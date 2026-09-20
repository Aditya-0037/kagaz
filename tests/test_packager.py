import csv
from pathlib import Path

import pytest

from agents.coordinator import run_audit
from tools.packager import package_audit

SCHEMES_DIR = Path(__file__).parent.parent / "fixtures" / "schemes"
SCHEME_A_PDF = SCHEMES_DIR / "scheme_a_postmatric.pdf"
SCHEME_A_NAME = "Post-Matric Scholarship 2026-27"


@pytest.fixture(autouse=True)
def _replay_mode(monkeypatch):
    monkeypatch.setenv("KAGAZ_LLM_MODE", "replay")
    monkeypatch.setenv("KAGAZ_MODEL_PROVIDER", "vertex")


@pytest.fixture(scope="module")
def priya_result():
    # Module-scoped fixtures are set up before function-scoped ones (like
    # the autouse _replay_mode above), regardless of declaration order —
    # so this needs its own env, not a reliance on _replay_mode having
    # already run. (This only stayed invisible before because the old
    # default provider happened to also be "ollama".)
    with pytest.MonkeyPatch.context() as mp:
        mp.setenv("KAGAZ_LLM_MODE", "replay")
        mp.setenv("KAGAZ_MODEL_PROVIDER", "vertex")
        return run_audit("priya_nair", "scheme_a_postmatric", SCHEME_A_NAME, SCHEME_A_PDF)


def test_package_creates_expected_folder_structure(tmp_path, priya_result):
    dest = package_audit(priya_result, tmp_path)

    assert dest == tmp_path / "priya_nair_scheme_a_postmatric"
    assert (dest / "documents").is_dir()
    assert (dest / "values.csv").is_file()
    assert (dest / "checklist.md").is_file()
    assert (dest / "audit_report.pdf").is_file()


def test_documents_are_reformatted_to_spec(tmp_path, priya_result):
    dest = package_audit(priya_result, tmp_path)
    documents_dir = dest / "documents"

    # priya_nair's photo is deliberately oversized - the packaged version
    # must land inside the scheme's spec (50KB, 276x354px)
    photo_path = documents_dir / "photo.jpg"
    assert photo_path.exists()
    assert photo_path.stat().st_size / 1024 <= 50

    # certificates required as PDF must actually be PDF, not the source JPEG
    income_pdf = documents_dir / "income_certificate.pdf"
    assert income_pdf.exists()
    assert income_pdf.read_bytes()[:5] == b"%PDF-"
    assert income_pdf.stat().st_size / 1024 <= 200


def test_source_documents_are_never_modified(tmp_path, priya_result):
    original_photo = Path("fixtures/students/priya_nair/documents/photo.jpg")
    before = original_photo.read_bytes()
    package_audit(priya_result, tmp_path)
    assert original_photo.read_bytes() == before


def test_values_csv_has_a_row_per_required_field_never_invents_values(tmp_path, priya_result):
    dest = package_audit(priya_result, tmp_path)
    with (dest / "values.csv").open(encoding="utf-8") as f:
        rows = list(csv.DictReader(f))

    assert len(rows) == len(priya_result.requirement.required_fields)
    labels = {row["field_label"] for row in rows}
    assert labels == set(priya_result.requirement.required_fields)

    by_label = {row["field_label"]: row for row in rows}
    # exact portal wording is model-dependent (e.g. "Full Name" vs "Full
    # Name (as per Aadhaar)") - match on the substring the mapping itself
    # keys off, not a hardcoded exact label
    full_name_label = next(label for label in by_label if "name" in label.lower() and "father" not in label.lower())
    assert by_label[full_name_label]["value"] == "Priya Ramesh Nair"
    assert by_label[full_name_label]["note"] == ""

    # nothing our verifiers never extract (Aadhaar Number) may have a
    # fabricated value - it must show up blank with a "not found" note
    assert by_label["Aadhaar Number"]["value"] == ""
    assert by_label["Aadhaar Number"]["note"] == "not found"


def test_checklist_md_shows_all_required_documents_found(tmp_path, priya_result):
    dest = package_audit(priya_result, tmp_path)
    content = (dest / "checklist.md").read_text(encoding="utf-8")
    assert "Missing: none." in content
    for doc_type in {rd.doc_type for rd in priya_result.requirement.required_documents}:
        assert doc_type in content


