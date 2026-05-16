"""One-shot backfill — fetch 30 days of events on first boot.

Idempotent and resumable: marked complete in `meta` collection. Re-runs only
if (a) the meta flag is missing or (b) USGS_BACKFILL_ON_BOOT is true AND we
explicitly want to refresh.
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
    is_backfill_complete,
    mark_backfill,
    quarantine_features,
    record_health,
    upsert_features,
)

log = get_logger(__name__)


async def run_backfill(
    *,
    usgs: USGSClient,
    mongo: MongoClient,
    force: bool = False,
) -> bool:
    """Run the one-shot backfill if needed. Returns True if backfill executed.

    Concurrency: the backfill writes to the same `events` collection as the
    poller via the same upsert path (`repo.upsert_features`). Mongo's per-doc
    upsert is atomic, so even if the 60s poller fires mid-backfill, no event
    gets corrupted. The poller may briefly see partial state (e.g. only the
    last day loaded), which is fine — every subsequent poll fills the rest in.
    """
    if not force and await is_backfill_complete(mongo):
        log.info("ingestion.backfill.skipped", reason="already_complete")
        return False

    log.info("ingestion.backfill.starting")
    await mark_backfill(mongo, status="running")
    started = time.perf_counter()
    try:
        with USGS_POLL_LATENCY.labels("month").time():
            result = await usgs.fetch_month()
    except UpstreamError as exc:
        log.warning("ingestion.backfill.upstream_error", error=str(exc))
        await mark_backfill(mongo, status="failed", error=str(exc))
        await record_health(
            mongo,
            feed="month",
            status="error",
            latency_ms=round((time.perf_counter() - started) * 1000),
            error_class=type(exc).__name__,
            error_message=str(exc),
        )
        USGS_POLL_RESULT.labels("month", "error").inc()
        return False

    now = datetime.now(UTC)
    outcome = await upsert_features(get_events_collection(mongo), result.features, now=now)
    quarantined = await quarantine_features(
        get_quarantine_collection(mongo),
        result.quarantined,
        feed="month",
        now=now,
    )
    latency_ms = round((time.perf_counter() - started) * 1000)

    EVENTS_INGESTED.labels("new").inc(outcome.new)
    EVENTS_INGESTED.labels("updated").inc(outcome.updated)
    EVENTS_INGESTED.labels("quarantined").inc(quarantined)
    USGS_POLL_RESULT.labels("month", "ok").inc()

    await record_health(
        mongo,
        feed="month",
        status="ok",
        latency_ms=latency_ms,
        new=outcome.new,
        updated=outcome.updated,
        quarantined=quarantined,
        http_status=result.http_status,
        now=now,
    )
    await mark_backfill(mongo, status="complete", events_loaded=outcome.total)
    log.info(
        "ingestion.backfill.complete",
        new=outcome.new,
        updated=outcome.updated,
        unchanged=outcome.unchanged,
        quarantined=quarantined,
        latency_ms=latency_ms,
    )
    return True
