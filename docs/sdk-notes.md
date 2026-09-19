# Strands Agents SDK notes

Do not trust prior knowledge of this SDK's API — it moves fast and names or
signatures below may already be stale by the time you read this. Re-check
against strandsagents.com if anything here looks off, especially anything
in the "not yet confirmed" section.

## Investigated 2026-09-19, resolved empirically once ADC was available (Vertex AI migration, STEP 0)

Source: https://strandsagents.com/docs/user-guide/concepts/model-providers/google/,
https://strandsagents.com/docs/api/python/strands.models.gemini/,
https://github.com/strands-agents/sdk-python/issues/1121,
https://github.com/strands-agents/sdk-python/issues/1039,
web search results on google-genai Vertex AI configuration.

**(a) Import/constructor — confirmed:**
`from strands.models.gemini import GeminiModel`.
`GeminiModel(client_args={...}, model_id="gemini-2.5-flash", params={...})`
— `client_args` are "arguments for the underlying Gemini client",
`params` covers `temperature`/`max_output_tokens`/`top_p`/`top_k`, plus a
`gemini_tools` option for Gemini-native built-in tools. `structured_output`
is implemented as `async def structured_output(output_model, prompt,
system_prompt=None, **kwargs) -> AsyncGenerator[dict[str, T | Any], None]`,
matching the base `Model` class shape.

**(b) `structured_output_model=` support on Gemini/Vertex — CONFIRMED
WORKING for Kagaz's usage, empirically, against real Vertex AI
(project `kagaz-509105`, `gemini-2.5-flash`, region `us-central1`).**
Two live calls both succeeded on the first try, no retry needed:
- A minimal single-field schema (`class Simple(BaseModel): color: str`).
- Kagaz's actual `agents/verifiers/common.VerifierOutput` (11 optional
  fields) against a realistic income-certificate OCR prompt — every field
  extracted correctly, no `tools[0].tool_type` error, no
  `StructuredOutputException`.

This resolves the ambiguity documented below (kept for the record — the
open GitHub issue itself may still affect *other* usage patterns, just
not the one this repo relies on):
- A Strands maintainer (dbschmigelski) confirmed `structured_output_model=`
  (not the deprecated `.structured_output()` method) is the intended
  current API "across all providers," including Gemini.
- **GitHub issue #1121** ("GeminiModel doesn't support the
  structured_output implementation"), filed 2025-10-31, still open as of
  last check (2026-07-10, 7 comments). Reproduction: `400 INVALID_ARGUMENT
  — "tools[0].tool_type: required one_of 'tool_type' must have one
  initialized field"` when calling `structured_output_model=` on
  `GeminiModel`. The reporter's repro combined structured output with
  ~20 additional tools plus MCP servers — a heavier setup than Kagaz's
  (Kagaz's extractor/verifier calls use `structured_output_model=` with
  no other tools attached), which is exactly the hypothesis the empirical
  test above confirms: Kagaz's narrower usage (no extra tools attached to
  the structured-output call) is unaffected.
- **GitHub issue #1039** ("GeminiModel failure when using Vertex AI mode
  without tools"), same error signature, was closed — root cause was the
  provider always sending an empty `tools` array, which Vertex AI's proto
  validation rejects (fix: omit `tools` entirely when there are none).
  Plausibly the same underlying fix (PR #1040, referenced by a commenter
  on #1121) is why Kagaz's own no-extra-tools calls work cleanly.

**(c) Vertex AI routing — confirmed, and corrects an assumption from the
original instructions.** It is **not** `client_args={"vertexai": True,
"project": ..., "location": ...}` in the primary documented pattern (that
shape is *plausible* as an alternative since `client_args` passes through
to `google.genai.Client(...)`, which likely accepts those as direct
kwargs too — but the confirmed, maintainer-used pattern in issue #1039's
own reproduction code is environment-variable-driven):
```python
os.environ["GOOGLE_GENAI_USE_VERTEXAI"] = "True"
# plus GOOGLE_CLOUD_PROJECT, GOOGLE_CLOUD_LOCATION
from strands.models.gemini import GeminiModel
GeminiModel(model_id="gemini-2.5-flash")  # no client_args needed
```
Confirmed against google-genai's own documented pattern (not just
asserted): `GOOGLE_GENAI_USE_VERTEXAI=true` + `GOOGLE_CLOUD_PROJECT` +
`GOOGLE_CLOUD_LOCATION` + Application Default Credentials (`gcloud auth
application-default login`) is the standard, documented way to point the
underlying `google-genai` client at Vertex AI instead of the Gemini
Developer API / AI Studio API key path.

