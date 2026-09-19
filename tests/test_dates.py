from datetime import date, timedelta

from tools.dates import check_validity, compare_dob, parse_date_flexible

# --- compare_dob -------------------------------------------------------------


def test_compare_dob_identical_strings_no_finding():
    assert compare_dob("05/06/2007", "05/06/2007") is None


def test_compare_dob_day_month_collision_is_blocker():
    result = compare_dob("05/06/2007", "06/05/2007")
    assert result is not None
    assert result.verdict == "blocker"
    assert "05/06/2007" in result.reason and "06/05/2007" in result.reason


def test_compare_dob_different_years_is_blocker():
    result = compare_dob("05/06/2007", "05/06/2008")
    assert result is not None
    assert result.verdict == "blocker"


def test_compare_dob_unparseable_is_blocker():
    result = compare_dob("05/06/2007", "not-a-date")
    assert result is not None
    assert result.verdict == "blocker"


def test_compare_dob_iso_and_slash_same_date_no_finding():
    assert compare_dob("2007-06-05", "05/06/2007") is None


def test_parse_date_flexible_ddmmyyyy():
    assert parse_date_flexible("05/06/2007") == date(2007, 6, 5)


def test_parse_date_flexible_iso():
    assert parse_date_flexible("2007-06-05") == date(2007, 6, 5)


def test_parse_date_flexible_invalid_returns_none():
    assert parse_date_flexible("banana") is None


# --- check_validity ------------------------------------------------------------

DEADLINE = date(2026, 9, 30)
TODAY = date(2026, 9, 3)


def test_validity_already_expired_is_blocker():
    result = check_validity(date(2026, 8, 1), DEADLINE, today=TODAY)
    assert result is not None
    assert result.verdict == "blocker"


def test_validity_expires_before_deadline_is_blocker():
    # mirrors mohammed_irfan's income certificate: expires 11 days before the deadline
    result = check_validity(date(2026, 9, 19), DEADLINE, today=TODAY)
    assert result is not None
    assert result.verdict == "blocker"
    assert "11" in result.reason


def test_validity_expires_shortly_after_deadline_is_worth_knowing():
    result = check_validity(date(2026, 10, 15), DEADLINE, today=TODAY)
    assert result is not None
    assert result.verdict == "worth_knowing"


def test_validity_expires_exactly_at_60_day_boundary_is_worth_knowing():
    result = check_validity(DEADLINE + timedelta(days=60), DEADLINE, today=TODAY)
    assert result is not None
    assert result.verdict == "worth_knowing"


def test_validity_comfortably_valid_no_finding():
    result = check_validity(date(2028, 1, 1), DEADLINE, today=TODAY)
    assert result is None


def test_validity_no_expiry_required_no_finding():
    # e.g. a marksheet, which never expires
    assert check_validity(None, DEADLINE, today=TODAY) is None


def test_validity_no_deadline_specified_no_finding():
    assert check_validity(date(2020, 1, 1), None, today=TODAY) is None
