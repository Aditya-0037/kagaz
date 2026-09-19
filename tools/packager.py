"""Packager (phase 8a): builds the deliverable folder from an AuditResult.

Deterministic, no LLM — takes what the coordinator already produced
(Requirement, ExtractedDocuments, Findings, decision_log) and packages it
for handoff to a human. This folder is the end of Kagaz's involvement:
Kagaz never submits anything to any portal; a human takes it from here.

<student>_<scheme>/
  documents/          converted, portal-spec compliant (tools/formatting.py)
  values.csv          field label -> value, keyed to Requirement.required_fields
  audit_report.pdf    findings grouped by severity, evidence, decision log
  checklist.md        required vs found vs missing
"""

from __future__ import annotations

import csv
from pathlib import Path

from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import cm
from reportlab.platypus import Paragraph, SimpleDocTemplate, Spacer

from contracts import AuditResult, ExtractedDocument, Requirement, RequiredDoc
from tools.formatting import convert_image_format, format_document_pdf, format_photo

_IMAGE_DOC_TYPES = {"photo", "signature"}
_DEFAULT_MAX_SIZE_KB = 200  # used when a scheme's spec didn't state one

# Phase F: common reasons a scheme application gets rejected that a
# document-verification pipeline structurally cannot see, because they
# aren't facts on the document at all — they're facts about a portal, a
# bank account's linkage status, or a submission-time event. Listing them
# explicitly, and labeling them "check yourself," is the honest complement
# to Kagaz's document findings above: not a gap to apologize for, but a
# stated boundary of what documents alone can confirm. Static content, not
# an AI judgment call — nothing here is inferred from a specific student's
# documents.
NON_DOCUMENT_REJECTION_CAUSES: list[str] = [
    "NPCI/Aadhaar seeding status of the bank account — a passbook can look "
    "perfectly valid and still fail DBT credit if the account isn't NPCI-mapped "
    "to that Aadhaar. Check this on the NPCI mapper or with the bank directly.",
    "Bank account holder name not matching the applicant's name exactly as "
    "the bank's own records have it (not just as printed on the passbook).",
    "Portal downtime or a missed deadline due to last-minute submission — "
    "Kagaz checks a document's validity against the scheme deadline, not "
    "whether the portal itself was reachable when you tried to submit.",
    "Category/income-certificate validity per the *portal's* rules, which "
    "can be stricter than the certificate's own printed validity window "
    "(e.g. some portals only accept certificates issued in the current "
    "financial year regardless of printed expiry).",
    "Duplicate or prior-year application already on file for this student "
    "under this scheme — not something any single document reveals.",
    "Institution/course eligibility for this specific scheme — Kagaz "
    "verifies the documents you gave it against the scheme's stated "
    "document/format requirements, not whether your institution or course "
    "is itself eligible for the scheme.",
]

_styles = getSampleStyleSheet()
_H1 = ParagraphStyle("PkgH1", parent=_styles["Heading1"], fontSize=16, spaceAfter=10)
_H2 = ParagraphStyle("PkgH2", parent=_styles["Heading2"], fontSize=13, spaceAfter=8, spaceBefore=10)
_BODY = ParagraphStyle("PkgBody", parent=_styles["Normal"], fontSize=10.5, leading=15, spaceAfter=4)
_EVIDENCE = ParagraphStyle("PkgEvidence", parent=_BODY, leftIndent=18, textColor="#444444")


# --------------------------------------------------------------------------
# documents/ — reformatted to the scheme's spec
# --------------------------------------------------------------------------


def _package_one_document(doc_type: str, source_path: Path, required: RequiredDoc | None, dest_dir: Path) -> None:
    if not source_path.exists():
        return  # nothing to package if the source itself is missing

    if doc_type in _IMAGE_DOC_TYPES:
        if required and required.dimensions_px and required.max_size_kb:
            format_photo(source_path, dest_dir / f"{doc_type}.jpg", required.dimensions_px, required.max_size_kb)
        else:
            # no spec to reformat against - pass the original through as-is
            (dest_dir / source_path.name).write_bytes(source_path.read_bytes())
        return

    formats = [f.lower() for f in (required.file_formats if required else [])]
    max_kb = (required.max_size_kb if required else None) or _DEFAULT_MAX_SIZE_KB

    if not formats or "pdf" in formats:
        format_document_pdf(source_path, dest_dir / f"{doc_type}.pdf", max_kb)
    else:
        convert_image_format(source_path, dest_dir / f"{doc_type}.{formats[0]}", formats[0])


