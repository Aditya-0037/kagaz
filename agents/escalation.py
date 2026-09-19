"""The escalation interrupt (spec section 6.6, phase 6).

When the coordinator hits a Finding with needs_human=True, this raises a
real Strands interrupt — the SDK's actual pause/resume mechanism
(strands.types.tools.ToolContext.interrupt(), confirmed in
docs/sdk-notes.md), not a status flag or a while loop. Execution genuinely
pauses; a human (or, in tests, a scripted decision_provider) supplies a
HumanDecision; execution resumes from exactly that point.

One finding at a time, never batched: escalate_one() raises one interrupt,
waits for one resume. run_escalations() calls it in a loop over every
needs_human Finding, sequentially — each finding is fully paused and
resolved before the next one is even raised.

The tool that gets called (`escalate`) is backed by
model_provider.get_scripted_tool_call_model(), not a real LLM call — see
that function's docstring for why: which tool to call isn't a judgment
call here (Python already knows a Finding needs review), so there's
nothing for a model to decide. This keeps the whole flow network-free by
construction, not by routing through llm_cache's replay mode — it never
makes a model call to route in the first place. Verified empirically that
this still exercises the SDK's genuine interrupt/resume protocol
end-to-end (see the phase 6 commit message).
"""

from __future__ import annotations

from typing import Callable

from strands import Agent, tool
from strands.types.tools import ToolContext

from contracts import Finding, HumanDecision
from model_provider import get_scripted_tool_call_model

# Given a Finding, return (decision, note). In production this would come
# from a human via the web UI (phase 8); in tests, a scripted sequence.
DecisionProvider = Callable[[Finding], tuple[str, str | None]]


def _make_escalate_tool(finding: Finding, finding_index: int):
    @tool(name="escalate", context=True)
    def escalate(tool_context: ToolContext) -> str:
        """Pause this run and ask a human to decide on the flagged finding."""
        response = tool_context.interrupt(
            f"kagaz-escalation-{finding_index}",
            reason={
                "finding_index": finding_index,
                "severity": finding.severity,
                "category": finding.category,
                "message": finding.message,
                "evidence": finding.evidence,
            },
        )
        return f"Human decision recorded: {response}"

    return escalate


def escalate_one(finding: Finding, finding_index: int, decision_provider: DecisionProvider) -> HumanDecision:
    """Raise a real interrupt for one Finding, resume it with whatever
    decision_provider returns, and record the result as a HumanDecision."""
    escalate = _make_escalate_tool(finding, finding_index)
    agent = Agent(model=get_scripted_tool_call_model("escalate"), tools=[escalate])

    result = agent(f"A finding needs human review: {finding.message}")
    if result.stop_reason != "interrupt":
        raise RuntimeError(
            f"expected an interrupt escalating finding #{finding_index}, got stop_reason={result.stop_reason!r}"
        )

    decision, note = decision_provider(finding)

    agent([{"interruptResponse": {"interruptId": result.interrupts[0].id, "response": decision}}])

    return HumanDecision(finding=finding, decision=decision, note=note)


def run_escalations(findings: list[Finding], decision_provider: DecisionProvider) -> list[HumanDecision]:
    """Escalate every needs_human Finding, one at a time, in order.
    Findings that don't need a human are skipped entirely."""
    decision_log: list[HumanDecision] = []
    for i, finding in enumerate(findings):
        if not finding.needs_human:
            continue
        decision_log.append(escalate_one(finding, i, decision_provider))
    return decision_log


def scripted_decision_provider(answers: list[tuple[str, str | None]]) -> DecisionProvider:
    """A DecisionProvider that returns answers from a fixed list in order
    — "a scripted answer sequence" for driving interrupts in tests with no
    human present. Raises if more findings are escalated than answers were
    scripted for, rather than silently reusing/guessing an answer."""
    it = iter(answers)

    def provider(finding: Finding) -> tuple[str, str | None]:
        try:
            return next(it)
        except StopIteration:
            raise RuntimeError(
                f"ran out of scripted decisions while escalating finding: {finding.message!r}"
            ) from None

    return provider
