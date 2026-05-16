"""Reusable tenacity retry policies.

Centralised so every upstream dependency has the same retry shape (and so we can
swap to a different backoff strategy globally if needed).
"""

from __future__ import annotations

import httpx
from tenacity import (
    AsyncRetrying,
    RetryError,
    retry_if_exception_type,
    stop_after_attempt,
    wait_random_exponential,
)

__all__ = ["RetryError", "upstream_retry"]

# Retry on connection-level / transient HTTP issues. Application-level errors
# (4xx, validation failures) should NOT be retried — the caller raises a domain
# error instead.
_RETRYABLE: tuple[type[BaseException], ...] = (
    httpx.ConnectError,
    httpx.ReadTimeout,
    httpx.ConnectTimeout,
    httpx.PoolTimeout,
    httpx.RemoteProtocolError,
)


def upstream_retry(*, attempts: int = 3, max_wait: float = 8.0) -> AsyncRetrying:
    """Exponential backoff with jitter. 3 attempts by default, max 8s wait."""
    return AsyncRetrying(
        retry=retry_if_exception_type(_RETRYABLE),
        wait=wait_random_exponential(multiplier=0.5, max=max_wait),
        stop=stop_after_attempt(attempts),
        reraise=True,
    )
