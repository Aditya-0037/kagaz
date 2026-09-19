"""One Strands agent per document type (spec section 6.2), sharing the
runner in common.py. Each module's own prompt only asks about that
document type's own fields — see common.py's docstring for why the LLM-
facing output schema is nonetheless shared.

VERIFIERS maps doc_type -> that module's verify(ocr_text, source_path, *,
student_id) -> (ExtractedDocument, token_usage) function, for the
coordinator's dispatch. photo and signature are not here — they're
non-agent, non-LLM handlers in tools/image_checks.py.
"""

from __future__ import annotations

from agents.verifiers import (
    bank_passbook,
    caste_certificate,
    domicile_certificate,
    income_certificate,
    marksheet,
)

VERIFIERS = {
    "income_certificate": income_certificate.verify,
    "caste_certificate": caste_certificate.verify,
    "domicile_certificate": domicile_certificate.verify,
    "marksheet": marksheet.verify,
    "bank_passbook": bank_passbook.verify,
}