**(d) Multimodal image input — confirmed.** "Gemini models support text,
image, document, and video inputs" (PNG/JPEG/GIF/WebP images, PDF
documents, MP4 video). Example:
```python
agent([{
    "role": "user",
    "content": [
        {"text": "What do you see in this image?"},
        {"image": {"format": "jpeg", "source": {"bytes": image_bytes}}},
    ],
}])
```

## Confirmed 2026-09-03 (for the Phase 1 model provider factory)

Source: https://strandsagents.com/docs/user-guide/concepts/model-providers/ollama/,
https://pypi.org/project/strands-agents/, https://pypi.org/project/strands-agents-tools/

- Package versions pinned in `requirements.txt`: `strands-agents==1.54.0`,
  `strands-agents-tools==0.8.7`.
- Ollama support is an extra: `pip install 'strands-agents[ollama]'`.
- Import: `from strands.models.ollama import OllamaModel`.
- Constructor: `OllamaModel(host=..., model_id=..., keep_alive="5m", temperature=..., top_p=..., stop_sequences=..., options=..., max_tokens=...)`.
  Only `host` and `model_id` are required. Constructing it does not touch
  the network — it just stores config. The network call happens when an
  `Agent` built with this model actually runs.
- Usage: `Agent(model=OllamaModel(host="http://localhost:11434", model_id="llama3.1"))`.
- Base type: `strands.models.Model` — `model_provider.py::get_model()` is
  typed to return this.
- `AnthropicModel` exists at `strands.models.anthropic.AnthropicModel` (not
  wired up yet — no Anthropic API key configured for this project). Not
  independently verified beyond the import path; re-check before wiring it
  up.
- A `BedrockModel` almost certainly exists at `strands.models.bedrock` by
  the same naming convention, but this was **not fetched or confirmed** —
  don't build against it from memory. The `bedrock` branch in
  `model_provider.py` raises `NotImplementedError` and stays that way until
  there are AWS credentials and this gets a real doc check.

## Confirmed 2026-09-03 (for phase 4 — the requirement extractor)

Source: https://strandsagents.com/docs/user-guide/concepts/agents/structured-output/,
https://strandsagents.com/docs/user-guide/concepts/tools/custom-tools/

- **Structured output.** `Agent.structured_output()` is a *deprecated*
  method — do not use it. The current API is parameter-based on a normal
  agent call:

  ```python
  from pydantic import BaseModel, Field
  from strands import Agent

  class PersonInfo(BaseModel):
      name: str = Field(description="Name of the person")

  agent = Agent(model=my_model)
  result = agent("John is 30 years old", structured_output_model=PersonInfo)
  person: PersonInfo = result.structured_output
  ```

  Parameter name is `structured_output_model`. Return value is an
  `AgentResult`; the validated Pydantic instance is on `.structured_output`.
  `requirement_extractor.py` uses this for all four decomposed calls.

- **`@tool` decorator.** Import: `from strands import tool`.

  ```python
  @tool
  def weather_forecast(city: str, days: int = 3) -> str:
      """Get weather forecast for a city.

      Args:
          city: The name of the city
          days: Number of days for the forecast
      """
      ...
  ```

  First docstring paragraph becomes the tool description; an `Args:`
  section documents each parameter. Optional decorator arguments: `name`,
  `description` (both override the function/docstring), `inputSchema`
  (custom JSON schema), `context` (opt into `ToolContext` access). Pass
  decorated functions to an agent via `Agent(tools=[weather_forecast])`.
  Not used yet in phase 4 (the extractor is four structured-output calls,
  no tool-calling loop) — reserved for phase 5 verifiers/coordinator, where
  `tools/*.py` functions likely get wired in this way.

