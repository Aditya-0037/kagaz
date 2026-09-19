"""Transient-failure handling (tools/retry.py) and how the coordinator
reports it.

Regression: a live Cloud Run run hit 429 RESOURCE_EXHAUSTED from Vertex
(several documents verified in parallel) and told the user "Kagaz could
not read the file provided for income certificate" — sending them off to
re-scan a perfectly good document over a rate limit.
"""

import pytest

from tools.retry import is_transient, with_retries


@pytest.mark.parametrize(
    "message",
    [
        "429 Too Many Requests. {'message': 'Resource exhausted. Please try again later.'}",
        "RESOURCE_EXHAUSTED",
        "503 Service Unavailable",
        "DEADLINE_EXCEEDED",
        "Quota exceeded for requests per minute",
    ],
)
def test_provider_rate_limits_and_outages_are_transient(message):
    assert is_transient(RuntimeError(message))


@pytest.mark.parametrize(
    "message",
    [
        "cannot identify image file '/tmp/x.txt'",
        "PDF file is encrypted",
        "invalid JSON in structured output",
    ],
)
def test_bad_input_is_not_transient(message):
    assert not is_transient(RuntimeError(message))


def test_with_retries_recovers_from_a_transient_failure(monkeypatch):
    monkeypatch.setattr("tools.retry.time.sleep", lambda _s: None)
    calls = {"n": 0}

    def flaky():
        calls["n"] += 1
        if calls["n"] < 3:
            raise RuntimeError("429 Too Many Requests")
        return "ok"

    assert with_retries(flaky) == "ok"
    assert calls["n"] == 3


def test_with_retries_does_not_retry_a_bad_document(monkeypatch):
    monkeypatch.setattr("tools.retry.time.sleep", lambda _s: None)
    calls = {"n": 0}

    def broken():
        calls["n"] += 1
        raise RuntimeError("cannot identify image file")

    with pytest.raises(RuntimeError):
        with_retries(broken)
    assert calls["n"] == 1  # failed once, not four times


def test_rate_limit_is_reported_as_service_busy_not_a_bad_document(tmp_path, monkeypatch):
    import agents.coordinator as coordinator
    from contracts import Requirement, RequiredDoc

    monkeypatch.setattr("tools.retry.time.sleep", lambda _s: None)

    def rate_limited(*_args, **_kwargs):
        raise RuntimeError("429 Too Many Requests. RESOURCE_EXHAUSTED")

    monkeypatch.setattr(coordinator, "extract_text", rate_limited)

    doc = tmp_path / "income_certificate.jpg"
    doc.write_bytes(b"x")
    requirement = Requirement(
        scheme_id="s",
        scheme_name="S",
        required_documents=[RequiredDoc(doc_type="income_certificate")],
        required_fields=[],
        source="text",
        confidence=1.0,
    )

    result = coordinator.run_audit_for_documents("u", "r", requirement, {"income_certificate": doc})

    assert len(result.findings) == 1
    finding = result.findings[0]
    assert finding.severity == "worth_knowing"  # not a blocker
    assert finding.needs_human is False  # does not stop the run for a decision
    assert "could not read the file" not in finding.message
    assert "busy" in finding.message
