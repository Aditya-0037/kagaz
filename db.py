"""Firestore-backed persistence for real-user accounts and their runs.

Only used by the /app/* real-user flow (api/auth_routes.py, api/app_routes.py).
The synthetic demo flow (api/main.py, api/run_state.py) is untouched — it
keeps its in-memory RUNS dict and pre-seeded fixtures, no Firestore
involved.

Authenticates via the same Application Default Credentials already
configured for Vertex AI (see docs/vertex-setup.md) — no separate
credentials needed. Project id comes from GOOGLE_CLOUD_PROJECT, same env
var model_provider.py uses.

Collections:
  users/{user_id}        — {email, password_hash, created_at}
  runs/{run_id}           — {user_id, status, scheme_source, created_at,
                              updated_at, ...AuditResult fields once done}
  documents/{document_id} — {user_id, doc_type, label, filename,
                              content_type, gcs_uri, uploaded_at,
                              expiry_date} — the digital locker: one
                              user's stored documents, independent of any
                              particular scheme run. expiry_date is
                              nullable ("YYYY-MM-DD", user-entered at
                              upload time) and is what powers the
                              expiring-soon view.
"""

from __future__ import annotations

import os
import uuid
from datetime import datetime, timezone
from functools import lru_cache
from typing import Any

from google.cloud import firestore


@lru_cache(maxsize=1)
def _client() -> firestore.Client:
    project = os.environ.get("GOOGLE_CLOUD_PROJECT")
    return firestore.Client(project=project)


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


# ---------------------------------------------------------------- users --

def create_user(email: str, password_hash: str) -> str:
    """Create a user with a unique email. Raises ValueError if it exists."""
    email = email.strip().lower()
    if get_user_by_email(email) is not None:
        raise ValueError(f"an account with email {email!r} already exists")
    user_id = uuid.uuid4().hex
    _client().collection("users").document(user_id).set(
        {"email": email, "password_hash": password_hash, "created_at": _now()}
    )
    return user_id


def get_user_by_email(email: str) -> dict[str, Any] | None:
    email = email.strip().lower()
    docs = (
        _client()
        .collection("users")
        .where(filter=firestore.FieldFilter("email", "==", email))
        .limit(1)
        .stream()
    )
    for doc in docs:
        data = doc.to_dict()
        data["id"] = doc.id
        return data
    return None


def get_user(user_id: str) -> dict[str, Any] | None:
    doc = _client().collection("users").document(user_id).get()
    if not doc.exists:
        return None
    data = doc.to_dict()
    data["id"] = doc.id
    return data


# ----------------------------------------------------------------- runs --

def create_run(user_id: str, scheme_source: str) -> str:
    run_id = uuid.uuid4().hex
    now = _now()
    _client().collection("runs").document(run_id).set(
        {
            "user_id": user_id,
            "status": "draft",
            "scheme_source": scheme_source,
            "created_at": now,
            "updated_at": now,
        }
    )
    return run_id


def update_run(run_id: str, **fields: Any) -> None:
    fields["updated_at"] = _now()
    _client().collection("runs").document(run_id).set(fields, merge=True)


def get_run(run_id: str) -> dict[str, Any] | None:
    doc = _client().collection("runs").document(run_id).get()
    if not doc.exists:
        return None
    data = doc.to_dict()
    data["id"] = doc.id
    return data


def list_runs_for_user(user_id: str) -> list[dict[str, Any]]:
    docs = (
        _client()
        .collection("runs")
        .where(filter=firestore.FieldFilter("user_id", "==", user_id))
        .order_by("created_at", direction=firestore.Query.DESCENDING)
        .stream()
    )
    result = []
    for doc in docs:
        data = doc.to_dict()
        data["id"] = doc.id
        result.append(data)
    return result


# ------------------------------------------------------- locker documents --

def create_document(
    user_id: str,
    doc_type: str,
    label: str,
    filename: str,
    content_type: str,
    gcs_uri: str,
    expiry_date: str | None,
) -> str:
    document_id = uuid.uuid4().hex
    _client().collection("documents").document(document_id).set(
        {
            "user_id": user_id,
            "doc_type": doc_type,
            "label": label,
            "filename": filename,
            "content_type": content_type,
            "gcs_uri": gcs_uri,
            "expiry_date": expiry_date,
            "uploaded_at": _now(),
        }
    )
    return document_id


def get_document(document_id: str) -> dict[str, Any] | None:
    doc = _client().collection("documents").document(document_id).get()
    if not doc.exists:
        return None
    data = doc.to_dict()
    data["id"] = doc.id
    return data


def list_documents_for_user(user_id: str) -> list[dict[str, Any]]:
    docs = (
        _client()
        .collection("documents")
        .where(filter=firestore.FieldFilter("user_id", "==", user_id))
        .order_by("uploaded_at", direction=firestore.Query.DESCENDING)
        .stream()
    )
    result = []
    for doc in docs:
        data = doc.to_dict()
        data["id"] = doc.id
        result.append(data)
    return result


def update_document(document_id: str, **fields: Any) -> None:
    """Change a locker document's metadata (label, doc_type, expiry).
    The stored file itself is never rewritten — replacing a file means
    uploading a new document."""
    fields["updated_at"] = _now()
    _client().collection("documents").document(document_id).set(fields, merge=True)


def delete_document(document_id: str) -> None:
    _client().collection("documents").document(document_id).delete()
