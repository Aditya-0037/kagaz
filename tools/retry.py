"""Retry helper for transient model-provider failures.

Vertex AI returns 429 RESOURCE_EXHAUSTED when a project's per-minute
quota is hit, and Kagaz hits it easily: the coordinator verifies every
required document in parallel, so one run can fire several Gemini calls
within a second of each other, right after the extraction call.

That is a transient infrastructure condition, not a problem with the
user's document — it must be retried with backoff, and if it still
fails it must be reported as "couldn't reach the model", never as
"your file is unreadable".
"""

from __future__ import annotations

import random
import time
from typing import Callable, TypeVar

T = TypeVar("T")

# Matched against str(exception) — the providers surface these as HTTP
# status codes and gRPC status names inside the message text.
_TRANSIENT_MARKERS = (
    "429",
    "resource_exhausted",
    "resource exhausted",
    "too many requests",
    "rate limit",
    "quota",
    "503",
    "unavailable",
    "deadline_exceeded",
    "deadline exceeded",
    "timeout",
    "internal error",
)


def is_transient(exc: BaseException) -> bool:
    """True when `exc` looks like a rate limit or a temporary provider
    outage rather than a problem with the input."""
    message = str(exc).lower()
    return any(marker in message for marker in _TRANSIENT_MARKERS)


def with_retries(
    call: Callable[[], T],
    *,
    attempts: int = 4,
    base_delay: float = 2.0,
    max_delay: float = 30.0,
) -> T:
    """Call `call`, retrying transient failures with exponential backoff
    and jitter. Non-transient exceptions propagate immediately — a
    corrupt file will not get better on the fourth attempt."""
    last: BaseException | None = None
    for attempt in range(attempts):
        try:
            return call()
        except Exception as exc:  # noqa: BLE001 - re-raised below unless transient
            last = exc
            if not is_transient(exc) or attempt == attempts - 1:
                raise
            delay = min(base_delay * (2**attempt), max_delay)
            time.sleep(delay + random.uniform(0, 0.75))
    raise last  # unreachable; keeps type checkers happy
