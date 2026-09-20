"""Verifier for marksheet documents. Marksheets don't expire, so
valid_until is never part of the expected field set."""

from __future__ import annotations

from pathlib import Path

from agents.verifiers.common import run_verifier
from contracts import ExtractedDocument

EXPECTED_FIELDS = {"name", "father_name", "dob", "roll_no", "marks_percent", "institution", "passing_year", "issue_date"}

# Only some documents of this type print these — extracted when
# present, but never counted against the extraction confidence.
OPTIONAL_FIELDS = frozenset({"institution", "passing_year"})

_PROMPT_TEMPLATE = """You are extracting fields from OCR text of an Indian school/board marksheet.

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
roll_no, marks_percent (as written, with the % sign if present),
institution (the school, college or board named on it), passing_year
(the year the examination was passed, e.g. "2024" — often printed as the
exam session or year of passing), and issue_date (as written). Marksheets don't have a validity/expiry date —
leave valid_until null regardless of what else is in the text.

OCR TEXT:
{ocr_text}
"""


def verify(
    ocr_text: str, source_path: Path, *, student_id: str, llm_mode: str | None = None
) -> tuple[ExtractedDocument, dict]:
    prompt = _PROMPT_TEMPLATE.format(ocr_text=ocr_text)
    return run_verifier(
        "marksheet",
        prompt,
        EXPECTED_FIELDS,
        source_path,
        cache_inputs={"doc_type": "marksheet", "student": student_id},
        llm_mode=llm_mode,
        optional_fields=OPTIONAL_FIELDS,
    )
