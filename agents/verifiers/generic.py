"""Verifier for document types Kagaz has no dedicated agent for.

The five named verifiers cover the documents most schemes ask for, but a
real applicant's folder has more than that: a 10th and a 12th marksheet
that are different documents, an Aadhaar card, a PAN card, a transfer or
migration certificate, a disability certificate. Refusing to read those
would make the most valuable check — is this person's name and date of
birth written the same way on every document — miss exactly the documents
most likely to disagree.

So an unrecognised type still gets read, for identity fields only. It
asks for whatever a document of that kind plausibly carries and takes
null for the rest, rather than inventing a doc-type-specific schema for
something it has never seen.
"""

from __future__ import annotations

from pathlib import Path

from agents.verifiers.common import run_verifier
from contracts import ExtractedDocument

# Deliberately the identity/date fields only. Document-specific numbers
# (marks, income, account) belong to the verifiers that know to expect
# them; here a null would wrongly drag the confidence score down.
EXPECTED_FIELDS = {"name", "father_name", "dob", "issue_date", "valid_until"}

_PROMPT_TEMPLATE = """You are extracting identity fields from OCR text of an Indian
official document. The document is described as: "{doc_label}".

The OCR text may have lost spaces between adjacent words on some lines
(e.g. "PriyaRameshNair" instead of "Priya Ramesh Nair") — use the field
label immediately before a value and your knowledge of Indian names to
reconstruct the correct spacing.

Extract only these, exactly as written on the document:
- name: the person the document is about
- father_name: the "Father's Name" / "Guardian's Name" field, if present
- dob: date of birth, if present
- issue_date: the date the document was issued, if present
- valid_until: an expiry / "valid up to" date, if the document carries one

If a field is missing, garbled beyond recognition, or simply not the kind
of thing this document carries, leave it null. Never guess a value that is
not actually supported by the text, and never copy a number from one field
into another.

OCR TEXT:
{ocr_text}
"""


def verify(
    ocr_text: str,
    source_path: Path,
    *,
    student_id: str,
    llm_mode: str | None = None,
    doc_type: str = "document",
    doc_label: str | None = None,
) -> tuple[ExtractedDocument, dict]:
    prompt = _PROMPT_TEMPLATE.format(
        ocr_text=ocr_text, doc_label=doc_label or doc_type.replace("_", " ")
    )
    return run_verifier(
        doc_type,
        prompt,
        EXPECTED_FIELDS,
        source_path,
        cache_inputs={"doc_type": doc_type, "student": student_id},
        llm_mode=llm_mode,
    )