def test_checklist_md_reports_a_missing_document(tmp_path, priya_result):
    trimmed = priya_result.model_copy(
        update={"extracted_documents": [d for d in priya_result.extracted_documents if d.doc_type != "signature"]}
    )
    dest = package_audit(trimmed, tmp_path)
    content = (dest / "checklist.md").read_text(encoding="utf-8")
    assert "Missing: signature." in content


def test_audit_report_pdf_is_a_real_pdf_and_mentions_advisory_only(tmp_path, priya_result):
    dest = package_audit(priya_result, tmp_path)
    pdf_bytes = (dest / "audit_report.pdf").read_bytes()
    assert pdf_bytes[:5] == b"%PDF-"

    import pdfplumber
    import io

    with pdfplumber.open(io.BytesIO(pdf_bytes)) as pdf:
        text = "\n".join(page.extract_text() or "" for page in pdf.pages)
    assert "advisory" in text.lower()
    assert "SYNTHETIC" in text


def test_audit_report_pdf_lists_findings_grouped_by_severity():
    import io

    import pdfplumber

    from agents.coordinator import run_audit_with_escalation
    from agents.escalation import scripted_decision_provider

    result = run_audit_with_escalation(
        "mohammed_irfan",
        "scheme_a_postmatric",
        SCHEME_A_NAME,
        SCHEME_A_PDF,
        scripted_decision_provider([("override", "checked manually"), ("accept", None)]),
    )

    import tempfile

    with tempfile.TemporaryDirectory() as tmp:
        dest = package_audit(result, Path(tmp))
        with pdfplumber.open(dest / "audit_report.pdf") as pdf:
            text = "\n".join(page.extract_text() or "" for page in pdf.pages)

    assert "Blockers" in text
    assert "Decision Log" in text
    assert "override" in text
    assert "checked manually" in text


def _result_with_source(priya_result, doc_type, source_path):
    """priya's AuditResult, but one document points at a different file."""
    docs = []
    for d in priya_result.extracted_documents:
        docs.append(d.model_copy(update={"source_path": source_path}) if d.doc_type == doc_type else d)
    return priya_result.model_copy(update={"extracted_documents": docs})


def test_a_pdf_source_is_packaged_not_crashed_on(priya_result, tmp_path):
    # Regression: format_document_pdf opens the source with PIL, so a user
    # who uploaded a PDF crashed packaging with "cannot identify image
    # file" — AFTER the audit had finished, throwing away the entire
    # folder: values sheet, checklist and report included.
    from tools.packager import package_audit

    pdf = tmp_path / "source.pdf"
    pdf.write_bytes((Path(__file__).parent.parent / "fixtures" / "schemes" / "scheme_a_postmatric.pdf").read_bytes())

    problems: list[str] = []
    dest = package_audit(_result_with_source(priya_result, "income_certificate", pdf), tmp_path, problems=problems)

    # the whole folder still exists
    assert (dest / "form_values.html").is_file()
    assert (dest / "checklist.md").is_file()
    assert (dest / "audit_report.pdf").is_file()
    # and the PDF came through as a PDF
    assert (dest / "documents" / "income_certificate.pdf").is_file()


def test_one_unconvertible_file_does_not_cost_the_whole_folder(priya_result, tmp_path):
    from tools.packager import package_audit

    junk = tmp_path / "broken.jpg"
    junk.write_bytes(b"not an image at all")

    problems: list[str] = []
    dest = package_audit(_result_with_source(priya_result, "marksheet", junk), tmp_path, problems=problems)

    assert (dest / "form_values.html").is_file()
    assert (dest / "checklist.md").is_file()
    assert any("marksheet" in p for p in problems)
    # and the user is told, in the folder itself
    assert "couldn't convert" in (dest / "checklist.md").read_text(encoding="utf-8")


def test_checklist_lists_what_is_still_needed(priya_result, tmp_path):
    from contracts import RequiredDoc
    from tools.packager import package_audit

    req = priya_result.requirement
    trimmed = priya_result.model_copy(
        update={
            "requirement": req.model_copy(
                update={"required_documents": list(req.required_documents) + [RequiredDoc(doc_type="ews_certificate")]}
            )
        }
    )
    dest = package_audit(trimmed, tmp_path)
    text = (dest / "checklist.md").read_text(encoding="utf-8")
    assert "Still to do before you submit" in text
    assert "ews certificate" in text