## Confirmed 2026-09-03 (for phase 5 — coordinator, and phase 6 — escalation)

Source: https://strandsagents.com/docs/user-guide/concepts/multi-agent/multi-agent-patterns/,
https://strandsagents.com/docs/user-guide/concepts/multi-agent/graph/,
https://strandsagents.com/docs/user-guide/concepts/multi-agent/workflow/,
https://strandsagents.com/docs/user-guide/concepts/interrupts/,
https://strandsagents.com/docs/user-guide/observability-evaluation/metrics/,
https://strandsagents.com/docs/user-guide/concepts/model-providers/amazon-bedrock/

- **Multi-agent pattern chosen: Workflow.** Strands names four patterns:
  Agents-as-Tools (an orchestrator agent decides which sub-agent-tool to
  call), Swarm (autonomous handoff, shared context, for open-ended
  collaboration), Graph (`GraphBuilder`/`add_node`/`add_edge` — but routing
  is driven by *an LLM's decision at each node*, and dependent nodes
  receive "a combined input" merged from their dependencies, not distinct
  per-node input), and Workflow — which the docs describe as implemented
  in **plain code, not a dedicated SDK class**: "you wire the agents
  together in plain code... the most explicit and auditable of all the
  patterns." Kagaz's verifier fan-out is deterministic dispatch (Python
  already knows exactly which document types need which verifier from
  `Requirement.required_documents` — no LLM needs to decide that) and each
  verifier needs its own distinct input (that document's OCR text, not a
  shared prompt blob). Graph and Swarm are built for LLM-driven routing and
  autonomous agent-to-agent handoff, neither of which this pipeline needs;
  forcing either on would add non-determinism and complexity with no
  benefit. `agents/coordinator.py` therefore calls verifier agents directly
  from Python, in parallel via `concurrent.futures.ThreadPoolExecutor`
  (independent calls, no data dependency between them), and calls
  `agents/cross_checker.py` sequentially after — this **is** the Workflow
  pattern per the docs' own definition, not a workaround.

- **Interrupts.** `strands.types.tools.ToolContext` — a tool decorated
  `@tool(context=True)` receives `tool_context` and can call
  `tool_context.interrupt(name: str, reason: dict) -> Any`, which pauses
  the agent and returns the human's response inline once resumed. Detect a
  pause via `result.stop_reason == "interrupt"`; the paused interrupts are
  on `result.interrupts` (each with `.id`, `.reason`). Resume by calling
  the agent again with a list, not a text prompt:
  `agent([{"interruptResponse": {"interruptId": result.interrupts[0].id, "response": <value>}}])`.
  Interrupts fire from **tool execution code**, independent of whether the
  underlying model call was cached/replayed or live — confirmed safe to
  drive with `KAGAZ_LLM_MODE=replay` and a scripted response sequence, no
  network needed. Multi-agent (Swarm/Graph) support exists via
  `BeforeNodeCallEvent` hooks and `result.status == Status.INTERRUPTED`,
  but Kagaz doesn't use Graph/Swarm (see above) — phase 6's escalation
  interrupt is a single-agent interrupt (one small Agent whose only tool is
  `escalate`), which is the documented base case, not the multi-agent
  extension.

## Confirmed 2026-09-04 (for phase 6 — model_provider.ScriptedToolCallModel)

Source: https://strandsagents.com/docs/user-guide/concepts/model-providers/custom_model_provider/,
https://strandsagents.com/docs/api/python/strands.models.model/

