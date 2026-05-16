"""Simple token-bucket rate limiter for Telegram sends.

Telegram limits:
  * 30 messages/second globally per bot
  * 1 message/second per chat (after the first burst)

We model them as two buckets — global and per-chat — both acquired before each send.
"""

from __future__ import annotations

import asyncio
import time
from dataclasses import dataclass


@dataclass(slots=True)
class TokenBucket:
    capacity: float
    refill_per_second: float
    _tokens: float = 0
    _last_refill: float = 0
    _lock: asyncio.Lock | None = None

    def __post_init__(self) -> None:
        self._tokens = self.capacity
        self._last_refill = time.monotonic()
        self._lock = asyncio.Lock()

    async def acquire(self, n: float = 1.0) -> None:
        assert self._lock is not None
        async with self._lock:
            while True:
                now = time.monotonic()
                elapsed = now - self._last_refill
                self._tokens = min(self.capacity, self._tokens + elapsed * self.refill_per_second)
                self._last_refill = now
                if self._tokens >= n:
                    self._tokens -= n
                    return
                # Wait just long enough for the next n tokens.
                need = n - self._tokens
                wait = need / self.refill_per_second
                await asyncio.sleep(wait)


class TelegramLimiter:
    def __init__(self) -> None:
        self.global_bucket = TokenBucket(capacity=30, refill_per_second=30)
        self._per_chat: dict[int, TokenBucket] = {}

    def _chat_bucket(self, chat_id: int) -> TokenBucket:
        bucket = self._per_chat.get(chat_id)
        if bucket is None:
            bucket = TokenBucket(capacity=1, refill_per_second=1)
            self._per_chat[chat_id] = bucket
        return bucket

    async def acquire(self, chat_id: int) -> None:
        await self.global_bucket.acquire()
        await self._chat_bucket(chat_id).acquire()
