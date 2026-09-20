"""Indian rupee parsing (tools/money.py) and the income-eligibility check."""

import pytest

from agents.cross_checker import income_findings
from contracts import ExtractedDocument
from tools.money import format_inr, parse_inr


@pytest.mark.parametrize(
    "text,expected",
    [
        ("Rs. 2,50,000 per annum", 250_000),
        ("₹250000/-", 250_000),
        ("2.5 lakh", 250_000),
        ("2.5 lakhs", 250_000),
        ("1 crore", 10_000_000),
        ("INR 185000", 185_000),
        ("₹1.85 Lakh", 185_000),
        ("8,00,000", 800_000),
        # Devanagari: a Hindi income certificate says "2.5 लाख", and matching
        # only the Latin spelling read that as ₹2 — three orders of magnitude
        # low, which would silently pass an income check that should block.
        ("2.5 लाख", 250_000),
        ("रु. 1,85,000", 185_000),
        ("1 करोड़", 10_000_000),
        ("50 हजार", 50_000),
        ("50 हज़ार", 50_000),
        ("no figure here", None),
        ("", None),
        (None, None),
    ],
)
def test_parse_inr(text, expected):
    assert parse_inr(text) == expected


def test_format_inr_uses_indian_digit_grouping():
    assert format_inr(250_000) == "₹2,50,000"
    assert format_inr(10_000_000) == "₹1,00,00,000"
    assert format_inr(999) == "₹999"


def _income_doc(value: str | None):
    fields = {"annual_income": value} if value is not None else {}
    return ExtractedDocument(
        doc_type="income_certificate",
        source_path="income_certificate.jpg",
        fields=fields,
        extraction_confidence=1.0,
    )


def test_no_finding_when_scheme_states_no_income_limit():
    assert income_findings([_income_doc("Rs. 5,00,000")], None) == []


def test_no_finding_when_income_is_within_the_limit():
    assert income_findings([_income_doc("Rs. 1,85,000")], 250_000) == []


def test_income_over_the_limit_is_a_blocker_needing_a_human():
    findings = income_findings([_income_doc("Rs. 4,00,000")], 250_000)
    assert len(findings) == 1
    assert findings[0].severity == "blocker"
    assert findings[0].category == "eligibility"
    assert findings[0].needs_human is True
    assert "4,00,000" in findings[0].message
    assert "2,50,000" in findings[0].message


def test_lakh_wording_on_either_side_still_compares():
    assert income_findings([_income_doc("₹3 lakh")], 250_000)[0].severity == "blocker"
    assert income_findings([_income_doc("₹2 lakh")], 250_000) == []


def test_unreadable_income_is_flagged_not_silently_passed():
    findings = income_findings([_income_doc("not stated")], 250_000)
    assert len(findings) == 1
    assert findings[0].severity == "worth_knowing"
    assert findings[0].needs_human is False


def test_missing_income_document_is_flagged_not_silently_passed():
    findings = income_findings([_income_doc(None)], 250_000)
    assert len(findings) == 1
    assert findings[0].severity == "worth_knowing"
    assert "could not read" in findings[0].message
