"""One poll cycle = fetch all_hour.geojson → upsert → log to system_health.

Pure orchestration; all DB writes go through `repo`, all HTTP through USGSClient.
"""

from __future__ import annotations

import time
from datetime import UTC, datetime

from kanshacare_shared.db import MongoClient
from kanshacare_shared.errors import UpstreamError
from kanshacare_shared.logging import get_logger
from kanshacare_shared.metrics import EVENTS_INGESTED, USGS_POLL_LATENCY, USGS_POLL_RESULT
from kanshacare_shared.usgs import USGSClient

from .repo import (
    get_events_collection,
    get_quarantine_collection,
    quarantine_features,
    record_health,
    upsert_features,
)

log = get_logger(__name__)


async def run_poll_cycle(
    *,
    usgs: USGSClient,
    mongo: MongoClient,
    feed: str = "hour",
) -> None:
    """One full poll cycle. Designed to be called by the scheduler every 60s.

    Never raises — every failure mode lands in `system_health` so the dashboard
    sees the truth. Letting it raise would crash the scheduler and silence the
    feed (and we'd miss the system-silence alert until the alerts service noticed).
    """
    started = time.perf_counter()
    fetch = usgs.fetch_hour if feed == "hour" else usgs.fetch_month
    try:
        with USGS_POLL_LATENCY.labels(feed).time():
            result = await fetch()
    except UpstreamError as exc:
        latency_ms = round((time.perf_counter() - started) * 1000)
        log.warning("ingestion.poll.upstream_error", feed=feed, error=str(exc))
        USGS_POLL_RESULT.labels(feed, "error").inc()
        await record_health(
            mongo,
            feed=feed,
            status="error",
            latency_ms=latency_ms,
            error_class=type(exc).__name__,
            error_message=str(exc),
        )
        return
    except Exception as exc:
        latency_ms = round((time.perf_counter() - started) * 1000)
        log.exception("ingestion.poll.unexpected_error", feed=feed)
        USGS_POLL_RESULT.labels(feed, "error").inc()
        await record_health(
            mongo,
            feed=feed,
            status="error",
            latency_ms=latency_ms,
            error_class=type(exc).__name__,
            error_message=str(exc),
        )
        return

    now = datetime.now(UTC)
    latency_ms = round((time.perf_counter() - started) * 1000)

    if result.not_modified:
        # USGS hasn't published anything new since our last poll — still healthy.
        USGS_POLL_RESULT.labels(feed, "not_modified").inc()
        await record_health(
            mongo,
            feed=feed,
            status="ok",
            latency_ms=latency_ms,
            http_status=304,
            now=now,
        )
        return

    outcome = await upsert_features(get_events_collection(mongo), result.features, now=now)
    quarantined = await quarantine_features(
        get_quarantine_collection(mongo),
        result.quarantined,
        feed=feed,
        now=now,
    )

    EVENTS_INGESTED.labels("new").inc(outcome.new)
    EVENTS_INGESTED.labels("updated").inc(outcome.updated)
    EVENTS_INGESTED.labels("quarantined").inc(quarantined)
    USGS_POLL_RESULT.labels(feed, "ok").inc()

    await record_health(
        mongo,
        feed=feed,
        status="ok",
        latency_ms=latency_ms,
        new=outcome.new,
        updated=outcome.updated,
        quarantined=quarantined,
        http_status=result.http_status,
        now=now,
    )

    log.info(
        "ingestion.poll.ok",
        feed=feed,
        latency_ms=latency_ms,
        new=outcome.new,
        updated=outcome.updated,
        unchanged=outcome.unchanged,
        quarantined=quarantined,
    )