def _package_documents(documents: list[ExtractedDocument], required_documents: list[RequiredDoc], dest_dir: Path) -> None:
    required_by_type = {rd.doc_type: rd for rd in required_documents}
    dest_dir.mkdir(parents=True, exist_ok=True)
    for doc in documents:
        _package_one_document(doc.doc_type, doc.source_path, required_by_type.get(doc.doc_type), dest_dir)


# --------------------------------------------------------------------------
# values.csv
# --------------------------------------------------------------------------


def _aggregate_fields(documents: list[ExtractedDocument]) -> dict[str, str]:
    """Merge every document's fields into one lookup, marksheet first (the
    same reference-document precedence cross_checker uses) so a name/dob
    collision resolves consistently rather than depending on dict order."""
    ordered = sorted(documents, key=lambda d: 0 if d.doc_type == "marksheet" else 1)
    aggregated: dict[str, str] = {}
    for doc in ordered:
        for key, value in doc.fields.items():
            aggregated.setdefault(key, value)
    return aggregated


def _map_field_label(label: str) -> str | None:
    """Best-effort mapping from a portal's field wording to one of the
    internal keys verifiers actually populate. Returns None (never a
    guess) for anything not covered by what the five verifiers extract —
    that's most portal fields (Aadhaar number, IFSC code, course details,
    ...); those correctly end up blank in values.csv."""
    lowered = label.lower()
    if "father" in lowered or "guardian" in lowered:
        return "father_name"
    if "birth" in lowered or " dob" in f" {lowered}":
        return "dob"
    if "bank account" in lowered or ("account" in lowered and ("no" in lowered or "number" in lowered)):
        return "account_no"
    if "ifsc" in lowered:
        return None
    if "income" in lowered:
        return "annual_income"
    if "name" in lowered:
        return "name"
    return None


def _write_values_csv(requirement: Requirement, documents: list[ExtractedDocument], dest_path: Path) -> None:
    aggregated = _aggregate_fields(documents)
    with dest_path.open("w", newline="", encoding="utf-8") as f:
        writer = csv.writer(f)
        writer.writerow(["field_label", "value", "note"])
        for label in requirement.required_fields:
            internal_key = _map_field_label(label)
            value = aggregated.get(internal_key) if internal_key else None
            writer.writerow([label, value or "", "" if value else "not found"])


# --------------------------------------------------------------------------
# checklist.md
# --------------------------------------------------------------------------


def _write_checklist_md(
    requirement: Requirement, documents: list[ExtractedDocument], dest_path: Path, synthetic: bool = True
) -> None:
    found_types = {d.doc_type for d in documents}
    banner = (
        "SYNTHETIC DEMO DATA — no real students, no real documents."
        if synthetic
        else "YOUR DOCUMENTS — processed live, not synthetic data."
    )
    lines = [
        f"# Checklist — {requirement.scheme_name}",
        "",
        banner,
        "",
        "## Verified from your documents",
        "",
        "| Document | Required | Found |",
        "| --- | --- | --- |",
    ]
    for rd in requirement.required_documents:
        found = "found" if rd.doc_type in found_types else "**missing**"
        lines.append(f"| {rd.doc_type} | yes | {found} |")

    missing = [rd.doc_type for rd in requirement.required_documents if rd.doc_type not in found_types]
    lines.append("")
    lines.append("Missing: none." if not missing else f"Missing: {', '.join(missing)}.")

    lines += [
        "",
        "## Kagaz cannot verify this — check it yourself",
        "",
        "These are common reasons applications get rejected that no document",
        "pipeline can see — they're facts about a portal or a bank account's",
        "linkage, not something printed on any document:",
        "",
    ]
    lines += [f"- {cause}" for cause in NON_DOCUMENT_REJECTION_CAUSES]

    dest_path.write_text("\n".join(lines), encoding="utf-8")


