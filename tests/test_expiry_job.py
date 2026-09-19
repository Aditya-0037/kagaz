"""Expiry watcher tests — phase 7. No LLM calls (find_expiring_documents
and render_digest are pure date arithmetic); run_watcher additionally
calls the cached requirement extractor, so it needs replay mode.
"""

from datetime import date

import pytest

import watcher.email_backend as email_backend
from watcher.expiry_job import find_expiring_documents, render_digest, run_watcher

MOHAMMED_INCOME_CERT_EXPIRY = date(2026, 9, 19)


@pytest.fixture(autouse=True)
def _replay_mode(monkeypatch):
    monkeypatch.setenv("KAGAZ_LLM_MODE", "replay")
    monkeypatch.setenv("KAGAZ_MODEL_PROVIDER", "vertex")


@pytest.fixture(autouse=True)
def _isolated_outbox(monkeypatch, tmp_path):
    monkeypatch.setattr(email_backend, "OUTBOX_DIR", tmp_path)


# --- pure date logic, no requirement extraction involved --------------------


def test_no_alerts_far_from_any_expiry():
    assert find_expiring_documents(date(2026, 1, 1)) == []


def test_finds_exactly_one_document_at_each_threshold():
    for days_out, as_of in [
        (60, date(2026, 7, 21)),
        (30, date(2026, 8, 20)),
        (7, date(2026, 9, 12)),
        (0, date(2026, 9, 19)),
    ]:
        alerts = find_expiring_documents(as_of)
        assert len(alerts) == 1, f"as_of={as_of}: expected 1 alert, got {alerts}"
        assert alerts[0].student_id == "mohammed_irfan"
        assert alerts[0].doc_type == "income_certificate"
        assert alerts[0].days_out == days_out
        assert alerts[0].valid_until == MOHAMMED_INCOME_CERT_EXPIRY


def test_off_threshold_date_has_no_alerts():
    # one day off any threshold - 8 days out, not 7
    assert find_expiring_documents(date(2026, 9, 11)) == []


# --- exact digest content at three different --as-of dates ------------------


def test_digest_content_at_seven_days_out():
    body, alerts, _ = run_watcher(date(2026, 9, 12))
    assert len(alerts) == 1
    assert body == (
        "Kagaz Expiry Digest — 2026-09-12\n"
        "SYNTHETIC DEMO DATA — no real students, no real documents.\n"
        "\n"
        "1 document(s) need attention:\n"
        "\n"
        "[7 days] Mohammed Irfan Sheikh — income_certificate\n"
        "    expires in 7 day(s), on 2026-09-19. Required by: Post-Matric Scholarship 2026-27."
    )


def test_digest_content_at_thirty_days_out():
    body, alerts, _ = run_watcher(date(2026, 8, 20))
    assert len(alerts) == 1
    assert body == (
        "Kagaz Expiry Digest — 2026-08-20\n"
        "SYNTHETIC DEMO DATA — no real students, no real documents.\n"
        "\n"
        "1 document(s) need attention:\n"
        "\n"
        "[30 days] Mohammed Irfan Sheikh — income_certificate\n"
        "    expires in 30 day(s), on 2026-09-19. Required by: Post-Matric Scholarship 2026-27."
    )


def test_digest_content_on_expiry_day():
    body, alerts, _ = run_watcher(date(2026, 9, 19))
    assert len(alerts) == 1
    assert body == (
        "Kagaz Expiry Digest — 2026-09-19\n"
        "SYNTHETIC DEMO DATA — no real students, no real documents.\n"
        "\n"
        "1 document(s) need attention:\n"
        "\n"
        "[0 days] Mohammed Irfan Sheikh — income_certificate\n"
        "    expires today, on 2026-09-19. Required by: Post-Matric Scholarship 2026-27."
    )


def test_digest_content_with_no_alerts():
    body, alerts, _ = run_watcher(date(2026, 1, 1))
    assert alerts == []
    assert body == (
        "Kagaz Expiry Digest — 2026-01-01\n"
        "SYNTHETIC DEMO DATA — no real students, no real documents.\n"
        "\n"
        "No documents are approaching expiry."
    )


# --- one digest per run, not one email per document --------------------------


def test_one_digest_file_written_per_run():
    _body, _alerts, outbox_path = run_watcher(date(2026, 9, 12))
    assert outbox_path is not None
    assert outbox_path.exists()
    assert outbox_path.name == "expiry-digest-2026-09-12.txt"
    content = outbox_path.read_text(encoding="utf-8")
    assert content.count("Subject:") == 1  # exactly one message, not one per document


def test_render_digest_is_pure_and_matches_run_watcher_body():
    alerts = find_expiring_documents(date(2026, 9, 12))
    assert render_digest(alerts, date(2026, 9, 12)) == run_watcher(date(2026, 9, 12))[0]
