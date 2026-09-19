"""In-memory run-state store bridging the coordinator's synchronous
escalation flow with the web UI's request/response cycle.

Demo-scale, single-process design: RUNS is a plain module-level dict and
each run executes on its own background thread. Production would use a
real job queue; for a one-worker FastAPI demo serving three synthetic
students, in-memory state is honest and simple rather than over-built.

The escalation screen "blocking the graph until a button is clicked" (the
phase 8 acceptance criterion) works because _decision_provider's inner
function calls queue.Queue.get(), which genuinely blocks the background
thread running agents.coordinator.run_audit_with_escalation — the escalate
interrupt (agents/escalation.py) is raised and stays unresolved until
submit_decision() puts a value on that same queue from the /decide route.
"""

from __future__ import annotations

import queue
import threading
import uuid
from dataclasses import dataclass, field
from pathlib import Path
from typing import Literal

from agents.coordinator import run_audit_with_escalation
from contracts import AuditResult, Finding
from tools.packager import package_audit

SCHEMES_DIR = Path(__file__).parent.parent / "fixtures" / "schemes"
PACKAGES_DIR = Path(__file__).parent.parent / "outbox" / "packages"

# doc_id -> (pdf filename, display name)
SCHEMES: dict[str, tuple[str, str]] = {
    "scheme_a_postmatric": ("scheme_a_postmatric.pdf", "Post-Matric Scholarship 2026-27"),
    "scheme_b_merit": ("scheme_b_merit.pdf", "State Merit Scholarship 2026"),
}


@dataclass
class RunState:
    run_id: str
    student_id: str
    scheme_id: str
    status: Literal["running", "awaiting_decision", "complete", "error"] = "running"
    pending_finding: Finding | None = None
    reviewed_count: int = 0
    result: AuditResult | None = None
    package_dir: Path | None = None
    error: str | None = None
    decision_queue: queue.Queue = field(default_factory=queue.Queue, repr=False)


RUNS: dict[str, RunState] = {}


def _decision_provider(state: RunState):
    def provider(finding: Finding) -> tuple[str, str | None]:
        state.pending_finding = finding
        state.status = "awaiting_decision"
        decision, note = state.decision_queue.get()  # blocks here until /decide posts
        state.reviewed_count += 1
        state.pending_finding = None
        state.status = "running"
        return decision, note

    return provider


def _run(state: RunState) -> None:
    filename, scheme_name = SCHEMES[state.scheme_id]
    try:
        result = run_audit_with_escalation(
            state.student_id,
            state.scheme_id,
            scheme_name,
            SCHEMES_DIR / filename,
            _decision_provider(state),
        )
        state.result = result
        state.package_dir = package_audit(result, PACKAGES_DIR)
        state.status = "complete"
    except Exception as exc:  # noqa: BLE001 - surfaced to the UI, never swallowed silently
        state.status = "error"
        state.error = str(exc)


def start_run(student_id: str, scheme_id: str) -> RunState:
    run_id = uuid.uuid4().hex[:12]
    state = RunState(run_id=run_id, student_id=student_id, scheme_id=scheme_id)
    RUNS[run_id] = state
    threading.Thread(target=_run, args=(state,), daemon=True).start()
    return state


def submit_decision(run_id: str, decision: str, note: str | None) -> None:
    state = RUNS.get(run_id)
    if state is None:
        raise KeyError(run_id)
    if state.status != "awaiting_decision":
        raise ValueError("no decision is currently pending for this run")
    state.decision_queue.put((decision, note))
