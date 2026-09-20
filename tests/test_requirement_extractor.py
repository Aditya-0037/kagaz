"""Requirement extractor tests — replay mode only, zero network.

Every assertion here is checked against fixtures/llm_cache/*.json. Two
recording generations: the original local-Ollama recordings (phase 4,
hand-corrected where the 8B model missed "Photograph"/"Specimen Signature"
despite the annexure-table format-specs call finding both), superseded by
recordings against Vertex AI / Gemini (see docs/sdk-notes.md's 2026-09-19
entry and docs/vertex-setup.md) — Gemini got every one of these right on
the first pass, no hand-correction needed. The fixtures are the test
contract from here on, not the model's live opinion, regardless of which
provider recorded them.
"""

from pathlib import Path

import pytest

from agents.requirement_extractor import (
    _extract_pdf_text,
    build_manual_requirement,
    extract_requirement_from_pdf,
    extract_requirement_from_text,
)
from contracts import RequiredDoc

SCHEMES_DIR = Path(__file__).parent.parent / "fixtures" / "schemes"


@pytest.fixture(autouse=True)
def _replay_mode(monkeypatch):
    monkeypatch.setenv("KAGAZ_LLM_MODE", "replay")
    monkeypatch.setenv("KAGAZ_MODEL_PROVIDER", "vertex")


# --- Scheme A: full document set, table-based annexure on page 3 ------------


def test_scheme_a_yields_all_seven_documents():
    req = extract_requirement_from_pdf(
        SCHEMES_DIR / "scheme_a_postmatric.pdf", "scheme_a_postmatric", "Post-Matric Scholarship 2026-27"
    )
    doc_types = {rd.doc_type for rd in req.required_documents}
    assert doc_types == {
        "income_certificate",
        "caste_certificate",
        "domicile_certificate",
        "marksheet",
        "bank_passbook",
        "photo",
        "signature",
    }


def test_scheme_a_deadline():
    req = extract_requirement_from_pdf(
        SCHEMES_DIR / "scheme_a_postmatric.pdf", "scheme_a_postmatric", "Post-Matric Scholarship 2026-27"
    )
    assert req.deadline.isoformat() == "2026-09-30"


def test_scheme_a_photo_spec_pulled_from_page_3_annexure():
    req = extract_requirement_from_pdf(
        SCHEMES_DIR / "scheme_a_postmatric.pdf", "scheme_a_postmatric", "Post-Matric Scholarship 2026-27"
    )
    photo = next(rd for rd in req.required_documents if rd.doc_type == "photo")
    assert photo.max_size_kb == 50
    assert photo.dimensions_px == (276, 354)
    assert set(photo.file_formats) == {"jpg", "jpeg"}


def test_scheme_a_fully_resolved_high_confidence():
    req = extract_requirement_from_pdf(
        SCHEMES_DIR / "scheme_a_postmatric.pdf", "scheme_a_postmatric", "Post-Matric Scholarship 2026-27"
    )
    assert req.unresolved == []
    assert req.confidence == 1.0


def test_scheme_a_source_is_pdf():
    req = extract_requirement_from_pdf(
        SCHEMES_DIR / "scheme_a_postmatric.pdf", "scheme_a_postmatric", "Post-Matric Scholarship 2026-27"
    )
    assert req.source == "pdf"


# --- Scheme B: smaller, different set, one deliberately vague clause --------


def test_scheme_b_yields_exactly_three_documents():
    req = extract_requirement_from_pdf(SCHEMES_DIR / "scheme_b_merit.pdf", "scheme_b_merit", "State Merit Scholarship 2026")
    doc_types = {rd.doc_type for rd in req.required_documents}
    assert doc_types == {"marksheet", "bank_passbook", "photo"}


def test_scheme_b_deadline_differs_from_scheme_a():
    req = extract_requirement_from_pdf(SCHEMES_DIR / "scheme_b_merit.pdf", "scheme_b_merit", "State Merit Scholarship 2026")
    assert req.deadline.isoformat() == "2026-10-15"


def test_scheme_b_has_fields_scheme_a_does_not():
    req_a = extract_requirement_from_pdf(
        SCHEMES_DIR / "scheme_a_postmatric.pdf", "scheme_a_postmatric", "Post-Matric Scholarship 2026-27"
    )
    req_b = extract_requirement_from_pdf(SCHEMES_DIR / "scheme_b_merit.pdf", "scheme_b_merit", "State Merit Scholarship 2026")
    new_fields = set(req_b.required_fields) - set(req_a.required_fields)
    assert "Merit Rank / Percentile in Qualifying Examination" in new_fields
    assert "Mobile Number Linked to Aadhaar" in new_fields


def test_scheme_b_vague_clause_is_unresolved_not_fabricated():
    req = extract_requirement_from_pdf(SCHEMES_DIR / "scheme_b_merit.pdf", "scheme_b_merit", "State Merit Scholarship 2026")

    bank_passbook = next(rd for rd in req.required_documents if rd.doc_type == "bank_passbook")
    assert bank_passbook.file_formats == []
    assert bank_passbook.max_size_kb is None
    assert bank_passbook.dimensions_px is None

    assert any("bank_passbook" in item for item in req.unresolved)
    assert req.confidence < 1.0


