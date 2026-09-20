"""Packager (phase 8a): builds the deliverable folder from an AuditResult.

Deterministic, no LLM — takes what the coordinator already produced
(Requirement, ExtractedDocuments, Findings, decision_log) and packages it
for handoff to a human. This folder is the end of Kagaz's involvement:
Kagaz never submits anything to any portal; a human takes it from here.

<student>_<scheme>/
  documents/          converted, portal-spec compliant (tools/formatting.py)
  form_values.html    field label -> value with copy buttons, for filling the form
  values.csv          the same data for a spreadsheet
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
#
# Each entry is (applies-to-this-form predicate, text). Showing all of
# them on every form was wrong: a form that never asks for a bank
# passbook has no DBT leg, so warning about NPCI seeding is noise that
# trains people to skim past the list — and skimming past it defeats the
# point of separating "checked" from "you must check".
_REJECTION_CAUSES: list[tuple[str, str]] = [
    (
        "bank_passbook",
        "NPCI/Aadhaar seeding status of the bank account — a passbook can look "
        "perfectly valid and still fail DBT credit if the account isn't NPCI-mapped "
        "to that Aadhaar. Check this on the NPCI mapper or with the bank directly.",
    ),
    (
        "bank_passbook",
        "Bank account holder name not matching the applicant's name exactly as "
        "the bank's own records have it (not just as printed on the passbook).",
    ),
    (
        "deadline",
        "Portal downtime or a missed deadline due to last-minute submission — "
        "Kagaz checks a document's validity against the scheme deadline, not "
        "whether the portal itself was reachable when you tried to submit.",
    ),
    (
        "dated_certificate",
        "Certificate validity per the *portal's* rules, which can be stricter "
        "than the certificate's own printed validity window (e.g. some portals "
        "only accept certificates issued in the current financial year "
        "regardless of printed expiry).",
    ),
    (
        "always",
        "Duplicate or prior-year application already on file for you under this "
        "scheme — not something any single document reveals.",
    ),
    (
        "eligibility",
        "Whether you personally meet this form's eligibility rules — Kagaz "
        "checks the documents you gave it against the document and format "
        "requirements it stated, not whether you or your institution qualify.",
    ),
]

_DATED_DOC_TYPES = {"income_certificate", "caste_certificate", "domicile_certificate"}


def relevant_rejection_causes(requirement: Requirement | None = None) -> list[str]:
    """The can't-verify causes that actually apply to this form.

    With no requirement (or one carrying nothing to go on) every cause is
    returned, since there's no basis for ruling any out.
    """
    if requirement is None:
        return [text for _applies, text in _REJECTION_CAUSES]

    doc_types = {rd.doc_type for rd in requirement.required_documents}
    applicable = {
        "always",
        *({"bank_passbook"} if "bank_passbook" in doc_types else set()),
        *({"deadline"} if requirement.deadline else set()),
        *({"dated_certificate"} if doc_types & _DATED_DOC_TYPES else set()),
        *(
            {"eligibility"}
            if (requirement.eligibility_criteria or requirement.max_family_income_inr)
            else set()
        ),
    }
    return [text for applies, text in _REJECTION_CAUSES if applies in applicable]


# Kept for callers that want the unfiltered list.
NON_DOCUMENT_REJECTION_CAUSES: list[str] = [text for _applies, text in _REJECTION_CAUSES]

_styles = getSampleStyleSheet()
_H1 = ParagraphStyle("PkgH1", parent=_styles["Heading1"], fontSize=16, spaceAfter=10)
_H2 = ParagraphStyle("PkgH2", parent=_styles["Heading2"], fontSize=13, spaceAfter=8, spaceBefore=10)
_BODY = ParagraphStyle("PkgBody", parent=_styles["Normal"], fontSize=10.5, leading=15, spaceAfter=4)
_EVIDENCE = ParagraphStyle("PkgEvidence", parent=_BODY, leftIndent=18, textColor="#444444")


# --------------------------------------------------------------------------
# documents/ — reformatted to the scheme's spec
# --------------------------------------------------------------------------


def _package_one_document(
    doc_type: str, source_path: Path, required: RequiredDoc | None, dest_dir: Path, problems: list[str]
) -> None:
    if not source_path.exists():
        return  # nothing to package if the source itself is missing

    label = doc_type.replace("_", " ")
    source_is_pdf = source_path.suffix.lower() == ".pdf"

    if doc_type in _IMAGE_DOC_TYPES:
        if source_is_pdf:
            # A PDF where the portal wants a photo/signature image.
            # Rasterising a PDF needs a renderer this project doesn't
            # ship, so pass the file through and say plainly that this one
            # still needs converting by hand — silently shipping a PDF the
            # portal will reject is worse.
            (dest_dir / f"{doc_type}.pdf").write_bytes(source_path.read_bytes())
            problems.append(
                f"{label}: you supplied a PDF, but this form wants an image. Kagaz copied the PDF "
                "through unchanged — export it as a JPG/PNG and re-run, or convert it before uploading."
            )
            return
        if required and required.dimensions_px and required.max_size_kb:
            format_photo(source_path, dest_dir / f"{doc_type}.jpg", required.dimensions_px, required.max_size_kb)
        else:
            # no spec to reformat against - pass the original through as-is
            (dest_dir / source_path.name).write_bytes(source_path.read_bytes())
        return

    formats = [f.lower() for f in (required.file_formats if required else [])]
    max_kb = (required.max_size_kb if required else None) or _DEFAULT_MAX_SIZE_KB

    if source_is_pdf:
        # Already the format most portals ask for. format_document_pdf
        # wraps an *image* into a PDF and would fail on PDF bytes with
        # "cannot identify image file" — which previously took the whole
        # package down after the audit had already finished.
        dest = dest_dir / f"{doc_type}.pdf"
        dest.write_bytes(source_path.read_bytes())
        size_kb = dest.stat().st_size / 1024
        if size_kb > max_kb:
            problems.append(
                f"{label}: your PDF is {size_kb:.0f}KB but this form's limit is {max_kb}KB. "
                "Kagaz can resize images to a size limit, but not re-compress a PDF — "
                "upload it as a JPG/PNG scan instead and Kagaz will fit it to the limit."
            )
        if formats and "pdf" not in formats:
            problems.append(
                f"{label}: this form asks for {'/'.join(formats).upper()} and you supplied a PDF. "
                "Upload a JPG/PNG scan and Kagaz will convert it to the format the form wants."
            )
        return

    if not formats or "pdf" in formats:
        format_document_pdf(source_path, dest_dir / f"{doc_type}.pdf", max_kb)
    else:
        convert_image_format(source_path, dest_dir / f"{doc_type}.{formats[0]}", formats[0])


def _package_documents(
    documents: list[ExtractedDocument],
    required_documents: list[RequiredDoc],
    dest_dir: Path,
    problems: list[str],
) -> None:
    required_by_type = {rd.doc_type: rd for rd in required_documents}
    dest_dir.mkdir(parents=True, exist_ok=True)
    for doc in documents:
        try:
            _package_one_document(
                doc.doc_type, doc.source_path, required_by_type.get(doc.doc_type), dest_dir, problems
            )
        except Exception as exc:  # noqa: BLE001 - one file must never cost the whole folder
            # The folder is the entire deliverable. Losing all of it —
            # the values sheet, the checklist, the report — because one
            # document wouldn't convert is the worst possible trade.
            problems.append(
                f"{doc.doc_type.replace('_', ' ')}: could not be reformatted ({exc}). "
                "The rest of this folder is still complete; convert this one by hand."
            )


# --------------------------------------------------------------------------
# values.csv
# --------------------------------------------------------------------------


def _values_of(doc: ExtractedDocument) -> dict[str, str]:
    """Everything readable off one document, including the two dates.

    issue_date and valid_until are parsed onto their own attributes
    rather than left in .fields, so a lookup that only read .fields could
    never surface them — a "Date of Issue" field on a form came back
    blank even when the date was printed plainly on the certificate.
    """
    values = dict(doc.fields)
    if doc.issue_date:
        values["issue_date"] = doc.issue_date.strftime("%d/%m/%Y")
    if doc.valid_until:
        values["valid_until"] = doc.valid_until.strftime("%d/%m/%Y")
    return values


def _values_by_doc_type(documents: list[ExtractedDocument]) -> dict[str, dict[str, str]]:
    return {doc.doc_type: _values_of(doc) for doc in documents}


def _aggregate_fields(documents: list[ExtractedDocument]) -> dict[str, str]:
    """Merge every document's values into one lookup, marksheet first (the
    same reference-document precedence cross_checker uses) so a name/dob
    collision resolves consistently rather than depending on dict order."""
    ordered = sorted(documents, key=lambda d: 0 if d.doc_type == "marksheet" else 1)
    aggregated: dict[str, str] = {}
    for doc in ordered:
        for key, value in _values_of(doc).items():
            aggregated.setdefault(key, value)
    return aggregated


# Words a form uses to name which document a field belongs to. "Income
# Certificate – Date of Issue" must read the income certificate's date,
# not whichever document happened to be merged first.
_DOC_HINTS: list[tuple[tuple[str, ...], str]] = [
    (("income certificate", "income cert"), "income_certificate"),
    (("caste certificate", "category certificate"), "caste_certificate"),
    (("domicile", "residence certificate"), "domicile_certificate"),
    (("marksheet", "mark sheet", "class 10", "class 12", "class x", "class xii", "qualifying exam"), "marksheet"),
    (("passbook", "bank account", "bank statement"), "bank_passbook"),
]


def _doc_type_hint(label: str) -> str | None:
    lowered = label.lower()
    for needles, doc_type in _DOC_HINTS:
        if any(n in lowered for n in needles):
            return doc_type
    return None


def _map_field_label(label: str) -> str | None:
    """Best-effort mapping from a portal's field wording to one of the
    internal keys verifiers actually populate. Returns None (never a
    guess) for anything not covered by what the five verifiers extract —
    that's most portal fields (Aadhaar number, IFSC code, course details,
    ...); those correctly end up blank in values.csv."""
    lowered = label.lower()
    # Order matters, in both directions. The qualified "name" labels must
    # beat the bare one ("Bank Name" is not the applicant's name), and the
    # bare one must beat the identifier patterns — a portal asking for
    # "Full Name (as per Aadhaar)" wants the name, not the Aadhaar number.
    if "father" in lowered or "guardian" in lowered:
        return "father_name"
    if "name" in lowered:
        if "bank" in lowered or "branch" in lowered:
            return "bank_name"
        if "institution" in lowered or "school" in lowered or "college" in lowered or "board" in lowered:
            return "institution"
        return "name"
    if "birth" in lowered or " dob" in f" {lowered}":
        return "dob"
    # Dates before anything else that could swallow them: "Income
    # Certificate – Date of Issue" is a date, not an income amount.
    if "valid" in lowered or "expiry" in lowered or "expires" in lowered:
        return "valid_until"
    if "issue" in lowered or "issued" in lowered:
        return "issue_date"
    if "year of passing" in lowered or "passing year" in lowered or "year of pass" in lowered:
        return "passing_year"
    if "aadhaar" in lowered or "aadhar" in lowered or "uid" in lowered:
        return "aadhaar_no"
    if "ifsc" in lowered:
        return "ifsc_code"
    if "bank account" in lowered or ("account" in lowered and ("no" in lowered or "number" in lowered)):
        return "account_no"
    # Certificate identifiers before the income-amount rule: "income
    # certificate no." asks for the certificate's number, and returning
    # the income figure for it was simply wrong.
    if "certificate" in lowered and (
        "no" in lowered or "number" in lowered or "id" in lowered or "confirmation" in lowered
    ):
        return "certificate_no"
    if "confirmation" in lowered or "acknowledgement" in lowered or "reference no" in lowered:
        return "certificate_no"
    if "income" in lowered:
        return "annual_income"
    if "caste" in lowered or "category" in lowered or "community" in lowered:
        return "caste_category"
    if "roll" in lowered or "enrol" in lowered or "registration no" in lowered:
        return "roll_no"
    if "percent" in lowered or "marks" in lowered or "cgpa" in lowered:
        return "marks_percent"
    if "institution" in lowered or "school" in lowered or "college" in lowered or "board" in lowered:
        return "institution"
    if "address" in lowered or "residence" in lowered or "domicile" in lowered:
        return "address"
    if "certificate" in lowered and ("no" in lowered or "number" in lowered):
        return "certificate_no"
    if "name" in lowered:
        return "name"
    return None


def _resolve_values(requirement: Requirement, documents: list[ExtractedDocument]) -> list[tuple[str, str, str]]:
    """(form's field label, value, source document) for every field the
    form asks for. Value is "" when no document supplied it — never a
    guess, because a wrong Aadhaar number pasted into a government form
    is worse than a blank one."""
    aggregated = _aggregate_fields(documents)
    by_type = _values_by_doc_type(documents)
    origin = _field_origins(documents)

    rows: list[tuple[str, str, str]] = []
    for label in requirement.required_fields:
        key = _map_field_label(label)
        if not key:
            rows.append((label, "", ""))
            continue

        # If the label names a document, read that document. Otherwise
        # fall back to the merged view.
        hint = _doc_type_hint(label)
        value = by_type.get(hint, {}).get(key) if hint else None
        source = hint.replace("_", " ") if (hint and value) else ""
        if not value:
            value = aggregated.get(key)
            source = origin.get(key, "") if value else ""

        rows.append((label, value or "", source))
    return rows


def _field_origins(documents: list[ExtractedDocument]) -> dict[str, str]:
    """Which document each value came from, so a wrong-looking value can
    be traced back to the page it was read off."""
    ordered = sorted(documents, key=lambda d: 0 if d.doc_type == "marksheet" else 1)
    origins: dict[str, str] = {}
    for doc in ordered:
        for key in _values_of(doc):
            origins.setdefault(key, doc.doc_type.replace("_", " "))
    return origins


def _write_values_csv(requirement: Requirement, documents: list[ExtractedDocument], dest_path: Path) -> None:
    with dest_path.open("w", newline="", encoding="utf-8") as f:
        writer = csv.writer(f)
        writer.writerow(["field_label", "value", "note"])
        for label, value, _source in _resolve_values(requirement, documents):
            writer.writerow([label, value, "" if value else "not found"])


def _write_values_html(
    requirement: Requirement, documents: list[ExtractedDocument], dest_path: Path, synthetic: bool = True
) -> None:
    """The form-filling sheet, as a page you can actually use.

    This file exists to be read by a person filling a web form field by
    field — nothing in Kagaz consumes it. A CSV was the wrong container
    for that: spreadsheets truncate long values in narrow cells, and
    getting one value onto the clipboard means fighting the grid. Here
    each value has its own Copy button, values wrap in full, and the
    source document is named next to each one.
    """
    rows = _resolve_values(requirement, documents)
    filled = sum(1 for _l, v, _s in rows if v)
    banner = (
        "SYNTHETIC DEMO DATA — no real students, no real documents"
        if synthetic
        else "Your documents — read live from the files you uploaded"
    )

    def esc(value: str) -> str:
        return (
            str(value)
            .replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;").replace('"', "&quot;")
        )

    body: list[str] = []
    for label, value, source in rows:
        if value:
            body.append(
                f'<tr><td class="lbl">{esc(label)}</td>'
                f'<td class="val"><span class="v" id="v{len(body)}">{esc(value)}</span>'
                f'<button type="button" class="copy" data-target="v{len(body)}">Copy</button></td>'
                f'<td class="src">{esc(source)}</td></tr>'
            )
        else:
            body.append(
                f'<tr class="empty"><td class="lbl">{esc(label)}</td>'
                f'<td class="val"><span class="none">not on any document you gave Kagaz — '
                f'fill this one in yourself</span></td><td class="src"></td></tr>'
            )

    html = f"""<!DOCTYPE html>
<html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Form values — {esc(requirement.scheme_name)}</title>
<style>
  body {{ font-family: -apple-system, "Segoe UI", Roboto, sans-serif; margin: 0; background: #f8fafc;
         color: #0f172a; font-size: 15px; line-height: 1.5; }}
  .wrap {{ max-width: 860px; margin: 0 auto; padding: 0 20px 60px; }}
  .banner {{ background: {"#7c2d12" if synthetic else "#14532d"}; color: #fff; text-align: center;
             padding: 9px 16px; font-size: 13px; font-weight: 600; }}
  h1 {{ font-size: 23px; margin: 28px 0 6px; letter-spacing: -.02em; }}
  p.lede {{ color: #64748b; margin: 0 0 20px; }}
  table {{ width: 100%; border-collapse: collapse; background: #fff; border: 1px solid #e2e8f0;
           border-radius: 10px; overflow: hidden; }}
  th {{ text-align: left; font-size: 11.5px; text-transform: uppercase; letter-spacing: .05em;
        color: #94a3b8; padding: 10px 14px; border-bottom: 1px solid #e2e8f0; }}
  td {{ padding: 12px 14px; border-bottom: 1px solid #f1f5f9; vertical-align: top; }}
  tr:last-child td {{ border-bottom: none; }}
  .lbl {{ font-weight: 600; width: 34%; }}
  .val {{ width: 46%; }}
  .v {{ display: inline-block; word-break: break-word; margin-right: 8px; }}
  .src {{ color: #94a3b8; font-size: 12.5px; width: 20%; }}
  .none {{ color: #b45309; font-size: 13.5px; }}
  tr.empty {{ background: #fffbeb; }}
  .copy {{ font: inherit; font-size: 12.5px; padding: 3px 10px; border: 1px solid #cbd5e1;
           background: #f8fafc; border-radius: 6px; cursor: pointer; }}
  .copy:hover {{ background: #eef2ff; border-color: #4f46e5; color: #4338ca; }}
  .copy.done {{ background: #ecfdf5; border-color: #047857; color: #047857; }}
  .foot {{ color: #94a3b8; font-size: 12.5px; margin-top: 18px; }}
  @media (max-width: 620px) {{
    .lbl, .val, .src {{ display: block; width: auto; }}
    td {{ padding: 8px 14px; }} tr {{ display: block; border-bottom: 1px solid #e2e8f0; }}
    th {{ display: none; }}
  }}
</style></head>
<body>
<div class="banner">{esc(banner)}</div>
<div class="wrap">
  <h1>{esc(requirement.scheme_name)}</h1>
  <p class="lede">Every field this form asks for, next to the value read off your own documents —
  {filled} of {len(rows)} filled. Copy each one straight into the portal so the spelling matches
  your documents exactly. Kagaz never guesses a value it couldn't find.</p>
  <table>
    <tr><th>Field on the form</th><th>Your value</th><th>Read from</th></tr>
    {"".join(body)}
  </table>
  <p class="foot">Generated by Kagaz. Advisory only — check each value against your own documents
  before submitting. Kagaz does not submit anything to any portal.</p>
</div>
<script>
  document.querySelectorAll(".copy").forEach(function (btn) {{
    btn.addEventListener("click", function () {{
      var el = document.getElementById(btn.getAttribute("data-target"));
      var text = el.textContent;
      function done() {{
        var old = btn.textContent; btn.textContent = "Copied"; btn.classList.add("done");
        setTimeout(function () {{ btn.textContent = old; btn.classList.remove("done"); }}, 1200);
      }}
      if (navigator.clipboard && navigator.clipboard.writeText) {{
        navigator.clipboard.writeText(text).then(done, function () {{ fallback(text, done); }});
      }} else {{ fallback(text, done); }}
    }});
  }});
  function fallback(text, done) {{
    var ta = document.createElement("textarea");
    ta.value = text; document.body.appendChild(ta); ta.select();
    try {{ document.execCommand("copy"); done(); }} catch (e) {{}}
    document.body.removeChild(ta);
  }}
</script>
</body></html>
"""
    dest_path.write_text(html, encoding="utf-8")


# --------------------------------------------------------------------------
# checklist.md
# --------------------------------------------------------------------------


def _write_checklist_md(
    requirement: Requirement,
    documents: list[ExtractedDocument],
    dest_path: Path,
    synthetic: bool = True,
    problems: list[str] | None = None,
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

    if missing:
        lines += [
            "",
            "## Still to do before you submit",
            "",
        ]
        lines += [
            f"- Get a **{doc_type.replace('_', ' ')}** and add it — this form requires it."
            for doc_type in missing
        ]

    if problems:
        lines += [
            "",
            "## Files Kagaz couldn't convert for you",
            "",
            "Everything else in this folder is ready. These need a hand:",
            "",
        ]
        lines += [f"- {p}" for p in problems]

    lines += [
        "",
        "## Kagaz cannot verify this — check it yourself",
        "",
        "These are common reasons applications get rejected that no document",
        "pipeline can see — they're facts about a portal or a bank account's",
        "linkage, not something printed on any document:",
        "",
    ]
    lines += [f"- {cause}" for cause in relevant_rejection_causes(requirement)]

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
    for cause in relevant_rejection_causes(result.requirement):
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


def package_audit(
    result: AuditResult,
    output_root: Path,
    synthetic: bool = True,
    problems: list[str] | None = None,
) -> Path:
    """Build the full deliverable folder for one AuditResult and return
    its path. synthetic=False (the real-account flow) swaps the "SYNTHETIC
    DEMO DATA" banner for a "YOUR DOCUMENTS" one in checklist.md and
    audit_report.pdf — everything else about the folder is identical.

    Anything that couldn't be reformatted is appended to `problems` and
    written into checklist.md, rather than raised. The folder is the whole
    deliverable; a single stubborn file must not take the values sheet,
    the checklist and the report down with it.
    """
    problems = problems if problems is not None else []
    dest_dir = Path(output_root) / f"{result.student_id}_{result.scheme_id}"
    dest_dir.mkdir(parents=True, exist_ok=True)

    _package_documents(
        result.extracted_documents, result.requirement.required_documents, dest_dir / "documents", problems
    )
    # The HTML sheet is the one a person actually fills the form from
    # (copy buttons, full values, no truncated cells); the CSV stays for
    # anyone who wants the same data in a spreadsheet.
    _write_values_html(
        result.requirement, result.extracted_documents, dest_dir / "form_values.html", synthetic=synthetic
    )
    _write_values_csv(result.requirement, result.extracted_documents, dest_dir / "values.csv")
    _write_checklist_md(
        result.requirement, result.extracted_documents, dest_dir / "checklist.md",
        synthetic=synthetic, problems=problems,
    )
    _write_audit_report_pdf(result, dest_dir / "audit_report.pdf", synthetic=synthetic)

    return dest_dir
