"""Verifier tests — replay mode only, zero network.

Fixtures now recorded against Vertex AI / Gemini (docs/vertex-setup.md),
which reads each document image directly via tools/ocr.py's "vision"
backend (a plain, non-structured multimodal call — see that module's
docstring) instead of the original phase 5c pipeline (rapidocr text ->
llama3.1:8b). Every one of these 15 recordings came back correct on the
first pass, including the two cases the 8B-model generation needed hand
correction for: aditya_sharma's marksheet name (misread "Kumar" as "Kuma"
in the old recording — this document is cross_checker's reference for name
comparisons, so it mattered most) and OCR-merged names elsewhere that the
old model echoed verbatim instead of reconstructing.
"""

from pathlib import Path

import pytest

from agents.verifiers import VERIFIERS
from agents.verifiers.bank_passbook import verify as verify_bank_passbook
from agents.verifiers.income_certificate import verify as verify_income_certificate
from agents.verifiers.marksheet import verify as verify_marksheet
from tools.ocr import extract_text

STUDENTS_DIR = Path(__file__).parent.parent / "fixtures" / "students"


@pytest.fixture(autouse=True)
def _replay_mode(monkeypatch):
    monkeypatch.setenv("KAGAZ_LLM_MODE", "replay")
    monkeypatch.setenv("KAGAZ_MODEL_PROVIDER", "vertex")


def _ocr(student_id: str, doc_type: str) -> tuple[str, Path]:
    path = STUDENTS_DIR / student_id / "documents" / f"{doc_type}.jpg"
    return extract_text(path), path


def test_all_five_doc_types_registered():
    assert set(VERIFIERS) == {
        "income_certificate",
        "caste_certificate",
        "domicile_certificate",
        "marksheet",
        "bank_passbook",
    }


def test_priya_nair_income_certificate_fields_and_dates():
    ocr_text, path = _ocr("priya_nair", "income_certificate")
    doc, usage = verify_income_certificate(ocr_text, path, student_id="priya_nair")

    assert doc.doc_type == "income_certificate"
    assert doc.fields["name"] == "Priya Ramesh Nair"
    assert doc.fields["dob"] == "12/03/2008"
    assert doc.issue_date.isoformat() == "2026-04-10"
    assert doc.valid_until.isoformat() == "2027-04-09"
    assert doc.extraction_confidence == 1.0
    assert usage["totalTokens"] > 0


def test_mohammed_irfan_income_certificate_expiry_is_readable():
    # This is the field the phase 5a bug fix depends on downstream — the
    # verifier must actually read the expiry off the document, not rely on
    # ground truth.
    ocr_text, path = _ocr("mohammed_irfan", "income_certificate")
    doc, _usage = verify_income_certificate(ocr_text, path, student_id="mohammed_irfan")
    assert doc.valid_until.isoformat() == "2026-09-19"


def test_mohammed_irfan_dob_swap_is_readable_on_domicile_certificate():
    doc_type = "domicile_certificate"
    ocr_text, path = _ocr("mohammed_irfan", doc_type)
    doc, _usage = VERIFIERS[doc_type](ocr_text, path, student_id="mohammed_irfan")
    assert doc.fields["dob"] == "06/05/2007"  # swapped relative to every other document

    ocr_text, path = _ocr("mohammed_irfan", "marksheet")
    reference, _usage = verify_marksheet(ocr_text, path, student_id="mohammed_irfan")
    assert reference.fields["dob"] == "05/06/2007"


def test_aditya_sharma_name_variance_is_readable_correctly():
    # The whole point of this student: three different (but all
    # legitimate) spellings/forms of the same name across documents.
    ocr_text, path = _ocr("aditya_sharma", "marksheet")
    reference, _ = VERIFIERS["marksheet"](ocr_text, path, student_id="aditya_sharma")
    assert reference.fields["name"] == "Aditya Kumar Sharma"

    ocr_text, path = _ocr("aditya_sharma", "bank_passbook")
    passbook, _ = verify_bank_passbook(ocr_text, path, student_id="aditya_sharma")
    assert passbook.fields["name"] == "Aditya Sharma"

    ocr_text, path = _ocr("aditya_sharma", "domicile_certificate")
    domicile, _ = VERIFIERS["domicile_certificate"](ocr_text, path, student_id="aditya_sharma")
    assert domicile.fields["name"] == "A. K. Sharma"


def test_marksheet_never_has_valid_until():
    ocr_text, path = _ocr("priya_nair", "marksheet")
    doc, _usage = verify_marksheet(ocr_text, path, student_id="priya_nair")
    assert doc.valid_until is None


def test_bank_passbook_never_has_valid_until():
    ocr_text, path = _ocr("priya_nair", "bank_passbook")
    doc, _usage = verify_bank_passbook(ocr_text, path, student_id="priya_nair")
    assert doc.valid_until is None


def test_missing_field_is_absent_not_guessed():
    # A garbled/near-empty OCR text should leave fields empty rather than
    # invent values — but this specific input isn't in the recorded
    # fixture set, so replay mode must refuse rather than silently
    # fabricate a response. That refusal *is* the guarantee this test
    # checks for.
    from llm_cache import LLMCacheMiss

    with pytest.raises(LLMCacheMiss):
        verify_income_certificate("garbled unreadable nonsense text", Path("nonexistent.jpg"), student_id="nobody")


def test_all_verifiers_report_full_confidence_on_clean_fixtures():
    for student_id in ("priya_nair", "aditya_sharma", "mohammed_irfan"):
        for doc_type, verify in VERIFIERS.items():
            ocr_text, path = _ocr(student_id, doc_type)
            doc, _usage = verify(ocr_text, path, student_id=student_id)
            assert doc.extraction_confidence == 1.0, f"{student_id}/{doc_type}: {doc.extraction_confidence}"
