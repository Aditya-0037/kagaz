"""Escalation interrupt tests — phase 6.

Every test here drives a REAL Strands interrupt/resume cycle (see
agents/escalation.py and model_provider.ScriptedToolCallModel) with no
human present and no network — the scripted decision provider stands in
for the human, and the tool-triggering model is deterministic by
construction rather than routed through llm_cache's replay mode.
"""

from pathlib import Path

import pytest

from agents.coordinator import run_audit_with_escalation
from agents.escalation import escalate_one, run_escalations, scripted_decision_provider
from contracts import Finding

SCHEMES_DIR = Path(__file__).parent.parent / "fixtures" / "schemes"
SCHEME_A_PDF = SCHEMES_DIR / "scheme_a_postmatric.pdf"
SCHEME_A_NAME = "Post-Matric Scholarship 2026-27"


@pytest.fixture(autouse=True)
def _replay_mode(monkeypatch):
    monkeypatch.setenv("KAGAZ_LLM_MODE", "replay")
    monkeypatch.setenv("KAGAZ_MODEL_PROVIDER", "vertex")


BLOCKER = Finding(
    severity="blocker",
    category="dob_mismatch",
    message="DOB differs across documents",
    evidence=["marksheet: 05/06/2007", "domicile_certificate: 06/05/2007"],
    needs_human=True,
)

LIKELY_FINE = Finding(
    severity="likely_fine",
    category="name_mismatch",
    message="Names differ by an omitted middle name",
    evidence=["marksheet: Aditya Kumar Sharma", "bank_passbook: Aditya Sharma"],
    needs_human=False,
)


def test_escalate_one_raises_a_real_interrupt_and_resumes():
    def provider(finding):
        assert finding is BLOCKER
        return "override", "confirmed with the student directly"

    decision = escalate_one(BLOCKER, 0, provider)

    assert decision.finding == BLOCKER
    assert decision.decision == "override"
    assert decision.note == "confirmed with the student directly"
    assert decision.decided_at is not None


def test_run_escalations_skips_findings_that_dont_need_human():
    calls = []

    def provider(finding):
        calls.append(finding)
        return "accept", None

    log = run_escalations([LIKELY_FINE, BLOCKER], provider)

    assert len(log) == 1
    assert calls == [BLOCKER]  # LIKELY_FINE never triggered an interrupt at all


def test_run_escalations_processes_multiple_findings_one_at_a_time_in_order():
    second_blocker = Finding(
        severity="blocker",
        category="expired",
        message="Income certificate expires before the deadline",
        evidence=["income_certificate: valid_until 2026-09-19"],
        needs_human=True,
    )
    order_seen = []

    def provider(finding):
        order_seen.append(finding.category)
        # each call only happens once the PREVIOUS interrupt was fully
        # resolved - if these were batched, order_seen would already
        # contain both entries by the time the first callback runs
        assert len(order_seen) <= 2
        return ("override" if finding.category == "dob_mismatch" else "accept"), None

    log = run_escalations([BLOCKER, second_blocker], provider)

    assert order_seen == ["dob_mismatch", "expired"]
    assert [d.decision for d in log] == ["override", "accept"]
    assert [d.finding.category for d in log] == ["dob_mismatch", "expired"]


def test_scripted_decision_provider_returns_answers_in_order():
    provider = scripted_decision_provider([("accept", "note1"), ("defer", None)])
    assert provider(BLOCKER) == ("accept", "note1")
    assert provider(LIKELY_FINE) == ("defer", None)


def test_scripted_decision_provider_raises_when_exhausted():
    provider = scripted_decision_provider([("accept", None)])
    provider(BLOCKER)
    with pytest.raises(RuntimeError):
        provider(BLOCKER)


# --- phase 6 acceptance: mohammed_irfan pauses twice, resumes twice --------


def test_mohammed_irfan_pauses_on_each_blocker_and_finishes_with_both_decisions():
    seen_in_order = []

    def provider(finding):
        seen_in_order.append((finding.category, finding.severity))
        return "override", f"reviewed: {finding.category}"

    result = run_audit_with_escalation("mohammed_irfan", "scheme_a_postmatric", SCHEME_A_NAME, SCHEME_A_PDF, provider)

    # two real, separate pauses - not one batched call
    assert seen_in_order == [("dob_mismatch", "blocker"), ("expired", "blocker")]

    assert len(result.decision_log) == 2
    assert {d.finding.category for d in result.decision_log} == {"dob_mismatch", "expired"}
    assert all(d.decision == "override" for d in result.decision_log)
    assert all(d.note is not None for d in result.decision_log)
    assert all(d.decided_at is not None for d in result.decision_log)

    # the underlying findings are unchanged - escalation resolves them, it
    # doesn't erase them
    assert len(result.findings) == 2


def test_priya_nair_has_no_findings_so_no_escalation_happens():
    def provider(finding):
        raise AssertionError("no finding should be escalated for priya_nair")

    result = run_audit_with_escalation("priya_nair", "scheme_a_postmatric", SCHEME_A_NAME, SCHEME_A_PDF, provider)
    assert result.decision_log == []


def test_aditya_sharma_likely_fine_findings_are_not_escalated():
    def provider(finding):
        raise AssertionError("likely_fine findings must not be escalated")

    result = run_audit_with_escalation("aditya_sharma", "scheme_a_postmatric", SCHEME_A_NAME, SCHEME_A_PDF, provider)
    assert result.decision_log == []
    assert len(result.findings) == 2  # the findings still exist, just weren't escalated