def test_scheme_b_photo_and_marksheet_specs_are_concrete_not_vague():
    req = extract_requirement_from_pdf(SCHEMES_DIR / "scheme_b_merit.pdf", "scheme_b_merit", "State Merit Scholarship 2026")
    photo = next(rd for rd in req.required_documents if rd.doc_type == "photo")
    marksheet = next(rd for rd in req.required_documents if rd.doc_type == "marksheet")
    assert photo.max_size_kb == 30
    assert photo.dimensions_px == (200, 230)
    assert marksheet.max_size_kb == 100


# --- source tagging per input tier -------------------------------------------


def test_pasted_text_source_is_text_not_pdf():
    # Same underlying text as the PDF path -> identical prompts -> same
    # cached responses, reused here to test the "pasted text" tier without
    # a second recording.
    text = _extract_pdf_text(SCHEMES_DIR / "scheme_b_merit.pdf")
    req = extract_requirement_from_text(text, "scheme_b_merit", "State Merit Scholarship 2026")
    assert req.source == "text"
    assert {rd.doc_type for rd in req.required_documents} == {"marksheet", "bank_passbook", "photo"}


def test_manual_requirement_source_is_manual_and_never_touches_the_llm(monkeypatch):
    # Deleting the env vars proves this path can't be quietly falling back
    # to a cached/live model call - build_manual_requirement takes no text
    # input at all.
    monkeypatch.delenv("KAGAZ_LLM_MODE", raising=False)
    monkeypatch.delenv("KAGAZ_MODEL_PROVIDER", raising=False)

    req = build_manual_requirement(
        "manual_scheme",
        "Manually Entered Scheme",
        required_documents=[RequiredDoc(doc_type="marksheet")],
        required_fields=["Full Name"],
    )
    assert req.source == "manual"
    assert req.confidence == 1.0
    assert req.unresolved == []


# --- garbage input ---------------------------------------------------------


def test_garbage_pdf_yields_low_confidence_and_unresolved_not_exception():
    req = extract_requirement_from_pdf(SCHEMES_DIR / "garbage_scan.pdf", "garbage_test", "Garbage Test")
    assert req.required_documents == []
    assert req.required_fields == []
    assert req.confidence == 0.0
    assert req.unresolved != []


def test_empty_pasted_text_yields_low_confidence_and_unresolved_not_exception():
    req = extract_requirement_from_text("", "empty_test", "Empty Test")
    assert req.confidence == 0.0
    assert req.unresolved != []
    assert req.source == "text"


def test_a_document_only_in_the_format_table_is_not_lost():
    # Regression: the merge looped over the checklist call's output only,
    # so a document the checklist call missed but the format-specs call
    # found — "Photograph" and "Specimen Signature", both named in prose
    # rather than in the list — vanished from the requirement entirely.
    from agents.requirement_extractor import (
        _ChecklistOutput,
        _DeadlineOutput,
        _FieldsOutput,
        _FormatSpecEntry,
        _FormatSpecsOutput,
        _merge,
    )

    req = _merge(
        "s",
        "S",
        "text",
        _ChecklistOutput(documents=["Income Certificate"]),  # checklist missed the photo
        _FieldsOutput(fields=["Full Name"]),
        _FormatSpecsOutput(
            specs=[
                _FormatSpecEntry(doc_type_label="Photograph", file_formats=["jpg"],
                                 max_size_kb=50, width_px=276, height_px=354),
            ]
        ),
        _DeadlineOutput(deadline_iso=None),
    )

    types = {rd.doc_type for rd in req.required_documents}
    assert types == {"income_certificate", "photo"}

    photo = next(rd for rd in req.required_documents if rd.doc_type == "photo")
    assert photo.max_size_kb == 50
    assert photo.dimensions_px == (276, 354)
    # and it says why it was added, rather than appearing silently
    assert any("format/size table" in u for u in req.unresolved)


def test_a_vague_spec_alone_does_not_invent_a_required_document():
    # Only a spec with real numbers implies the document is required; a
    # vague mention must not add a document the checklist never saw.
    from agents.requirement_extractor import (
        _ChecklistOutput,
        _DeadlineOutput,
        _FieldsOutput,
        _FormatSpecEntry,
        _FormatSpecsOutput,
        _merge,
    )

    req = _merge(
        "s",
        "S",
        "text",
        _ChecklistOutput(documents=["Income Certificate"]),
        _FieldsOutput(fields=[]),
        _FormatSpecsOutput(
            specs=[_FormatSpecEntry(doc_type_label="Some Annexure", unresolved_note="in the prescribed format")]
        ),
        _DeadlineOutput(deadline_iso=None),
    )
    assert {rd.doc_type for rd in req.required_documents} == {"income_certificate"}
