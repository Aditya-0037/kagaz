"""Verifier for caste_certificate documents."""

from __future__ import annotations

from pathlib import Path

from agents.verifiers.common import run_verifier
from contracts import ExtractedDocument

EXPECTED_FIELDS = {"name", "father_name", "dob", "certificate_no", "caste_category", "address", "issue_date", "valid_until"}

# Only some documents of this type print these — extracted when
# present, but never counted against the extraction confidence.
OPTIONAL_FIELDS = frozenset({"address"})

_PROMPT_TEMPLATE = """You are extracting fields from OCR text of an Indian caste certificate.

The OCR text may have lost spaces between adjacent words on some lines
(e.g. "PriyaRameshNair" instead of "Priya Ramesh Nair") — use the field
label immediately before a value and your knowledge of Indian names to
reconstruct the correct spacing.

The document may be in Hindi or another Indic language while the form it
is being submitted to is in English. Return every NAME and PLACE in Latin
script, transliterated (प्रिया रमेश नायर -> "Priya Ramesh Nair"), using the
standard spelling the person would themselves write in English. Keep
numbers, dates and amounts exactly as printed. If a field is genuinely missing, garbled
beyond recognition, or absent from the text, leave it null. Never guess a
value that isn't actually supported by the text.

Extract: name, father_name (the "Father's Name" field), dob (as written),
certificate_no, caste_category (e.g. "OBC", "General", "SC", "ST"),
address (the residential address, if printed), issue_date (as written),
and valid_until (the "Valid Until" field, as written).

OCR TEXT:
{ocr_text}
"""


def verify(
    ocr_text: str, source_path: Path, *, student_id: str, llm_mode: str | None = None
) -> tuple[ExtractedDocument, dict]:
    prompt = _PROMPT_TEMPLATE.format(ocr_text=ocr_text)
    return run_verifier(
        "caste_certificate",
        prompt,
        EXPECTED_FIELDS,
        source_path,
        cache_inputs={"doc_type": "caste_certificate", "student": student_id},
        llm_mode=llm_mode,
        optional_fields=OPTIONAL_FIELDS,
    )
