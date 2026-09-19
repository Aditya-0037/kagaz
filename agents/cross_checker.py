"""Cross-checker: compares fields across one student's documents.

Despite living under agents/ (it is one node the coordinator's graph will
call in a later phase), this makes zero LLM calls — spec section 6.3 is
explicit that this must be pure, tested Python, not a prompt. The LLM's job
(later phases) is to explain a Finding to a human; this module decides
whether one exists.

Nothing is ever auto-corrected and nothing is ever blocked from proceeding.
Findings are advice with reasons attached, in three severity tiers. Only a
"blocker" sets needs_human=True — that is the one thing that later triggers
the coordinator's escalation interrupt (spec section 6.6). likely_fine and
worth_knowing are informational only.
"""

from __future__ import annotations

from datetime import date

from contracts import ExtractedDocument, Finding, RequiredDoc
from tools.dates import check_validity, compare_dob
from tools.money import format_inr, parse_inr
from tools.name_match import compare_names

_REFERENCE_DOC_PRIORITY = ("marksheet",)


def _pick_reference(documents: list[ExtractedDocument]) -> ExtractedDocument | None:
    by_type = {doc.doc_type: doc for doc in documents}
    for doc_type in _REFERENCE_DOC_PRIORITY:
        if doc_type in by_type and by_type[doc_type].fields.get("name"):
            return by_type[doc_type]
    for doc in documents:
        if doc.fields.get("name"):
            return doc
    return None


def _name_findings(documents: list[ExtractedDocument]) -> list[Finding]:
    reference = _pick_reference(documents)
    if reference is None:
        return []

    findings = []
    for doc in documents:
        if doc is reference or not doc.fields.get("name"):
            continue
        comparison = compare_names(reference.fields["name"], doc.fields["name"])
        if comparison.verdict == "match":
            continue
        findings.append(
            Finding(
                severity=comparison.verdict,
                category="name_mismatch",
                message=comparison.reason,
                evidence=[
                    f"{reference.doc_type}: {reference.fields['name']}",
                    f"{doc.doc_type}: {doc.fields['name']}",
                ],
                needs_human=(comparison.verdict == "blocker"),
            )
        )
    return findings


def _dob_findings(documents: list[ExtractedDocument]) -> list[Finding]:
    reference = _pick_reference(documents)
    if reference is None or not reference.fields.get("dob"):
        return []

    findings = []
    for doc in documents:
        if doc is reference or not doc.fields.get("dob"):
            continue
        result = compare_dob(reference.fields["dob"], doc.fields["dob"])
        if result is None:
            continue
        findings.append(
            Finding(
                severity=result.verdict,
                category="dob_mismatch",
                message=result.reason,
                evidence=[
                    f"{reference.doc_type}: DOB {reference.fields['dob']}",
                    f"{doc.doc_type}: DOB {doc.fields['dob']}",
                ],
                needs_human=(result.verdict == "blocker"),
            )
        )
    return findings


def _validity_findings(
    documents: list[ExtractedDocument],
    required_documents: list[RequiredDoc],
    today: date | None,
) -> list[Finding]:
    required_by_type = {rd.doc_type: rd for rd in required_documents}
    findings = []
    for doc in documents:
        required = required_by_type.get(doc.doc_type)
        if required is None or required.must_be_valid_on is None:
            continue
        result = check_validity(doc.valid_until, required.must_be_valid_on, today)
        if result is None:
            continue
        findings.append(
            Finding(
                severity=result.verdict,
                category="expired",
                message=result.reason,
                evidence=[
                    f"{doc.doc_type}: valid_until "
                    f"{doc.valid_until.isoformat() if doc.valid_until else 'unknown'}"
                ],
                needs_human=(result.verdict == "blocker"),
            )
        )
    return findings


def income_findings(documents: list[ExtractedDocument], max_family_income_inr: int | None) -> list[Finding]:
    """Compare the family income on the income certificate against the
    scheme's stated ceiling. Deterministic arithmetic, no LLM — a scheme
    rejects an otherwise-perfect application when the income on the
    certificate is over the limit, and that is checkable.

    Three outcomes, all honest:
      - over the limit            -> blocker, needs a human
      - within the limit          -> no finding (nothing is wrong)
      - income unreadable/absent  -> worth_knowing, so it is never
                                     silently treated as "passed"
    """
    if max_family_income_inr is None:
        return []

    limit_text = format_inr(max_family_income_inr)
    stated = next(
        (doc.fields["annual_income"] for doc in documents if doc.fields.get("annual_income")),
        None,
    )
    if stated is None:
        return [
            Finding(
                severity="worth_knowing",
                category="eligibility",
                message=f"This scheme caps family income at {limit_text} per year, and Kagaz could not read an income figure from your documents.",
                evidence=["No annual income value was extracted from the income certificate."],
                suggested_action="Check your income certificate's figure against the scheme's limit yourself.",
            )
        ]

    amount = parse_inr(stated)
    if amount is None:
        return [
            Finding(
                severity="worth_knowing",
                category="eligibility",
                message=f"This scheme caps family income at {limit_text} per year; the figure on your certificate ({stated}) could not be read as an amount.",
                evidence=[f"Income certificate states: {stated}"],
                suggested_action="Compare the figure on your certificate against the scheme's limit yourself.",
            )
        ]

    if amount > max_family_income_inr:
        return [
            Finding(
                severity="blocker",
                category="eligibility",
                message=f"Family income {format_inr(amount)} is above this scheme's limit of {limit_text} per year.",
                evidence=[
                    f"Income certificate states: {stated} ({format_inr(amount)})",
                    f"Scheme's stated ceiling: {limit_text} per year",
                ],
                suggested_action="Applications over the income ceiling are normally rejected. Check whether a different income certificate applies, or whether this scheme has a higher-income category.",
                needs_human=True,
            )
        ]

    return []


def audit_student(
    documents: list[ExtractedDocument],
    required_documents: list[RequiredDoc] | None = None,
    today: date | None = None,
) -> list[Finding]:
    """Run every cross-document check for one student and return the
    resulting Findings. Order: name mismatches, DOB mismatches, validity
    windows."""
    findings: list[Finding] = []
    findings.extend(_name_findings(documents))
    findings.extend(_dob_findings(documents))
    if required_documents:
        findings.extend(_validity_findings(documents, required_documents, today))
    return findings
