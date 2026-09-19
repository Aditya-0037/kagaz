"""Coordinator: owns the end-to-end audit flow.

apply_deadline() lives here rather than in the extractor deliberately.
agents/requirement_extractor._merge always sets must_be_valid_on=None on
every RequiredDoc — the extractor doesn't guess a per-document validity
policy from the model. Left unfixed, agents/cross_checker._validity_findings
skips any document whose must_be_valid_on is None, so wired end-to-end no
expiry finding could ever fire: mohammed_irfan's income certificate, which
expires 11 days before the scheme deadline, would silently pass. The
existing cross-checker test only ever passed because it hand-built a
RequiredDoc with must_be_valid_on already set.

The fix belongs in the coordinator because "which documents must stay
valid through the deadline" is a policy decision about how the pipeline
uses a Requirement, not a fact the extractor can read off a scheme PDF.

run_audit() is the rest of the coordinator: the Workflow multi-agent
pattern (see docs/sdk-notes.md for why Workflow — plain-code orchestration
— was chosen over Graph/Swarm). Requirement extraction -> apply_deadline
-> per-document verification, dispatched deterministically by doc_type and
run in parallel (independent calls, no data dependency between them) ->
cross-check (zero LLM calls) -> AuditResult.

run_audit_with_escalation() (phase 6) layers the escalation interrupt on
top: every Finding with needs_human=True gets raised as a real,
one-at-a-time Strands interrupt (agents/escalation.py) and resolved via
decision_provider before the run finishes.
"""

from __future__ import annotations

import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

from agents.cross_checker import audit_student
from agents.escalation import DecisionProvider, run_escalations
from agents.requirement_extractor import extract_requirement_from_pdf
from agents.verifiers import VERIFIERS
from contracts import AuditResult, ExtractedDocument, Requirement, RequiredDoc
from tools.doc_types import EXPIRING_DOC_TYPES
from tools.image_checks import IMAGE_CHECKS
from tools.ocr import extract_text

STUDENTS_DIR = Path(__file__).parent.parent / "fixtures" / "students"


def apply_deadline(requirement: Requirement) -> Requirement:
    """Copy requirement.deadline onto must_be_valid_on for every
    RequiredDoc whose doc_type expires (see EXPIRING_DOC_TYPES). Returns a
    new Requirement; the input is not mutated. A no-op if there's no
    deadline to apply."""
    if requirement.deadline is None:
        return requirement

    updated_docs = [
        rd.model_copy(update={"must_be_valid_on": requirement.deadline})
        if rd.doc_type in EXPIRING_DOC_TYPES
        else rd
        for rd in requirement.required_documents
    ]
    return requirement.model_copy(update={"required_documents": updated_docs})


def _document_path(student_id: str, doc_type: str) -> Path:
    return STUDENTS_DIR / student_id / "documents" / f"{doc_type}.jpg"


def _verify_one(student_id: str, required: RequiredDoc) -> tuple[ExtractedDocument, dict]:
    """Deterministic dispatch by doc_type — no LLM decides which verifier
    runs, Python already knows from the Requirement."""
    doc_type = required.doc_type
    source_path = _document_path(student_id, doc_type)

    if doc_type in IMAGE_CHECKS:
        return IMAGE_CHECKS[doc_type](source_path, required), {}

    if doc_type in VERIFIERS:
        ocr_text = extract_text(source_path)
        return VERIFIERS[doc_type](ocr_text, source_path, student_id=student_id)

    raise ValueError(f"No verifier or image check registered for doc_type {doc_type!r}")


def run_audit(student_id: str, scheme_id: str, scheme_name: str, scheme_pdf_path: Path | str) -> AuditResult:
    """Run one student through the full pipeline: extract this scheme's
    requirements, verify this student's documents against them (in
    parallel), cross-check, and package the result."""
    start = time.monotonic()

    requirement = extract_requirement_from_pdf(scheme_pdf_path, scheme_id, scheme_name)
    requirement = apply_deadline(requirement)

    documents: list[ExtractedDocument] = []
    token_usage: dict[str, int] = {}

    with ThreadPoolExecutor(max_workers=max(1, len(requirement.required_documents))) as executor:
        futures = [
            executor.submit(_verify_one, student_id, required) for required in requirement.required_documents
        ]
        for future in as_completed(futures):
            document, usage = future.result()
            documents.append(document)
            for key, value in usage.items():
                token_usage[key] = token_usage.get(key, 0) + value

    # Parallel execution means completion order isn't submission order —
    # sort for a deterministic result regardless of scheduling.
    documents.sort(key=lambda d: d.doc_type)

    findings = audit_student(documents, requirement.required_documents)

    return AuditResult(
        student_id=student_id,
        scheme_id=scheme_id,
        requirement=requirement,
        extracted_documents=documents,
        findings=findings,
        token_usage=token_usage,
        duration_seconds=round(time.monotonic() - start, 3),
    )


def run_audit_with_escalation(
    student_id: str,
    scheme_id: str,
    scheme_name: str,
    scheme_pdf_path: Path | str,
    decision_provider: DecisionProvider,
) -> AuditResult:
    """run_audit(), then escalate every needs_human Finding — one real
    interrupt at a time, never batched — resolving each through
    decision_provider before returning. The decision_log on the result is
    the audit trail."""
    result = run_audit(student_id, scheme_id, scheme_name, scheme_pdf_path)
    decision_log = run_escalations(result.findings, decision_provider)
    return result.model_copy(update={"decision_log": decision_log})
