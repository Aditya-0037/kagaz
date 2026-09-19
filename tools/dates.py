"""Pure-Python date logic for the cross-checker (spec section 6.3).

No LLM calls. Two independent checks:

  - compare_dob: catches DOB values that differ across a student's
    documents — including the classic day/month transposition
    ("05/06/2007" vs "06/05/2007") that looks like it might just be a
    format quirk but is actually a silent-rejection risk.
  - check_validity: compares a document's valid_until against the scheme
    deadline (must_be_valid_on), producing the three severity tiers from
    spec section 6.3.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, timedelta
from typing import Literal

Verdict = Literal["blocker", "likely_fine", "worth_knowing"]

_DATE_FORMATS = ("%d/%m/%Y", "%d-%m-%Y", "%Y-%m-%d")

WORTH_KNOWING_WINDOW_DAYS = 60


@dataclass(frozen=True)
class DateFinding:
    verdict: Verdict
    reason: str


def parse_date_flexible(raw: str) -> date | None:
    """Parse a date string trying DD/MM/YYYY, DD-MM-YYYY, then ISO. Indian
    documents default to DD/MM/YYYY; ISO is accepted since fixtures/tools
    use it internally and it's unambiguous regardless."""
    for fmt in _DATE_FORMATS:
        try:
            return datetime.strptime(raw, fmt).date()
        except ValueError:
            continue
    return None


def _is_day_month_swap(a_raw: str, b_raw: str) -> bool:
    """Best-effort check, for a clearer message only: do the first two
    numeric fields look transposed between the two raw strings?"""
    for sep in ("/", "-"):
        parts_a = a_raw.split(sep)
        parts_b = b_raw.split(sep)
        if len(parts_a) == 3 and len(parts_b) == 3:
            return parts_a[0] == parts_b[1] and parts_a[1] == parts_b[0] and parts_a[0] != parts_a[1]
    return False


def compare_dob(a_raw: str, b_raw: str) -> DateFinding | None:
    """Compare two raw DOB strings from different documents. Returns a
    blocker DateFinding if they resolve to different calendar dates, else
    None (no finding)."""
    if a_raw.strip() == b_raw.strip():
        return None

    date_a = parse_date_flexible(a_raw)
    date_b = parse_date_flexible(b_raw)

    if date_a is None or date_b is None:
        return DateFinding(
            "blocker",
            f"DOB could not be parsed on at least one document: {a_raw!r} vs {b_raw!r}.",
        )

    if date_a == date_b:
        return None

    message = f"DOB differs across documents: {a_raw!r} vs {b_raw!r}."
    if _is_day_month_swap(a_raw, b_raw):
        message += " Day and month appear transposed between the two — a very common silent-rejection cause."
    return DateFinding("blocker", message)


def check_validity(
    valid_until: date | None,
    must_be_valid_on: date | None,
    today: date | None = None,
) -> DateFinding | None:
    """Compare a document's validity window against the scheme deadline.

    - Already expired -> blocker
    - Still valid today but expires before the deadline -> blocker
    - Expires within WORTH_KNOWING_WINDOW_DAYS after the deadline -> worth_knowing
    - Comfortably valid beyond that -> no finding (None)

    A document with no validity requirement (must_be_valid_on is None) or
    no expiry at all (valid_until is None, e.g. a marksheet) produces no
    finding — there is nothing to compare.
    """
    if valid_until is None or must_be_valid_on is None:
        return None

    today = today or date.today()

    if valid_until < today:
        days_ago = (today - valid_until).days
        return DateFinding(
            "blocker",
            f"Already expired: valid_until {valid_until.isoformat()} was {days_ago} day(s) ago.",
        )

    if valid_until < must_be_valid_on:
        days_short = (must_be_valid_on - valid_until).days
        return DateFinding(
            "blocker",
            f"Expires {days_short} day(s) before the scheme deadline "
            f"({valid_until.isoformat()} vs deadline {must_be_valid_on.isoformat()}).",
        )

    if valid_until <= must_be_valid_on + timedelta(days=WORTH_KNOWING_WINDOW_DAYS):
        days_after = (valid_until - must_be_valid_on).days
        return DateFinding(
            "worth_knowing",
            f"Expires {days_after} day(s) after the scheme deadline — comfortably valid "
            "for this submission, but renew soon if it's needed again.",
        )

    return None
