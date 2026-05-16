"""Redis client (async). Used by arq queue + ad-hoc rate-limiting / dedup."""

from __future__ import annotations

from typing import TYPE_CHECKING

from redis.asyncio import Redis, from_url

from .logging import get_logger

if TYPE_CHECKING:
    from .config import BaseAppSettings

log = get_logger(__name__)


class RedisClient:
    """Wraps a redis.asyncio client with a ping helper for readiness checks."""

    def __init__(self, settings: BaseAppSettings) -> None:
        self._redis: Redis = from_url(
            settings.redis_url,
            encoding="utf-8",
            decode_responses=True,
        )

    @property
    def redis(self) -> Redis:
        return self._redis

    async def ping(self) -> bool:
        try:
            return bool(await self._redis.ping())
        except Exception as exc:
            log.warning("redis.ping.failed", error=str(exc))
            return False

    async def close(self) -> None:
        await self._redis.aclose()
