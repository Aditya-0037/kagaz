"""Web UI tests (phase 8b) — drives the real HTTP flow with FastAPI's
TestClient, including the escalation screen actually blocking the
background run until a decision is POSTed.
"""

import time

import pytest
from fastapi.testclient import TestClient

from api.main import app

client = TestClient(app)


@pytest.fixture(autouse=True)
def _replay_mode(monkeypatch):
    monkeypatch.setenv("KAGAZ_LLM_MODE", "replay")
    monkeypatch.setenv("KAGAZ_MODEL_PROVIDER", "vertex")


def _wait_until(run_url: str, predicate, timeout: float = 20.0) -> str:
    deadline = time.monotonic() + timeout
    last_text = ""
    while time.monotonic() < deadline:
        response = client.get(run_url)
        last_text = response.text
        if predicate(last_text):
            return last_text
        time.sleep(0.1)
    raise AssertionError(f"timed out waiting for condition; last page:\n{last_text[:500]}")


def _start_run(student_id: str, scheme_id: str = "scheme_a_postmatric") -> str:
    response = client.post("/run", data={"student_id": student_id, "scheme_id": scheme_id}, follow_redirects=False)
    assert response.status_code == 303
    return response.headers["location"]


def test_landing_page_shows_every_scheme_input_method():
    # "/" is the product landing page, not the demo picker — a visitor has
    # to be able to see that link/screenshot/PDF/text input all exist
    # without signing up first.
    response = client.get("/")
    assert response.status_code == 200
    assert "Paste a link" in response.text
    assert "Upload a screenshot" in response.text
    assert "Upload the PDF" in response.text
    assert "Paste the text" in response.text


def test_demo_lists_students_and_schemes():
    response = client.get("/demo")
    assert response.status_code == 200
    assert "Priya Ramesh Nair" in response.text
    assert "Mohammed Irfan Sheikh" in response.text
    assert "Post-Matric Scholarship" in response.text
    assert "State Merit Scholarship" in response.text


def test_unknown_run_id_is_404():
    assert client.get("/run/does-not-exist").status_code == 404


def test_priya_nair_runs_to_completion_with_no_escalation_and_downloads():
    run_url = _start_run("priya_nair")
    text = _wait_until(run_url, lambda t: "wall clock" in t)

    assert "checked out" in text.lower()  # the "no findings" card
    assert "Human review needed" not in text

    run_id = run_url.rsplit("/", 1)[-1]
    download = client.get(f"/run/{run_id}/download")
    assert download.status_code == 200
    assert download.headers["content-type"] == "application/zip"
    assert len(download.content) > 1000


def test_mohammed_irfan_escalation_screen_blocks_until_decision_submitted():
    run_url = _start_run("mohammed_irfan")

    # first pause: the run must NOT be able to reach "complete" on its own
    text = _wait_until(run_url, lambda t: "Human review needed" in t)
    assert "dob mismatch" in text.lower() or "expired" in text.lower()

    # confirm it stays blocked - polling again a moment later must still
    # show the same escalation screen, not silently progress
    time.sleep(0.3)
    still_blocked = client.get(run_url).text
    assert "Human review needed" in still_blocked

    decide = client.post(
        f"{run_url}/decide", data={"decision": "override", "note": "confirmed with student"}, follow_redirects=False
    )
    assert decide.status_code == 303

    # second pause
    text = _wait_until(run_url, lambda t: "Human review needed" in t)
    decide = client.post(f"{run_url}/decide", data={"decision": "accept", "note": ""}, follow_redirects=False)
    assert decide.status_code == 303

    text = _wait_until(run_url, lambda t: "wall clock" in t)
    assert "decision log" in text
    assert "override" in text
    assert "confirmed with student" in text
    assert "accept" in text


def test_submitting_a_decision_when_none_is_pending_is_rejected():
    run_url = _start_run("priya_nair")
    _wait_until(run_url, lambda t: "wall clock" in t)  # let it finish, no escalation ever happens

    response = client.post(f"{run_url}/decide", data={"decision": "accept", "note": ""})
    assert response.status_code == 409
