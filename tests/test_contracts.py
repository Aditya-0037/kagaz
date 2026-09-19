from datetime import date
from pathlib import Path

import pytest
from pydantic import ValidationError

from contracts import ExtractedDocument, Finding, RequiredDoc, Requirement


def test_required_doc_minimal():
    doc = RequiredDoc(doc_type="income_certificate")
    assert doc.file_formats == []
    assert doc.max_size_kb is None
    assert doc.dimensions_px is None


def test_required_doc_full():
    doc = RequiredDoc(
        doc_type="photo",
        file_formats=["jpg", "jpeg"],
        max_size_kb=50,
        dimensions_px=(413, 531),
        must_be_valid_on=date(2026, 9, 30),
        notes="passport-style, white background",
    )
    assert doc.dimensions_px == (413, 531)


def test_requirement_round_trip():
    req = Requirement(
        scheme_id="scholarship-2026",
        scheme_name="Post-Matric Scholarship 2026",
        deadline=date(2026, 9, 30),
        required_documents=[RequiredDoc(doc_type="income_certificate")],
        required_fields=["Full Name", "Father's Name"],
        source="pdf",
        confidence=0.92,
        unresolved=["max upload size for signature not stated"],
    )
    dumped = req.model_dump()
    restored = Requirement.model_validate(dumped)
    assert restored == req


def test_requirement_requires_source():
    with pytest.raises(ValidationError):
        Requirement(
            scheme_id="x",
            scheme_name="X",
            source="not-a-real-source",  # type: ignore[arg-type]
            confidence=0.5,
        )


def test_extracted_document_path_is_coerced():
    doc = ExtractedDocument(
        doc_type="marksheet",
        source_path="fixtures/students/aditya/marksheet.pdf",
        fields={"name": "Aditya Kumar Sharma"},
        extraction_confidence=0.88,
    )
    assert isinstance(doc.source_path, Path)


def test_finding_defaults_needs_human_false():
    finding = Finding(
        severity="likely_fine",
        category="name_mismatch",
        message="Name on bank passbook omits middle name; portals usually accept this.",
        evidence=["marksheet: Aditya Kumar Sharma", "passbook: Aditya Sharma"],
    )
    assert finding.needs_human is False


def test_finding_blocker_needs_human_true():
    finding = Finding(
        severity="blocker",
        category="dob_mismatch",
        message="DOB differs across documents: 05/06/2007 vs 06/05/2007.",
        evidence=["marksheet: 05/06/2007", "domicile_certificate: 06/05/2007"],
        needs_human=True,
    )
    assert finding.needs_human is True


def test_finding_rejects_unknown_severity():
    with pytest.raises(ValidationError):
        Finding(
            severity="urgent",  # type: ignore[arg-type]
            category="missing",
            message="x",
        )