# --------------------------------------------------------------------------
# audit_report.pdf
# --------------------------------------------------------------------------

_SEVERITY_ORDER = ["blocker", "worth_knowing", "likely_fine"]
_SEVERITY_LABELS = {"blocker": "Blockers", "worth_knowing": "Worth Knowing", "likely_fine": "Likely Fine"}


def _write_audit_report_pdf(result: AuditResult, dest_path: Path, synthetic: bool = True) -> None:
    banner = (
        "SYNTHETIC DEMO DATA — no real students, no real documents."
        if synthetic
        else "YOUR DOCUMENTS — processed live, not synthetic data."
    )
    story = [
        Paragraph(f"Kagaz Audit Report — {result.student_id}", _H1),
        Paragraph(f"Scheme: {result.requirement.scheme_name}", _BODY),
        Paragraph(banner, _BODY),
        Spacer(1, 4),
        Paragraph(
            "<b>This run is advisory only.</b> Kagaz never submits anything to any "
            "portal, and does not auto-correct anything above. A human reviews these "
            "findings and presses submit.",
            _BODY,
        ),
        Spacer(1, 10),
    ]

    story.append(Paragraph("Verified from your documents", _H2))
    if not result.findings:
        story.append(Paragraph("No findings. Every document checked out.", _BODY))
    for severity in _SEVERITY_ORDER:
        matching = [f for f in result.findings if f.severity == severity]
        if not matching:
            continue
        story.append(Paragraph(_SEVERITY_LABELS[severity], _H2))
        for finding in matching:
            story.append(Paragraph(f"<b>{finding.category}</b>: {finding.message}", _BODY))
            for ev in finding.evidence:
                story.append(Paragraph(f"&bull; {ev}", _EVIDENCE))

    story.append(Spacer(1, 10))
    story.append(Paragraph("Kagaz cannot verify this — check it yourself", _H2))
    story.append(
        Paragraph(
            "Common rejection reasons no document pipeline can see — facts about a "
            "portal or a bank account's linkage, not anything printed on a document:",
            _BODY,
        )
    )
    for cause in NON_DOCUMENT_REJECTION_CAUSES:
        story.append(Paragraph(f"&bull; {cause}", _EVIDENCE))

    if result.decision_log:
        story.append(Paragraph("Decision Log", _H2))
        for decision in result.decision_log:
            note = f" — {decision.note}" if decision.note else ""
            story.append(
                Paragraph(
                    f"{decision.decided_at.isoformat(timespec='seconds')} — "
                    f"<b>{decision.decision}</b> on \"{decision.finding.message}\"{note}",
                    _BODY,
                )
            )

    story.append(Spacer(1, 10))
    usage = result.token_usage.get("totalTokens")
    footer = f"Verification took {result.duration_seconds:.2f}s"
    if usage:
        footer += f" and {usage} tokens"
    story.append(Paragraph(footer + ".", _BODY))

    SimpleDocTemplate(
        str(dest_path), pagesize=A4, topMargin=2 * cm, bottomMargin=2 * cm, leftMargin=2 * cm, rightMargin=2 * cm
    ).build(story)


# --------------------------------------------------------------------------
# top level
# --------------------------------------------------------------------------


def package_audit(result: AuditResult, output_root: Path, synthetic: bool = True) -> Path:
    """Build the full deliverable folder for one AuditResult and return
    its path. synthetic=False (the real-account flow) swaps the "SYNTHETIC
    DEMO DATA" banner for a "YOUR DOCUMENTS" one in checklist.md and
    audit_report.pdf — everything else about the folder is identical."""
    dest_dir = Path(output_root) / f"{result.student_id}_{result.scheme_id}"
    dest_dir.mkdir(parents=True, exist_ok=True)

    _package_documents(result.extracted_documents, result.requirement.required_documents, dest_dir / "documents")
    _write_values_csv(result.requirement, result.extracted_documents, dest_dir / "values.csv")
    _write_checklist_md(result.requirement, result.extracted_documents, dest_dir / "checklist.md", synthetic=synthetic)
    _write_audit_report_pdf(result, dest_dir / "audit_report.pdf", synthetic=synthetic)

    return dest_dir
