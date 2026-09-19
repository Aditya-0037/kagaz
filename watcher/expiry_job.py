"""Expiry watcher (phase 7): scans every student document's valid_until
and flags anything crossing a 60/30/7-day-out or expiry-day threshold.

A scheduled job, not a chat surface — no LLM calls, pure deterministic
date arithmetic reading from the same synthetic fixtures the rest of the
system uses. One digest per run (per day, in production — see
scripts/run_watcher.py), never one email per document.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from pathlib import Path

from agents.requirement_extractor import extract_requirement_from_pdf
from fixtures_loader import list_students, student_documents
from watcher.email_backend import send_digest

SCHEMES_DIR = Path(__file__).parent.parent / "fixtures" / "schemes"

THRESHOLDS_DAYS = (60, 30, 7, 0)

SCHEMES = [
    ("scheme_a_postmatric.pdf", "scheme_a_postmatric", "Post-Matric Scholarship 2026-27"),
    ("scheme_b_merit.pdf", "scheme_b_merit", "State Merit Scholarship 2026"),
]


@dataclass(frozen=True)
class ExpiryAlert:
    student_id: str
    student_name: str
    doc_type: str
    valid_until: date
    days_out: int
    schemes: tuple[str, ...]


def _doc_type_to_schemes() -> dict[str, tuple[str, ...]]:
    """doc_type -> the names of every known scheme that requires it."""
    mapping: dict[str, list[str]] = {}
    for filename, scheme_id, scheme_name in SCHEMES:
        requirement = extract_requirement_from_pdf(SCHEMES_DIR / filename, scheme_id, scheme_name)
        for rd in requirement.required_documents:
            mapping.setdefault(rd.doc_type, []).append(scheme_name)
    return {doc_type: tuple(names) for doc_type, names in mapping.items()}


def find_expiring_documents(as_of: date) -> list[ExpiryAlert]:
    """Every document, across every student, whose valid_until crosses
    one of the 60/30/7-day-out or expiry-day thresholds relative to
    as_of. Documents that never expire (valid_until is None) are skipped."""
    doc_type_schemes = _doc_type_to_schemes()

    alerts = []
    for student in list_students():
        for doc in student_documents(student["student_id"]):
            if doc.valid_until is None:
                continue
            days_out = (doc.valid_until - as_of).days
            if days_out in THRESHOLDS_DAYS:
                alerts.append(
                    ExpiryAlert(
                        student_id=student["student_id"],
                        student_name=student["canonical_name"],
                        doc_type=doc.doc_type,
                        valid_until=doc.valid_until,
                        days_out=days_out,
                        schemes=doc_type_schemes.get(doc.doc_type, ()),
                    )
                )
    return sorted(alerts, key=lambda a: (a.days_out, a.student_id, a.doc_type))


def render_digest(alerts: list[ExpiryAlert], as_of: date) -> str:
    lines = [
        f"Kagaz Expiry Digest — {as_of.isoformat()}",
        "SYNTHETIC DEMO DATA — no real students, no real documents.",
        "",
    ]
    if not alerts:
        lines.append("No documents are approaching expiry.")
        return "\n".join(lines)

    lines.append(f"{len(alerts)} document(s) need attention:")
    lines.append("")
    for alert in alerts:
        when = "expires today" if alert.days_out == 0 else f"expires in {alert.days_out} day(s)"
        schemes = ", ".join(alert.schemes) if alert.schemes else "no scheme on file"
        lines.append(f"[{alert.days_out} days] {alert.student_name} — {alert.doc_type}")
        lines.append(f"    {when}, on {alert.valid_until.isoformat()}. Required by: {schemes}.")
    return "\n".join(lines)


def run_watcher(as_of: date) -> tuple[str, list[ExpiryAlert], Path | None]:
    """Run one watcher pass: find expiring documents, render one digest,
    send it. Returns (digest_text, alerts, outbox_path_or_None) so callers
    (scripts/run_watcher.py, tests) can inspect what happened without
    re-parsing the sent digest."""
    alerts = find_expiring_documents(as_of)
    subject = f"Kagaz Expiry Digest — {as_of.isoformat()} — {len(alerts)} document(s)"
    body = render_digest(alerts, as_of)
    outbox_path = send_digest(subject, body, as_of)
    return body, alerts, outbox_path
