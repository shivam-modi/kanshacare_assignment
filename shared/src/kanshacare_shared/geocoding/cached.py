"""Mongo-backed cache wrapper. Provider-agnostic — cache layer is unchanged
when we swap Nominatim for LocationIQ tomorrow."""

from __future__ import annotations

import hashlib
from datetime import UTC, datetime
from typing import Any

from ..db import COLL_GEOCODE_CACHE, MongoClient
from ..logging import get_logger
from ..models import GeocodeResult
from .base import GeocodeQuery, Geocoder

log = get_logger(__name__)


def _cache_key(provider: str, kind: str, value: str) -> str:
    """Stable hash so we can dedup variations like 'Tokyo' vs ' Tokyo '."""
    normalized = f"{provider}::{kind}::{value.strip().casefold()}"
    return hashlib.sha1(normalized.encode("utf-8")).hexdigest()


class CachedGeocoder:
    """Decorator that caches results in Mongo for `cache_ttl_days` (TTL index)."""

    def __init__(self, inner: Geocoder, mongo: MongoClient) -> None:
        self._inner = inner
        self._coll = mongo.collection(COLL_GEOCODE_CACHE)

    @property
    def provider_name(self) -> str:
        return self._inner.provider_name

    async def forward(self, query: GeocodeQuery) -> GeocodeResult | None:
        key = _cache_key(self._inner.provider_name, "forward", query.text)
        if cached := await self._read(key):
            return cached
        result = await self._inner.forward(query)
        if result is not None:
            await self._write(key, query.text, "forward", result)
        return result

    async def reverse(self, lat: float, lon: float) -> GeocodeResult | None:
        key = _cache_key(self._inner.provider_name, "reverse", f"{lat:.5f},{lon:.5f}")
        if cached := await self._read(key):
            return cached
        result = await self._inner.reverse(lat, lon)
        if result is not None:
            await self._write(key, f"{lat:.5f},{lon:.5f}", "reverse", result)
        return result

    async def aclose(self) -> None:
        await self._inner.aclose()

    async def _read(self, key: str) -> GeocodeResult | None:
        doc = await self._coll.find_one({"_id": key})
        if doc is None:
            return None
        try:
            return GeocodeResult.model_validate(doc["result"])
        except Exception as exc:
            log.warning("geocode.cache.bad_doc", key=key, error=str(exc))
            return None

    async def _write(self, key: str, query: str, kind: str, result: GeocodeResult) -> None:
        doc: dict[str, Any] = {
            "_id": key,
            "provider": self._inner.provider_name,
            "kind": kind,
            "query": query,
            "result": result.model_dump(),
            "cached_at": datetime.now(UTC),
        }
        await self._coll.replace_one({"_id": key}, doc, upsert=True)
