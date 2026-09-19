"""Record/replay cache for model calls.

Every agent's model calls go through `cached_call`. The point is that
`pytest` (and CI) never needs network access or API keys: set
KAGAZ_LLM_MODE=replay (the default) and every call is served from
fixtures/llm_cache/, or raises LLMCacheMiss (naming the exact missing key)
if nothing was ever recorded — replay mode never touches the network.

Modes (KAGAZ_LLM_MODE):
  replay (default) - read-only. Cache hit returns the stored response.
                      Cache miss raises LLMCacheMiss; call_fn is never
                      invoked, so hand-author the fixture and re-run.
  record            - always invokes call_fn and overwrites the cache entry
                      with the fresh response ("record refreshes").
  live              - always invokes call_fn and never touches the cache.
                      Useful for ad hoc manual testing against a real model.
"""

from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
from typing import Any, Callable

DEFAULT_CACHE_DIR = Path(__file__).parent / "fixtures" / "llm_cache"


class LLMCacheMiss(Exception):
    """Raised in replay mode when no recorded response exists for a call.

    This means the fixture set is incomplete, not that the network is down
    — replay mode never attempts a network call.
    """


def hash_key(
    provider: str,
    model: str,
    prompt: str,
    inputs: dict[str, Any] | None = None,
) -> str:
    """Deterministic key for a model call, independent of dict key order."""
    payload = json.dumps(
        {"provider": provider, "model": model, "prompt": prompt, "inputs": inputs or {}},
        sort_keys=True,
        default=str,
    )
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()[:24]


def _entry_path(key: str, cache_dir: Path) -> Path:
    return cache_dir / f"{key}.json"


def load(key: str, cache_dir: Path = DEFAULT_CACHE_DIR) -> Any | None:
    path = _entry_path(key, cache_dir)
    if not path.exists():
        return None
    with path.open("r", encoding="utf-8") as f:
        return json.load(f)["response"]


def save(
    key: str,
    provider: str,
    model: str,
    prompt: str,
    inputs: dict[str, Any] | None,
    response: Any,
    cache_dir: Path = DEFAULT_CACHE_DIR,
) -> None:
    cache_dir.mkdir(parents=True, exist_ok=True)
    path = _entry_path(key, cache_dir)
    with path.open("w", encoding="utf-8") as f:
        json.dump(
            {
                "provider": provider,
                "model": model,
                "prompt": prompt,
                "inputs": inputs or {},
                "response": response,
            },
            f,
            indent=2,
            sort_keys=True,
        )


def cached_call(
    provider: str,
    model: str,
    prompt: str,
    inputs: dict[str, Any] | None,
    call_fn: Callable[[], Any],
    *,
    mode: str | None = None,
    cache_dir: Path = DEFAULT_CACHE_DIR,
) -> Any:
    """Route a model call through the record/replay cache.

    `call_fn` takes no arguments — callers close over whatever they need to
    actually invoke the model. It is never invoked in replay mode.
    """
    mode = mode or os.environ.get("KAGAZ_LLM_MODE", "replay")
    if mode not in {"replay", "record", "live"}:
        raise ValueError(f"Unknown KAGAZ_LLM_MODE: {mode!r}")

    if mode == "live":
        return call_fn()

    key = hash_key(provider, model, prompt, inputs)

    if mode == "replay":
        cached = load(key, cache_dir)
        if cached is None:
            raise LLMCacheMiss(
                f"No recorded response for key {key!r} "
                f"(provider={provider!r}, model={model!r}, prompt={prompt[:80]!r}...). "
                f"Run with KAGAZ_LLM_MODE=record to create fixtures/llm_cache/{key}.json."
            )
        return cached

    # mode == "record"
    response = call_fn()
    save(key, provider, model, prompt, inputs, response, cache_dir)
    return response