- `strands.models.Model` has **four** abstract methods, not the three a
  first search suggested — missing `structured_output` breaks
  instantiation with `TypeError: Can't instantiate abstract class ... without
  an implementation for abstract method 'structured_output'` (hit this
  directly while building the escalation trigger model, fixed by
  implementing it as a stub that raises `NotImplementedError`, since this
  model is only ever used to trigger one fixed tool call — it never needs
  structured output):
  - `stream(messages, tool_specs=None, system_prompt=None, *, tool_choice=None, system_prompt_content=None, invocation_state=None, cancel_signal=None, **kwargs) -> AsyncIterable[StreamEvent]`
  - `structured_output(output_model, prompt, system_prompt=None, **kwargs) -> AsyncGenerator[dict, None]`
  - `update_config(**model_config) -> None`
  - `get_config() -> Any`
- A minimal `stream()` implementation that deterministically triggers one
  tool call, verified working end-to-end (real interrupt raised, real
  resume, no network):
  ```python
  async def stream(self, messages, tool_specs=None, system_prompt=None, **kwargs):
      yield {"messageStart": {"role": "assistant"}}
      yield {"contentBlockStart": {"start": {"toolUse": {"name": self._tool_name, "toolUseId": "..."}}}}
      yield {"contentBlockDelta": {"delta": {"toolUse": {"input": json.dumps(self._tool_input)}}}}
      yield {"contentBlockStop": {}}
      yield {"messageStop": {"stopReason": "tool_use"}}
  ```
  Empirically confirmed: after an interrupt raised from within that tool
  call is resumed, Strands calls `stream()` again (the post-resume
  continuation) — a model that unconditionally re-emits the same tool_use
  event on every call re-triggers the interrupt and loops forever.
  `ScriptedToolCallModel` guards this with a call counter: first call
  triggers the tool, every call after that ends the turn with plain text.
- The interrupt `id` Strands assigns
  (`v1:tool_call:<toolUseId>:<uuid>`) embeds whatever `toolUseId` the model
  streamed — confirmed by observation that using a fixed `toolUseId` (not
  a random one) makes the whole interrupt id deterministic across runs,
  though `agents/escalation.py` doesn't rely on that determinism (it always
  reads the id fresh off the live `result.interrupts[0].id`).

- **Token usage.** `result.metrics.accumulated_usage` on the `AgentResult`
  (an `EventLoopMetrics`) carries token counts (e.g. `totalTokens`,
  `inputTokens`, `outputTokens`). Captured per verifier call and cached
  alongside the structured output (`{"output": ..., "usage": ...}`) so
  replay mode reports the *actual* historical token cost, not zero —
  requirement extraction's cache shape (`_run_structured` in
  `requirement_extractor.py`) is left as-is from phase 4 to avoid
  re-recording/breaking its 14 passing tests; `AuditResult.token_usage`
  therefore covers the per-student verification cost, which is the
  meaningful marginal number anyway (one scheme's requirements are
  extracted once and shared across every student of that scheme).

- **Bedrock.** `from strands.models import BedrockModel`. Constructor:
  `BedrockModel(model_id=..., region_name=..., temperature=..., top_p=...)`.
  Region resolution priority: explicit `region_name` param, then boto3
  session config, then env vars. Used in `model_provider.py`'s `bedrock`
  branch, imported only inside that branch (never at module load, so
  `pytest` collection never touches boto3/AWS). Not called anywhere yet —
  no credentials exist for this project.

## Not yet confirmed — check before using

- [ ] The hook system beyond interrupts (`HookProvider`, which events exist
      besides `BeforeToolCallEvent`/`BeforeNodeCallEvent`) — only fetched
      as much as phase 6's escalation needs so far.
- [ ] Full `strands-agents-tools` built-in `workflow` tool (action-based:
      create/start/status/pause/resume) — not used; Kagaz's own plain-code
      Workflow is simpler and sufficient, but worth knowing it exists.

Re-check anything above against strandsagents.com if behavior in a later
phase doesn't match what's documented here — don't build past this point
from memory alone.