def test_dates_printed_on_a_certificate_reach_the_form_sheet():
    # Regression: issue_date/valid_until are parsed onto their own
    # attributes instead of .fields, and the value lookup only read
    # .fields — so a "Date of Issue" field came back blank even when the
    # date was printed plainly on the certificate.
    from datetime import date as _date

    from contracts import ExtractedDocument, Requirement, RequiredDoc
    from tools.packager import _resolve_values

    doc = ExtractedDocument(
        doc_type="income_certificate",
        source_path="income.jpg",
        fields={"certificate_no": "INC-2026-0042"},
        issue_date=_date(2026, 5, 29),
        valid_until=_date(2027, 5, 28),
        extraction_confidence=1.0,
    )
    req = Requirement(
        scheme_id="s", scheme_name="S",
        required_documents=[RequiredDoc(doc_type="income_certificate")],
        required_fields=["Income Certificate – Date of Issue", "income certificate no."],
        source="text", confidence=1.0,
    )

    values = {label: value for label, value, _src in _resolve_values(req, [doc])}
    assert values["Income Certificate – Date of Issue"] == "29/05/2026"
    # and the certificate number is the number, not the income amount
    assert values["income certificate no."] == "INC-2026-0042"


def test_a_field_naming_a_document_reads_that_document():
    from datetime import date as _date

    from contracts import ExtractedDocument, Requirement, RequiredDoc
    from tools.packager import _resolve_values

    income = ExtractedDocument(
        doc_type="income_certificate", source_path="i.jpg", fields={},
        issue_date=_date(2026, 5, 29), extraction_confidence=1.0,
    )
    marks = ExtractedDocument(
        doc_type="marksheet", source_path="m.jpg", fields={},
        issue_date=_date(2024, 6, 1), extraction_confidence=1.0,
    )
    req = Requirement(
        scheme_id="s", scheme_name="S",
        required_documents=[RequiredDoc(doc_type="income_certificate"), RequiredDoc(doc_type="marksheet")],
        required_fields=["Income Certificate Date of Issue", "Marksheet Date of Issue"],
        source="text", confidence=1.0,
    )

    values = {label: value for label, value, _src in _resolve_values(req, [marks, income])}
    assert values["Income Certificate Date of Issue"] == "29/05/2026"
    assert values["Marksheet Date of Issue"] == "01/06/2024"


def test_npci_is_only_listed_when_the_form_wants_a_bank_passbook():
    # A form that never asks for a passbook has no DBT leg, so warning
    # about NPCI seeding is noise that teaches people to skim the list.
    from contracts import Requirement, RequiredDoc
    from tools.packager import relevant_rejection_causes

    no_bank = Requirement(
        scheme_id="s", scheme_name="S",
        required_documents=[RequiredDoc(doc_type="income_certificate")],
        required_fields=[], source="text", confidence=1.0,
    )
    with_bank = no_bank.model_copy(
        update={"required_documents": [RequiredDoc(doc_type="bank_passbook")]}
    )

    assert not any("NPCI" in c for c in relevant_rejection_causes(no_bank))
    assert any("NPCI" in c for c in relevant_rejection_causes(with_bank))
    # something always applies, so the section is never empty
    assert relevant_rejection_causes(no_bank)


def test_deadline_and_eligibility_causes_track_the_form():
    from datetime import date as _date

    from contracts import Requirement
    from tools.packager import relevant_rejection_causes

    bare = Requirement(
        scheme_id="s", scheme_name="S", required_documents=[], required_fields=[],
        source="text", confidence=1.0,
    )
    assert not any("deadline" in c.lower() for c in relevant_rejection_causes(bare))

    dated = bare.model_copy(update={"deadline": _date(2026, 12, 20)})
    assert any("deadline" in c.lower() for c in relevant_rejection_causes(dated))

    eligible = bare.model_copy(update={"max_family_income_inr": 100000})
    assert any("eligibility rules" in c for c in relevant_rejection_causes(eligible))
