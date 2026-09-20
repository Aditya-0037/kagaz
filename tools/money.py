"""Indian rupee amount parsing. Pure Python, no LLM.

Both sides of the income-eligibility check arrive as prose, not numbers:
a scheme says "family income must not exceed Rs. 2,50,000 per annum" or
"₹2.5 lakh", and an income certificate says "Rs. 1,85,000/-" or
"₹1.85 Lakh". This turns either into an int so agents/cross_checker can
compare them deterministically instead of asking a model "is this more
than that".

Indian digit grouping (2,50,000 = two lakh fifty thousand) is handled by
simply removing separators — the grouping pattern carries no extra
information once the digits are in order.
"""

from __future__ import annotations

import re

_THOUSAND = 1_000
_LAKH = 100_000
_CRORE = 10_000_000

# "2,50,000" / "250000" / "2.5" — digits with optional separators/decimal.
_NUMBER = r"\d[\d,\s]*(?:\.\d+)?"

# Scale words in Latin AND Devanagari. A Hindi income certificate says
# "2.5 लाख", and matching only the Latin spelling read that as ₹2 — three
# orders of magnitude low, which would silently pass an income check that
# should have blocked the application.
_CRORE_WORDS = r"(?:\bcrores?\b|\bcr\b|करोड़ों|करोड़|करोड)"
_LAKH_WORDS = r"(?:\blakhs?\b|\blacs?\b|लाखों|लाख|लक्ष)"
_THOUSAND_WORDS = r"(?:\bthousand\b|\bhazaars?\b|\bhazars?\b|हज़ार|हजार)"

_CRORE_RE = re.compile(rf"({_NUMBER})\s*{_CRORE_WORDS}", re.IGNORECASE | re.UNICODE)
_LAKH_RE = re.compile(rf"({_NUMBER})\s*{_LAKH_WORDS}", re.IGNORECASE | re.UNICODE)
_THOUSAND_RE = re.compile(rf"({_NUMBER})\s*{_THOUSAND_WORDS}", re.IGNORECASE | re.UNICODE)
_PLAIN_RE = re.compile(_NUMBER)


def _to_float(raw: str) -> float | None:
    cleaned = raw.replace(",", "").replace(" ", "").strip()
    try:
        return float(cleaned)
    except ValueError:
        return None


def parse_inr(text: str | None) -> int | None:
    """Return a rupee amount as a whole number, or None if `text` states no
    parseable amount.

    Understands "Rs. 2,50,000", "₹250000/-", "2.5 lakh", "1 crore",
    "INR 185000 per annum", and the Devanagari equivalents ("2.5 लाख",
    "रु. 1,85,000"). Returns None rather than guessing when the text has
    no number at all — a caller must be able to tell "no limit stated"
    apart from "limit is zero".
    """
    if not text:
        return None
    text = str(text).strip()
    if not text:
        return None

    crore = _CRORE_RE.search(text)
    if crore:
        value = _to_float(crore.group(1))
        return int(round(value * _CRORE)) if value is not None else None

    lakh = _LAKH_RE.search(text)
    if lakh:
        value = _to_float(lakh.group(1))
        return int(round(value * _LAKH)) if value is not None else None

    thousand = _THOUSAND_RE.search(text)
    if thousand:
        value = _to_float(thousand.group(1))
        return int(round(value * _THOUSAND)) if value is not None else None

    plain = _PLAIN_RE.search(text)
    if plain:
        value = _to_float(plain.group(0))
        return int(round(value)) if value is not None else None

    return None


def format_inr(amount: int) -> str:
    """Format for display with Indian digit grouping: 250000 -> '2,50,000'."""
    digits = str(abs(int(amount)))
    if len(digits) <= 3:
        grouped = digits
    else:
        head, tail = digits[:-3], digits[-3:]
        parts = []
        while len(head) > 2:
            parts.insert(0, head[-2:])
            head = head[:-2]
        if head:
            parts.insert(0, head)
        grouped = ",".join(parts) + "," + tail
    sign = "-" if int(amount) < 0 else ""
    return f"{sign}₹{grouped}"
