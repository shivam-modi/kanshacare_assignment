"""Nominatim (OpenStreetMap) geocoder.

Free, no API key, but the usage policy is strict:
* identifying User-Agent (REQUIRED)
* max 1 request/second
* avoid bulk geocoding
"""

from __future__ import annotations

import asyncio
import time
from typing import Any

import httpx

from ..errors import UpstreamError
from ..logging import get_logger
from ..models import GeocodeResult
from ..retry import RetryError, upstream_retry
from .base import GeocodeQuery

log = get_logger(__name__)

_NOMINATIM_BASE = "https://nominatim.openstreetmap.org"


class NominatimGeocoder:
    provider_name = "nominatim"

    def __init__(
        self,
        *,
        user_agent: str,
        rate_limit_per_sec: float = 1.0,
        timeout_seconds: float = 10.0,
    ) -> None:
        if not user_agent or "example" in user_agent.lower():
            # Nominatim will ban a generic UA; force callers to set something specific.
            log.warning(
                "nominatim.user_agent.generic",
                advice="set GEOCODER_USER_AGENT to identify your deployment",
            )
        self._client = httpx.AsyncClient(
            base_url=_NOMINATIM_BASE,
            timeout=httpx.Timeout(timeout_seconds, connect=5.0),
            headers={"User-Agent": user_agent, "Accept-Language": "en"},
        )
        self._min_interval = 1.0 / max(rate_limit_per_sec, 0.1)
        self._last_call_monotonic: float = 0.0
        self._lock = asyncio.Lock()

    async def aclose(self) -> None:
        await self._client.aclose()

    async def forward(self, query: GeocodeQuery) -> GeocodeResult | None:
        params: dict[str, Any] = {
            "q": query.text,
            "format": "jsonv2",
            "limit": str(query.limit),
            "addressdetails": "1",
        }
        if query.country_codes:
            params["countrycodes"] = ",".join(query.country_codes)
        items = await self._call("/search", params)
        if not items:
            return None
        return self._to_result(query.text, items[0])

    async def reverse(self, lat: float, lon: float) -> GeocodeResult | None:
        params = {
            "lat": str(lat),
            "lon": str(lon),
            "format": "jsonv2",
            "addressdetails": "1",
        }
        item = await self._call("/reverse", params)
        if not item or not isinstance(item, dict):
            return None
        return self._to_result(f"{lat},{lon}", item)

    async def _call(self, path: str, params: dict[str, Any]) -> Any:
        await self._respect_rate_limit()
        try:
            async for attempt in upstream_retry(attempts=2, max_wait=4.0):
                with attempt:
                    resp = await self._client.get(path, params=params)
        except RetryError as exc:
            raise UpstreamError("Nominatim unreachable") from exc

        if resp.status_code == 429:
            raise UpstreamError("Nominatim rate-limited us (429)")
        if resp.status_code >= 500:
            raise UpstreamError(f"Nominatim {resp.status_code}")
        resp.raise_for_status()
        return resp.json()

    async def _respect_rate_limit(self) -> None:
        async with self._lock:
            elapsed = time.monotonic() - self._last_call_monotonic
            if elapsed < self._min_interval:
                await asyncio.sleep(self._min_interval - elapsed)
            self._last_call_monotonic = time.monotonic()

    @staticmethod
    def _to_result(query: str, item: dict[str, Any]) -> GeocodeResult:
        address = item.get("address", {}) or {}
        return GeocodeResult(
            query=query,
            name=item.get("display_name", query),
            lat=float(item["lat"]),
            lon=float(item["lon"]),
            country=address.get("country"),
            country_code=(address.get("country_code") or "").upper() or None,
            provider="nominatim",
        )
