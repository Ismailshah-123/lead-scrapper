"""
Rate limiting and retry/backoff, shared by every connector.

Spec section 27 ("Rate Limiting") requires: configurable delay, request
throttling, retry limits, exponential backoff, timeout, error handling,
logging. This module provides the first four as small, composable pieces;
timeout is passed to `requests` by each connector; error handling/logging
is each connector's own try/except around calls wrapped with these.
"""
from __future__ import annotations

import threading
import time

from tenacity import (
    retry,
    retry_if_exception_type,
    stop_after_attempt,
    wait_exponential,
)

from app.core.config import get_secrets
from app.core.logging_config import get_logger

logger = get_logger("rate_limiter")


class DelayLimiter:
    """A conservative, process-wide minimum delay between outbound
    requests. Not a token bucket — deliberately simple, since the spec
    asks for "never hammer websites" defaults, not maximum throughput."""

    def __init__(self, delay_seconds: float | None = None) -> None:
        self._delay = delay_seconds if delay_seconds is not None else get_secrets().request_delay_seconds
        self._lock = threading.Lock()
        self._last_call_at: float = 0.0

    def wait(self) -> None:
        with self._lock:
            elapsed = time.monotonic() - self._last_call_at
            remaining = self._delay - elapsed
            if remaining > 0:
                time.sleep(remaining)
            self._last_call_at = time.monotonic()


# A single shared limiter is intentional: connectors run in the same
# process during a pipeline run, and the "never hammer" guarantee should
# hold across all of them combined, not per-connector.
default_limiter = DelayLimiter()


def with_retry(exception_types: tuple[type[BaseException], ...] = (Exception,)):
    """Decorator factory: retry with exponential backoff up to
    `MAX_RETRIES` attempts (from .env), only for the given exception
    types. Re-raises the last exception if every attempt fails, so callers
    can log-and-continue at the connector level (spec section 29)."""

    return retry(
        reraise=True,
        stop=stop_after_attempt(max(1, get_secrets().max_retries)),
        wait=wait_exponential(multiplier=1, min=1, max=15),
        retry=retry_if_exception_type(exception_types),
    )
