"""Canonical document-type vocabulary and label normalisation.

Pure Python, no LLM. The requirement extractor asks the model for document
labels worded however the source text words them ("Photograph", "Mark
Sheet", "Bank Passbook (first page)") — this maps those labels onto the
fixed doc_type strings the rest of the system (cross-checker, formatter,
fixtures) already keys on.
"""

from __future__ import annotations

import re

CANONICAL_DOC_TYPES = frozenset(
    {
        "income_certificate",
        "caste_certificate",
        "domicile_certificate",
        "marksheet",
        "bank_passbook",
        "photo",
        "signature",
    }
)

# Certificates expire and are typically required to stay valid through a
# scheme's deadline. Marksheets, passbooks, photos, and signatures don't
# carry an expiry in the same sense — a marksheet doesn't "expire," a
# passbook/photo/signature just needs to exist. Used by
# agents/coordinator.apply_deadline() to decide which documents get
# must_be_valid_on set from the scheme deadline.
EXPIRING_DOC_TYPES = frozenset(
    {
        "income_certificate",
        "caste_certificate",
        "domicile_certificate",
    }
)

# Longest/most specific aliases first isn't required — matching is exact-map
# first, then substring, and substring checks a fixed set below.
_DOC_TYPE_ALIASES: dict[str, str] = {
    "income certificate": "income_certificate",
    "caste certificate": "caste_certificate",
    "domicile certificate": "domicile_certificate",
    "residence certificate": "domicile_certificate",
    "domicile / residence certificate": "domicile_certificate",
    "marksheet": "marksheet",
    "mark sheet": "marksheet",
    "mark-sheet": "marksheet",
    "latest marksheet": "marksheet",
    "most recent marksheet": "marksheet",
    "qualifying examination marksheet": "marksheet",
    "bank passbook": "bank_passbook",
    "bank passbook (first page)": "bank_passbook",
    "bank account passbook": "bank_passbook",
    "passbook": "bank_passbook",
    "photograph": "photo",
    "photo": "photo",
    "recent photograph": "photo",
    "passport size photograph": "photo",
    "passport-size photograph": "photo",
    "signature": "signature",
    "specimen signature": "signature",
}

# Substring fallbacks, checked in order, for labels that don't hit the exact
# map above (e.g. "Income Certificate issued by Tehsildar").
_SUBSTRING_FALLBACKS: list[tuple[str, str]] = [
    ("income", "income_certificate"),
    ("caste", "caste_certificate"),
    ("domicile", "domicile_certificate"),
    ("residence", "domicile_certificate"),
    ("marksheet", "marksheet"),
    ("mark sheet", "marksheet"),
    ("passbook", "bank_passbook"),
    ("photograph", "photo"),
    ("photo", "photo"),
    ("signature", "signature"),
]


def _slugify(label: str) -> str:
    slug = re.sub(r"[^a-z0-9]+", "_", label.strip().casefold()).strip("_")
    return slug or "unknown_document"


def normalize_doc_type(label: str) -> str:
    """Map a free-text document label to a canonical doc_type.

    Falls back to a slugified version of the label itself if nothing
    matches, rather than raising — an unrecognised document should still
    show up (under its own slug) rather than silently disappear."""
    cleaned = label.strip().casefold()

    if cleaned in _DOC_TYPE_ALIASES:
        return _DOC_TYPE_ALIASES[cleaned]

    for needle, canonical in _SUBSTRING_FALLBACKS:
        if needle in cleaned:
            return canonical

    return _slugify(label)
