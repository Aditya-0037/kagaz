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

import os
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

from agents.cross_checker import audit_student, income_findings
from agents.escalation import DecisionProvider, run_escalations
from agents.requirement_extractor import extract_requirement_from_pdf
from agents.verifiers import VERIFIERS, generic
from contracts import AuditResult, ExtractedDocument, Finding, Requirement, RequiredDoc
from tools.doc_types import CANONICAL_DOC_TYPES, EXPIRING_DOC_TYPES
from tools.image_checks import IMAGE_CHECKS
from tools.ocr import DEFAULT_CACHE_DIR as OCR_CACHE_DIR
from tools.ocr import extract_text
from tools.retry import is_transient

STUDENTS_DIR = Path(__file__).parent.parent / "fixtures" / "students"

# Real documents' OCR text must never land in the committed fixtures
# directory — that is git-tracked and gets pushed publicly. Real-account
# runs get this scratch directory instead (outbox/ is gitignored), and it
# is wiped per run by api/real_run_state.py.
REAL_OCR_CACHE_DIR = Path(__file__).parent.parent / "outbox" / "real_scratch" / "ocr_cache"

# A positive value caps concurrent document verifications. Set
# KAGAZ_MAX_PARALLEL_VERIFICATIONS=0 to run every document in an audit at
# once. The deployed default is deliberately five, while the Cloud Run
# service opts into zero because Gemini 2.5 Flash uses Dynamic Shared Quota
# rather than a fixed per-minute project quota.
DEFAULT_MAX_PARALLEL_VERIFICATIONS = 5


def _verification_workers(document_count: int) -> int:
    """Return the configured parallelism, bounded by available work.

    A zero environment value means "no application-side cap"; malformed
    values fall back to the conservative default instead of breaking an
    applicant's audit.
    """
    configured = os.getenv("KAGAZ_MAX_PARALLEL_VERIFICATIONS")
    try:
        requested = DEFAULT_MAX_PARALLEL_VERIFICATIONS if configured is None else int(configured)
    except ValueError:
        requested = DEFAULT_MAX_PARALLEL_VERIFICATIONS
    return max(1, document_count if requested <= 0 else min(requested, document_count))


def apply_deadline(requirement: Requirement) -> Requirement:
    """Copy requirement.deadline onto must_be_valid_on for every
    RequiredDoc whose doc_type expires (see EXPIRING_DOC_TYPES). Returns a
    new Requirement; the input is not mutated. A no-op if there's no
    deadline to apply."""
    if requirement.deadline is None:
        return requirement

    # Known expiring types, plus anything Kagaz doesn't recognise: a
    # custom document ("migration certificate", "disability certificate")
    # may well carry a validity window, and cross_checker skips any
    # document whose valid_until came back empty — so setting this for an
    # unknown type can only add a real finding, never a false one.
    updated_docs = [
        rd.model_copy(update={"must_be_valid_on": requirement.deadline})
        if rd.doc_type in EXPIRING_DOC_TYPES or rd.doc_type not in CANONICAL_DOC_TYPES
        else rd
        for rd in requirement.required_documents
    ]
    return requirement.model_copy(update={"required_documents": updated_docs})


def _document_path(student_id: str, doc_type: str) -> Path:
    return STUDENTS_DIR / student_id / "documents" / f"{doc_type}.jpg"


def _verify_one(
    doc_path: Path,
    required: RequiredDoc,
    subject_id: str,
    llm_mode: str | None = None,
    ocr_cache_dir: Path | None = None,
) -> tuple[ExtractedDocument, dict]:
    """Deterministic dispatch by doc_type — no LLM decides which verifier
    runs, Python already knows from the Requirement. subject_id is just a
    cache-key/log label (a student_id for the demo flow, a user_id for the
    real-account flow) — it never affects which verifier runs."""
    doc_type = required.doc_type

    if doc_type in IMAGE_CHECKS:
        return IMAGE_CHECKS[doc_type](doc_path, required), {}

    ocr_text = extract_text(doc_path, llm_mode=llm_mode, cache_dir=ocr_cache_dir or OCR_CACHE_DIR)

    if doc_type in VERIFIERS:
        return VERIFIERS[doc_type](ocr_text, doc_path, student_id=subject_id, llm_mode=llm_mode)

    # A document type Kagaz has no dedicated agent for — a second
    # marksheet, an Aadhaar card, a migration certificate. Read it for
    # identity fields anyway so it still takes part in the name/DOB
    # cross-check, which is where a mismatch would actually show up.
    return generic.verify(
        ocr_text,
        doc_path,
        student_id=subject_id,
        llm_mode=llm_mode,
        doc_type=doc_type,
        doc_label=required.notes or doc_type.replace("_", " "),
    )


