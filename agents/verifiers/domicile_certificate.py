"""Verifier for domicile_certificate documents."""

from __future__ import annotations

from pathlib import Path

from agents.verifiers.common import run_verifier
from contracts import ExtractedDocument

EXPECTED_FIELDS = {"name", "father_name", "dob", "certificate_no", "issue_date", "valid_until"}

_PROMPT_TEMPLATE = """You are extracting fields from OCR text of an Indian domicile (residence) certificate.

The OCR text may have lost spaces between adjacent words on some lines
(e.g. "PriyaRameshNair" instead of "Priya Ramesh Nair") — use the field
label immediately before a value and your knowledge of Indian names to
reconstruct the correct spacing. If a field is genuinely missing, garbled
beyond recognition, or absent from the text, leave it null. Never guess a
value that isn't actually supported by the text.

Extract: name, father_name (the "Father's Name" field), dob (as written),
certificate_no, issue_date (as written), and valid_until (the "Valid
Until" field, as written).

OCR TEXT:
{ocr_text}
"""


def verify(ocr_text: str, source_path: Path, *, student_id: str) -> tuple[ExtractedDocument, dict]:
    prompt = _PROMPT_TEMPLATE.format(ocr_text=ocr_text)
    return run_verifier(
        "domicile_certificate",
        prompt,
        EXPECTED_FIELDS,
        source_path,
        cache_inputs={"doc_type": "domicile_certificate", "student": student_id},
    )
