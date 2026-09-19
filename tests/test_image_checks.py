from pathlib import Path

from PIL import Image

from contracts import RequiredDoc
from tools.image_checks import check_photo, check_signature

FIXTURES = Path(__file__).parent.parent / "fixtures" / "students"
PRIYA_PHOTO = FIXTURES / "priya_nair" / "documents" / "photo.jpg"
ADITYA_SIGNATURE = FIXTURES / "aditya_sharma" / "documents" / "signature.jpg"


def test_check_photo_without_spec_reports_metadata_only():
    doc = check_photo(PRIYA_PHOTO)
    assert doc.doc_type == "photo"
    assert doc.extraction_confidence == 1.0
    assert "dimensions_px" in doc.fields
    assert "format" in doc.fields
    assert "issues" not in doc.fields


def test_check_photo_against_spec_flags_oversized_and_wrong_dimensions():
    # priya_nair's photo is deliberately oversized (~2.2MB, 2200x2900) —
    # the whole point of the formatter (phase 3) is to fix this before
    # upload; the verifier's job is to notice it needs fixing.
    spec = RequiredDoc(doc_type="photo", file_formats=["jpg", "jpeg"], max_size_kb=50, dimensions_px=(276, 354))
    doc = check_photo(PRIYA_PHOTO, spec)
    assert doc.extraction_confidence < 1.0
    assert "issues" in doc.fields
    assert "KB exceeds" in doc.fields["issues"]
    assert "dimensions" in doc.fields["issues"]


def test_check_photo_against_matching_spec_has_no_issues():
    with Image.open(PRIYA_PHOTO) as img:
        dims = img.size
    size_kb = PRIYA_PHOTO.stat().st_size / 1024
    spec = RequiredDoc(doc_type="photo", file_formats=["jpg"], max_size_kb=int(size_kb) + 10, dimensions_px=dims)
    doc = check_photo(PRIYA_PHOTO, spec)
    assert doc.extraction_confidence == 1.0
    assert "issues" not in doc.fields


def test_check_signature_reports_metadata():
    doc = check_signature(ADITYA_SIGNATURE)
    assert doc.doc_type == "signature"
    assert doc.extraction_confidence == 1.0
    assert "dimensions_px" in doc.fields


def test_blank_image_is_flagged(tmp_path):
    blank_path = tmp_path / "blank.jpg"
    Image.new("RGB", (300, 300), (240, 240, 240)).save(blank_path, "JPEG")
    doc = check_photo(blank_path)
    assert doc.extraction_confidence == 0.0
    assert "blank" in doc.fields["issues"].lower()


def test_corrupt_file_is_flagged(tmp_path):
    corrupt_path = tmp_path / "corrupt.jpg"
    corrupt_path.write_bytes(b"not actually a jpeg file, just garbage bytes")
    doc = check_photo(corrupt_path)
    assert doc.extraction_confidence == 0.0
    assert "could not be opened" in doc.fields["issues"]


def test_no_finding_when_document_never_expires():
    # photo/signature never carry issue_date/valid_until at all
    doc = check_photo(PRIYA_PHOTO)
    assert doc.issue_date is None
    assert doc.valid_until is None
