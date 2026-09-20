"""Configuration coverage for document-verification parallelism."""

from agents.coordinator import DEFAULT_MAX_PARALLEL_VERIFICATIONS, _verification_workers


def test_verification_parallelism_defaults_to_a_bounded_value(monkeypatch):
    monkeypatch.delenv("KAGAZ_MAX_PARALLEL_VERIFICATIONS", raising=False)
    assert _verification_workers(9) == DEFAULT_MAX_PARALLEL_VERIFICATIONS
    assert _verification_workers(2) == 2


def test_zero_parallelism_setting_removes_the_application_side_cap(monkeypatch):
    monkeypatch.setenv("KAGAZ_MAX_PARALLEL_VERIFICATIONS", "0")
    assert _verification_workers(9) == 9


def test_invalid_parallelism_setting_falls_back_safely(monkeypatch):
    monkeypatch.setenv("KAGAZ_MAX_PARALLEL_VERIFICATIONS", "unlimited")
    assert _verification_workers(9) == DEFAULT_MAX_PARALLEL_VERIFICATIONS