def _missing_document_findings(requirement: Requirement, documents: dict[str, Path]) -> list[Finding]:
    """A required doc_type with no entry in `documents` at all (never
    uploaded, never matched from the locker) is unambiguous: nothing to
    verify, and nothing a name/date cross-check could possibly catch. This
    never fires for the demo flow — every demo student has every required
    file on disk — but the real-account flow lets a user skip a document,
    and that has to surface as a real blocker, not silently vanish."""
    return [
        Finding(
            severity="blocker",
            category="missing",
            message=f"No {required.doc_type.replace('_', ' ')} was provided for this application.",
            evidence=[f"Required by the scheme; no document was uploaded or selected for {required.doc_type!r}."],
            needs_human=True,
        )
        for required in requirement.required_documents
        if required.doc_type not in documents
    ]


def run_audit_for_documents(
    subject_id: str,
    scheme_id: str,
    requirement: Requirement,
    documents: dict[str, Path],
    llm_mode: str | None = None,
    ocr_cache_dir: Path | None = None,
) -> AuditResult:
    """The reusable core of a run: verify whichever of requirement's
    required_documents subject actually has a file for (in parallel),
    cross-check, and return the AuditResult. A required doc_type with no
    entry in `documents` simply isn't verified — audit_student already
    reports it as a missing-document finding, same as a demo student
    without that file on disk."""
    start = time.monotonic()

    extracted: list[ExtractedDocument] = []
    token_usage: dict[str, int] = {}

    unreadable: list[Finding] = []
    to_verify = [required for required in requirement.required_documents if required.doc_type in documents]
    with ThreadPoolExecutor(max_workers=_verification_workers(len(to_verify))) as executor:
        futures = {
            executor.submit(
                _verify_one, documents[required.doc_type], required, subject_id, llm_mode, ocr_cache_dir
            ): required
            for required in to_verify
        }
        for future in as_completed(futures):
            required = futures[future]
            try:
                document, usage = future.result()
            except Exception as exc:  # noqa: BLE001 - one bad file must not kill the whole run
                doc_label = required.doc_type.replace("_", " ")
                if is_transient(exc):
                    # A rate limit or a provider blip is Kagaz's problem,
                    # not a defect in the user's document. Saying "could
                    # not read your file" here would send someone off to
                    # re-scan a perfectly good certificate.
                    unreadable.append(
                        Finding(
                            severity="worth_knowing",
                            category="format",
                            message=f"Kagaz couldn't check your {doc_label} — the document service was busy, not a problem with your file.",
                            evidence=[f"Provider returned: {exc}"],
                            suggested_action="Run this application again in a minute; the document itself looks fine.",
                        )
                    )
                else:
                    # A corrupt scan, a password-protected PDF, a file
                    # that isn't really a document — report it against
                    # that one document and keep auditing the rest.
                    unreadable.append(
                        Finding(
                            severity="blocker",
                            category="format",
                            message=f"Kagaz could not read the file provided for {doc_label}.",
                            evidence=[
                                f"{documents[required.doc_type].name}: {exc}",
                                "Upload a clear image (JPG/PNG) or a text-based PDF and run this again.",
                            ],
                            needs_human=True,
                        )
                    )
                continue
            extracted.append(document)
            for key, value in usage.items():
                token_usage[key] = token_usage.get(key, 0) + value

    # Parallel execution means completion order isn't submission order —
    # sort for a deterministic result regardless of scheduling.
    extracted.sort(key=lambda d: d.doc_type)

    findings = (
        _missing_document_findings(requirement, documents)
        + unreadable
        + income_findings(extracted, requirement.max_family_income_inr)
        + audit_student(extracted, requirement.required_documents)
    )

    return AuditResult(
        student_id=subject_id,
        scheme_id=scheme_id,
        requirement=requirement,
        extracted_documents=extracted,
        findings=findings,
        token_usage=token_usage,
        duration_seconds=round(time.monotonic() - start, 3),
    )


def run_audit(student_id: str, scheme_id: str, scheme_name: str, scheme_pdf_path: Path | str) -> AuditResult:
    """Run one demo student through the full pipeline: extract this
    scheme's requirements, verify this student's pre-seeded documents
    against them, cross-check, and package the result."""
    requirement = apply_deadline(extract_requirement_from_pdf(scheme_pdf_path, scheme_id, scheme_name))
    documents = {
        required.doc_type: _document_path(student_id, required.doc_type) for required in requirement.required_documents
    }
    return run_audit_for_documents(student_id, scheme_id, requirement, documents)


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


def run_real_audit_with_escalation(
    user_id: str,
    scheme_id: str,
    requirement: Requirement,
    documents: dict[str, Path],
    decision_provider: DecisionProvider,
) -> AuditResult:
    """The real-account flow's equivalent of run_audit_with_escalation:
    the Requirement is already extracted (agents/scheme_input.py +
    extract_requirement_from_text, forced llm_mode="live"), and documents
    are local temp-file downloads of the user's locker uploads rather than
    pre-seeded fixtures. Verification is forced live too — real documents
    are never written into the committed replay cache, and their OCR text
    goes to a gitignored scratch directory rather than fixtures/."""
    requirement = apply_deadline(requirement)
    result = run_audit_for_documents(
        user_id, scheme_id, requirement, documents, llm_mode="live", ocr_cache_dir=REAL_OCR_CACHE_DIR
    )
    decision_log = run_escalations(result.findings, decision_provider)
    return result.model_copy(update={"decision_log": decision_log})
