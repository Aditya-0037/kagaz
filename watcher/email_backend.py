"""Pluggable email transport for the expiry digest (phase 7). No LLM.

KAGAZ_EMAIL_BACKEND:
  file (default) - renders to outbox/, works offline, no credentials.
  ses            - boto3 SES. Written now, never called (no AWS
                    credentials exist for this project), guarded exactly
                    like model_provider.py's bedrock branch: boto3 is
                    imported only inside _send_ses, never at module scope.
"""

from __future__ import annotations

import os
from datetime import date
from pathlib import Path

OUTBOX_DIR = Path(__file__).parent.parent / "outbox"


def _send_file(subject: str, body: str, as_of: date) -> Path:
    OUTBOX_DIR.mkdir(parents=True, exist_ok=True)
    path = OUTBOX_DIR / f"expiry-digest-{as_of.isoformat()}.txt"
    path.write_text(f"Subject: {subject}\n\n{body}", encoding="utf-8")
    return path


def _send_ses(subject: str, body: str) -> None:
    import boto3  # imported here only - never at module scope, see docstring

    client = boto3.client("ses", region_name=os.environ.get("AWS_REGION", "us-east-1"))
    client.send_email(
        Source=os.environ.get("KAGAZ_DIGEST_FROM", "kagaz-noreply@example.org"),
        Destination={"ToAddresses": [os.environ.get("KAGAZ_DIGEST_TO", "coordinator@example.org")]},
        Message={"Subject": {"Data": subject}, "Body": {"Text": {"Data": body}}},
    )


def send_digest(subject: str, body: str, as_of: date) -> Path | None:
    """Send one digest. Returns the outbox file path for the `file`
    backend, or None for `ses` (nothing local to point to)."""
    backend = os.environ.get("KAGAZ_EMAIL_BACKEND", "file")
    if backend == "file":
        return _send_file(subject, body, as_of)
    if backend == "ses":
        _send_ses(subject, body)
        return None
    raise ValueError(f"Unknown KAGAZ_EMAIL_BACKEND: {backend!r}")
