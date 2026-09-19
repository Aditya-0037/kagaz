"""Phase A: password hashing (pure, no network) and the signup/login/logout
web flow. The web flow needs real Firestore (no emulator wired up yet, see
plan), so it's skipped unless GOOGLE_CLOUD_PROJECT is configured — same
pattern as tests/test_model_provider.py's live-provider tests.
"""

import os
import uuid

import pytest
from fastapi.testclient import TestClient

from auth import hash_password, verify_password

pytestmark_live = pytest.mark.skipif(
    "GOOGLE_CLOUD_PROJECT" not in os.environ,
    reason="no GOOGLE_CLOUD_PROJECT configured for this environment yet",
)


def test_hash_password_is_salted_differently_each_time():
    a = hash_password("correct horse battery staple")
    b = hash_password("correct horse battery staple")
    assert a != b  # different random salts
    assert verify_password("correct horse battery staple", a)
    assert verify_password("correct horse battery staple", b)


def test_verify_password_rejects_wrong_password():
    hashed = hash_password("correct horse battery staple")
    assert not verify_password("wrong password", hashed)


def test_verify_password_rejects_garbage_stored_value():
    assert not verify_password("anything", "not-a-valid-stored-hash")


@pytestmark_live
class TestWebFlow:
    @pytest.fixture(autouse=True)
    def _setup(self, monkeypatch):
        monkeypatch.setenv("KAGAZ_LLM_MODE", "replay")
        monkeypatch.setenv("KAGAZ_MODEL_PROVIDER", "vertex")
        from api.main import app

        self.client = TestClient(app)
        self.email = f"test-{uuid.uuid4().hex}@example.com"
        self.password = "correct horse battery staple"

    def test_app_redirects_to_login_when_logged_out(self):
        response = self.client.get("/app", follow_redirects=False)
        assert response.status_code == 303
        assert response.headers["location"] == "/login"

    def test_signup_creates_a_user_and_logs_in(self):
        response = self.client.post(
            "/signup", data={"email": self.email, "password": self.password}, follow_redirects=False
        )
        assert response.status_code == 303
        assert response.headers["location"] == "/app"

        dashboard = self.client.get("/app")
        assert dashboard.status_code == 200
        assert self.email in dashboard.text

    def test_duplicate_email_is_rejected(self):
        self.client.post("/signup", data={"email": self.email, "password": self.password})
        response = self.client.post("/signup", data={"email": self.email, "password": self.password})
        assert response.status_code == 200
        assert "already exists" in response.text

    def test_login_sets_session_and_wrong_password_is_rejected(self):
        self.client.post("/signup", data={"email": self.email, "password": self.password})
        self.client.post("/logout")

        bad = self.client.post("/login", data={"email": self.email, "password": "wrong password"})
        assert bad.status_code == 200
        assert "Incorrect email or password" in bad.text

        good = self.client.post(
            "/login", data={"email": self.email, "password": self.password}, follow_redirects=False
        )
        assert good.status_code == 303
        assert good.headers["location"] == "/app"

    def test_logout_clears_session(self):
        self.client.post("/signup", data={"email": self.email, "password": self.password})
        self.client.post("/logout")
        response = self.client.get("/app", follow_redirects=False)
        assert response.status_code == 303
        assert response.headers["location"] == "/login"
