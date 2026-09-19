"""Real-account equivalent of api/run_state.py: bridges the coordinator's
synchronous escalation flow with the web request/response cycle, for a
run against a real user's own uploaded/mapped documents instead of a
pre-seeded synthetic student.

Same demo-scale design as run_state.py (in-memory RUNS dict, one thread
per run) — the difference is real runs also persist their outcome to
Firestore (db.update_run) so they still show up on the dashboard after
the in-memory state is gone (server restart, or just a while later).
"""

from __future__ import annotations

import queue
import shutil
import threading
from dataclasses import dataclass, field
from pathlib import Path
from typing import Literal

import db
from agents.coordinator import REAL_OCR_CACHE_DIR, run_real_audit_with_escalation
from blob_storage import download_to_temp
from contracts import AuditResult, Finding, Requirement
from tools.packager import package_audit

PACKAGES_DIR = Path(__file__).parent.parent / "outbox" / "real_packages"


@dataclass
class RealRunState:
    run_id: str
    user_id: str
    status: Literal["running", "awaiting_decision", "complete", "error"] = "running"
    pending_finding: Finding | None = None
    reviewed_count: int = 0
    result: AuditResult | None = None
    package_dir: Path | None = None
    error: str | None = None
    decision_queue: queue.Queue = field(default_factory=queue.Queue, repr=False)


RUNS: dict[str, RealRunState] = {}


def _decision_provider(state: RealRunState):
    def provider(finding: Finding) -> tuple[str, str | None]:
        state.pending_finding = finding
        state.status = "awaiting_decision"
        decision, note = state.decision_queue.get()  # blocks here until /decide posts
        state.reviewed_count += 1
        state.pending_finding = None
        state.status = "running"
        return decision, note

    return provider


def _run(state: RealRunState, requirement: Requirement, gcs_uris: dict[str, str]) -> None:
    temp_paths: dict[str, Path] = {}
    try:
        for doc_type, gcs_uri in gcs_uris.items():
            temp_paths[doc_type] = download_to_temp(gcs_uri)

        result = run_real_audit_with_escalation(
            state.user_id, state.run_id, requirement, temp_paths, _decision_provider(state)
        )
        state.result = result
        state.package_dir = package_audit(result, PACKAGES_DIR, synthetic=False)
        state.status = "complete"
        db.update_run(
            state.run_id,
            status="complete",
            findings_count=len(result.findings),
            blocker_count=sum(1 for f in result.findings if f.severity == "blocker"),
        )
    except Exception as exc:  # noqa: BLE001 - surfaced to the UI, never swallowed silently
        state.status = "error"
        state.error = str(exc)
        db.update_run(state.run_id, status="error", error=str(exc))
    finally:
        # Temp downloads exist only for this run's verification pass —
        # real document bytes never linger on local disk after it.
        for path in temp_paths.values():
            path.unlink(missing_ok=True)
        # Same for the OCR text of those documents. It is cached during
        # the run (several verifiers read the same file), then dropped —
        # it is a transcript of someone's income certificate.
        shutil.rmtree(REAL_OCR_CACHE_DIR, ignore_errors=True)


def start_run(run_id: str, user_id: str, requirement: Requirement, gcs_uris: dict[str, str]) -> RealRunState:
    state = RealRunState(run_id=run_id, user_id=user_id)
    RUNS[run_id] = state
    db.update_run(run_id, status="running")
    threading.Thread(target=_run, args=(state, requirement, gcs_uris), daemon=True).start()
    return state


def submit_decision(run_id: str, decision: str, note: str | None) -> None:
    state = RUNS.get(run_id)
    if state is None:
        raise KeyError(run_id)
    if state.status != "awaiting_decision":
        raise ValueError("no decision is currently pending for this run")
    state.decision_queue.put((decision, note))
