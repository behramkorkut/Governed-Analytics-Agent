"""Sliding-window rate limiting, per client IP — protects billed LLM calls.

Each `/ask` API call and each dashboard chat question can trigger several
Anthropic requests, so an unauthenticated exposure needs a hard daily budget.
Same pattern as readmission-risk-ml: beyond `settings.rate_limit_per_day`
calls in a rolling 24 h window, the caller gets 429 + `Retry-After` (API) or
a friendly notice (dashboard). In-memory by design: one process, no external
service — adequate for a single-instance deployment.
"""

from __future__ import annotations

import threading
import time
from collections import deque

WINDOW_S = 24 * 3600  # one day, in seconds


class SlidingWindowRateLimiter:
    """Per-key sliding-window counter (thread-safe, in-memory)."""

    def __init__(self) -> None:
        self._hits: dict[str, deque[float]] = {}
        self._lock = threading.Lock()

    def allow(self, key: str, max_calls: int, now: float | None = None) -> tuple[bool, int]:
        """Register one call for `key`. Returns (allowed, retry_after_seconds)."""
        now = time.monotonic() if now is None else now
        with self._lock:
            hits = self._hits.setdefault(key, deque())
            while hits and now - hits[0] >= WINDOW_S:
                hits.popleft()
            if len(hits) >= max_calls:
                return False, int(WINDOW_S - (now - hits[0])) + 1
            hits.append(now)
            return True, 0

    def reset(self) -> None:
        """Test hook: forget every key."""
        with self._lock:
            self._hits.clear()


_limiter = SlidingWindowRateLimiter()


def reset_rate_limiter() -> None:
    _limiter.reset()


def check_rate_limit(key: str, max_calls: int) -> tuple[bool, int]:
    """(allowed, retry_after_s) for one call from `key`; max_calls <= 0 disables."""
    if max_calls <= 0:
        return True, 0
    return _limiter.allow(key, max_calls)
