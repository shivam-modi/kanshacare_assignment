"""Token bucket sanity."""

from __future__ import annotations

import asyncio
import time

import pytest

from worker_app.rate_limit import TelegramLimiter, TokenBucket


@pytest.mark.asyncio
async def test_token_bucket_allows_burst_up_to_capacity() -> None:
    bucket = TokenBucket(capacity=5, refill_per_second=1)
    start = time.perf_counter()
    for _ in range(5):
        await bucket.acquire()
    elapsed = time.perf_counter() - start
    # Five acquires within capacity should be near-instant.
    assert elapsed < 0.1


@pytest.mark.asyncio
async def test_token_bucket_throttles_when_empty() -> None:
    bucket = TokenBucket(capacity=2, refill_per_second=10)  # 100ms per token
    # Drain.
    await bucket.acquire()
    await bucket.acquire()
    start = time.perf_counter()
    await bucket.acquire()  # forced wait ~100ms
    elapsed = time.perf_counter() - start
    assert 0.05 < elapsed < 0.5


@pytest.mark.asyncio
async def test_telegram_limiter_per_chat_independent() -> None:
    limiter = TelegramLimiter()
    # Two different chats should not block each other (small burst).
    await asyncio.gather(*(limiter.acquire(1) for _ in range(1)))
    await asyncio.gather(*(limiter.acquire(2) for _ in range(1)))
