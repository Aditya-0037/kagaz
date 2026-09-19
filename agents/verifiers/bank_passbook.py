"""Verifier for bank_passbook documents. Passbooks don't expire, so
valid_until is never part of the expected field set."""

from __future__ import annotations

from pathlib import Path

from agents.verifiers.common import run_verifier
from contracts import ExtractedDocument

EXPECTED_FIELDS = {"name", "father_name", "dob", "account_no", "bank_name", "issue_date"}

_PROMPT_TEMPLATE = """You are extracting fields from OCR text of an Indian bank passbook's KYC page.

The OCR text may have lost spaces between adjacent words on some lines
(e.g. "PriyaRameshNair" instead of "Priya Ramesh Nair") — use the field
label immediately before a value and your knowledge of Indian names to
reconstruct the correct spacing. If a field is genuinely missing, garbled
beyond recognition, or absent from the text, leave it null. Never guess a
value that isn't actually supported by the text.

Extract: name, father_name (the "Father's Name" field), dob (as written),
account_no (as written, including any masking like X's), bank_name, and
issue_date (as written). Bank passbooks don't have a validity/expiry date —
leave valid_until null regardless of what else is in the text.

OCR TEXT:
{ocr_text}
"""


def verify(ocr_text: str, source_path: Path, *, student_id: str) -> tuple[ExtractedDocument, dict]:
    prompt = _PROMPT_TEMPLATE.format(ocr_text=ocr_text)
    return run_verifier(
        "bank_passbook",
        prompt,
        EXPECTED_FIELDS,
        source_path,
        cache_inputs={"doc_type": "bank_passbook", "student": student_id},
    )
