"""USGS feed client with retries, conditional GET, and parse-error quarantine.

Treats the feed itself like a device: if it's slow, retry once with backoff; if
it returns 5xx, surface UpstreamError; if it returns malformed JSON or a feature
fails schema validation, isolate the bad feature without dropping the rest.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

import httpx
import orjson
from pydantic import ValidationError as PydanticValidationError

from .errors import UpstreamError
from .logging import get_logger
from .models import USGSFeature, USGSFeatureCollection
from .retry import RetryError, upstream_retry

log = get_logger(__name__)

_DEFAULT_HEADERS = {
    "Accept": "application/geo+json, application/json;q=0.9",
    "User-Agent": "kanshacare-ingestion/0.1 (+https://kanshacare.example)",
}


@dataclass(slots=True)
class FeedFetchResult:
    """Outcome of one feed fetch — what the caller logs into system_health."""

    feed: str
    features: list[USGSFeature]
    quarantined: list[dict[str, Any]] = field(default_factory=list)
    http_status: int = 200
    not_modified: bool = False
    raw_metadata: dict[str, Any] = field(default_factory=dict)


class USGSClient:
    """Thin async client around the USGS GeoJSON feeds.

    Use as an async context manager so the underlying httpx client is closed on shutdown.
    """

    def __init__(
        self,
        *,
        hour_url: str,
        month_url: str,
        timeout_seconds: float = 10.0,
    ) -> None:
        self._hour_url = hour_url
        self._month_url = month_url
        self._client = httpx.AsyncClient(
            timeout=httpx.Timeout(timeout_seconds, connect=5.0),
            headers=_DEFAULT_HEADERS,
            follow_redirects=True,
        )
        # ETag cache for conditional GET — avoids parsing identical payloads.
        self._etag: dict[str, str] = {}

    async def __aenter__(self) -> USGSClient:
        return self

    async def __aexit__(self, *_: object) -> None:
        await self.aclose()

    async def aclose(self) -> None:
        await self._client.aclose()

    async def fetch_hour(self) -> FeedFetchResult:
        return await self._fetch(self._hour_url, feed="hour")

    async def fetch_month(self) -> FeedFetchResult:
        return await self._fetch(self._month_url, feed="month")

    async def _fetch(self, url: str, *, feed: str) -> FeedFetchResult:
        headers: dict[str, str] = {}
        if (etag := self._etag.get(url)) is not None:
            headers["If-None-Match"] = etag

        try:
            async for attempt in upstream_retry(attempts=3, max_wait=4.0):
                with attempt:
                    resp = await self._client.get(url, headers=headers)
        except RetryError as exc:
            log.warning("usgs.fetch.retries_exhausted", feed=feed, error=str(exc))
            raise UpstreamError(f"USGS {feed} feed unreachable after retries") from exc

        if resp.status_code == 304:
            return FeedFetchResult(feed=feed, features=[], http_status=304, not_modified=True)

        if resp.status_code >= 500:
            raise UpstreamError(f"USGS {feed} feed returned {resp.status_code}")
        if resp.status_code >= 400:
            # 4xx means we're asking wrong (auth, URL); retrying won't help.
            raise UpstreamError(f"USGS {feed} feed rejected request: {resp.status_code}")

        if (new_etag := resp.headers.get("ETag")) is not None:
            self._etag[url] = new_etag

        try:
            payload = orjson.loads(resp.content)
        except orjson.JSONDecodeError as exc:
            raise UpstreamError(f"USGS {feed} feed returned invalid JSON") from exc

        return _parse_features(feed, payload, http_status=resp.status_code)


def _parse_features(feed: str, payload: dict[str, Any], *, http_status: int) -> FeedFetchResult:
    """Validate the FeatureCollection, isolating bad features rather than dropping all."""
    raw_features = payload.get("features", [])
    metadata = payload.get("metadata", {})

    # First try the strict path — if everything validates we're done.
    try:
        fc = USGSFeatureCollection.model_validate(payload)
        return FeedFetchResult(
            feed=feed,
            features=fc.features,
            http_status=http_status,
            raw_metadata=metadata,
        )
    except PydanticValidationError:
        # Fall through to per-feature validation. Some feeds occasionally contain
        # an event with a malformed property; one bad apple shouldn't spoil the batch.
        pass

    good: list[USGSFeature] = []
    bad: list[dict[str, Any]] = []
    for raw in raw_features:
        try:
            good.append(USGSFeature.model_validate(raw))
        except PydanticValidationError as exc:
            log.warning(
                "usgs.feature.invalid",
                feed=feed,
                feature_id=raw.get("id"),
                error=str(exc),
            )
            bad.append({"raw": raw, "error": str(exc)})

    return FeedFetchResult(
        feed=feed,
        features=good,
        quarantined=bad,
        http_status=http_status,
        raw_metadata=metadata,
    )
