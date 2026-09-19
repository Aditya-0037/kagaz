"""Single factory for every model instance in this repo.

Nothing outside this module instantiates a model. Which provider is used is
selected entirely by the KAGAZ_MODEL_PROVIDER environment variable, so
swapping providers never touches agent code.

"vertex" (Google Cloud Vertex AI, via Gemini) is the default and primary
provider. "ollama" stays fully wired as the offline/local dev fallback —
free, no credentials, no network dependency on Google Cloud. "bedrock" was
the original provider during early development; the project has since
moved to Vertex AI, so it now raises NotImplementedError pointing at that.
No AWS SDK is imported anywhere in this repo.

Confirmed against strandsagents.com (see docs/sdk-notes.md):
ollama — 2026-09-03, https://strandsagents.com/docs/user-guide/concepts/model-providers/ollama/
gemini/vertex — 2026-09-19, https://strandsagents.com/docs/user-guide/concepts/model-providers/google/
strands-agents==1.54.0 (see requirements.txt for the exact pin at the time
of the Vertex migration).
"""

from __future__ import annotations

import json
import os
from typing import Any

from strands.models import Model

DEFAULT_OLLAMA_HOST = "http://localhost:11434"
DEFAULT_OLLAMA_MODEL_ID = "llama3.1:8b"

DEFAULT_VERTEX_LOCATION = "us-central1"
DEFAULT_VERTEX_MODEL_ID = "gemini-2.5-flash"


def get_model(
    provider: str | None = None,
    *,
    model_id: str | None = None,
    host: str | None = None,
) -> Model:
    """Return a configured Strands `Model` for the selected provider.

    provider defaults to the KAGAZ_MODEL_PROVIDER env var (falling back to
    "vertex"). Constructing the model does not make a network call — that
    only happens when an Agent actually invokes it.
    """
    provider = provider or os.environ.get("KAGAZ_MODEL_PROVIDER", "vertex")

    if provider == "ollama":
        from strands.models.ollama import OllamaModel

        return OllamaModel(
            host=host or os.environ.get("KAGAZ_OLLAMA_HOST", DEFAULT_OLLAMA_HOST),
            model_id=model_id or os.environ.get("KAGAZ_OLLAMA_MODEL_ID", DEFAULT_OLLAMA_MODEL_ID),
        )

    if provider == "vertex":
        # Imported here, not at module scope, so pytest collection (and
        # every other provider's code path) never requires google-genai to
        # be importable.
        from strands.models.gemini import GeminiModel

        return GeminiModel(
            client_args={
                "vertexai": True,
                "project": os.environ.get("GOOGLE_CLOUD_PROJECT"),
                "location": os.environ.get("GOOGLE_CLOUD_LOCATION", DEFAULT_VERTEX_LOCATION),
            },
            model_id=model_id or os.environ.get("KAGAZ_VERTEX_MODEL_ID", DEFAULT_VERTEX_MODEL_ID),
        )

    if provider == "anthropic":
        raise NotImplementedError(
            "KAGAZ_MODEL_PROVIDER=anthropic is not wired up yet. "
            "Set KAGAZ_MODEL_PROVIDER=vertex or 'ollama' for local development."
        )

    if provider == "bedrock":
        raise NotImplementedError(
            "KAGAZ_MODEL_PROVIDER=bedrock is no longer used — this project moved to "
            "Google Cloud Vertex AI (see docs/vertex-setup.md). Set "
            "KAGAZ_MODEL_PROVIDER=vertex, or 'ollama' for local development."
        )

    raise ValueError(f"Unknown KAGAZ_MODEL_PROVIDER: {provider!r}")


def get_model_identifier(provider: str | None = None, *, model_id: str | None = None) -> str:
    """A cache-friendly (provider, model) identifier pair's model half —
    e.g. "llama3.1:8b" for ollama, "gemini-2.5-flash" for vertex. Used by
    llm_cache keys; instantiates nothing, so it's safe to call even for a
    NotImplementedError provider.
    """
    provider = provider or os.environ.get("KAGAZ_MODEL_PROVIDER", "vertex")
    if provider == "ollama":
        return model_id or os.environ.get("KAGAZ_OLLAMA_MODEL_ID", DEFAULT_OLLAMA_MODEL_ID)
    if provider == "vertex":
        return model_id or os.environ.get("KAGAZ_VERTEX_MODEL_ID", DEFAULT_VERTEX_MODEL_ID)
    return provider


class ScriptedToolCallModel(Model):
    """A `Model` that always calls one specific tool with fixed input,
    with zero network I/O — for agents/escalation.py.

    This is deliberately NOT selected via KAGAZ_MODEL_PROVIDER: it isn't a
    model backend a user would choose, it's a stand-in for cases where
    Python already knows the answer and asking a real LLM to "decide"
    would be theater. Escalating a Finding.needs_human is exactly that:
    the coordinator already knows a human review is needed and which tool
    (`escalate`) to invoke — the only genuine unknown is the human's
    decision, which arrives via the interrupt's resume value, not from
    model inference. Confirmed against
    https://strandsagents.com/docs/user-guide/concepts/model-providers/custom_model_provider/
    and https://strandsagents.com/docs/api/python/strands.models.model/
    on 2026-09-04 (see docs/sdk-notes.md) for Model's abstract interface
    (stream, structured_output, update_config, get_config) and verified
    empirically that the resulting interrupt/resume cycle is genuinely the
    SDK's real mechanism, not an approximation.
    """

    def __init__(self, tool_name: str, tool_input: dict[str, Any] | None = None):
        self._tool_name = tool_name
        self._tool_input = tool_input or {}
        self.config: dict[str, Any] = {}
        self._call_count = 0

    async def stream(self, messages, tool_specs=None, system_prompt=None, **kwargs):
        # First call: trigger the tool (and, via it, the interrupt). Every
        # call after that (i.e. the post-resume continuation, once the
        # tool has returned the human's decision) just ends the turn —
        # calling the tool again here would re-trigger the interrupt and
        # loop forever.
        self._call_count += 1
        if self._call_count == 1:
            yield {"messageStart": {"role": "assistant"}}
            yield {
                "contentBlockStart": {
                    "start": {"toolUse": {"name": self._tool_name, "toolUseId": f"scripted-{self._tool_name}"}}
                }
            }
            yield {"contentBlockDelta": {"delta": {"toolUse": {"input": json.dumps(self._tool_input)}}}}
            yield {"contentBlockStop": {}}
            yield {"messageStop": {"stopReason": "tool_use"}}
        else:
            yield {"messageStart": {"role": "assistant"}}
            yield {"contentBlockStart": {"start": {}}}
            yield {"contentBlockDelta": {"delta": {"text": "Acknowledged."}}}
            yield {"contentBlockStop": {}}
            yield {"messageStop": {"stopReason": "end_turn"}}

    async def structured_output(self, output_model, prompt, system_prompt=None, **kwargs):
        raise NotImplementedError("ScriptedToolCallModel does not support structured_output")
        yield  # pragma: no cover - makes this an async generator per Model's interface

    def update_config(self, **config: Any) -> None:
        self.config.update(config)

    def get_config(self) -> Any:
        return self.config


def get_scripted_tool_call_model(tool_name: str, tool_input: dict[str, Any] | None = None) -> Model:
    """A deterministic, network-free Model that always calls `tool_name`.
    See ScriptedToolCallModel's docstring for why this exists."""
    return ScriptedToolCallModel(tool_name, tool_input)
