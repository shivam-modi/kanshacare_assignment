"""Read-side queries against Mongo. Centralised so endpoints stay thin and
the same logic powers both REST + SSE (and is testable in isolation).
"""

from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator
from datetime import UTC, datetime, timedelta
from typing import Any, Literal

from kanshacare_shared.db import (
    COLL_EVENTS,
    COLL_META,
    COLL_SYSTEM_HEALTH,
    MongoClient,
)
from kanshacare_shared.geo import km_to_radians
from kanshacare_shared.logging import get_logger

log = get_logger(__name__)

TimeWindow = Literal["1h", "24h", "7d", "30d"]

_WINDOW_DELTAS: dict[TimeWindow, timedelta] = {
    "1h": timedelta(hours=1),
    "24h": timedelta(hours=24),
    "7d": timedelta(days=7),
    "30d": timedelta(days=30),
}


def window_to_epoch_ms_floor(window: TimeWindow, *, now: datetime | None = None) -> int:
    """Return the lower bound for `properties.time` (epoch ms) for the given window."""
    now = now or datetime.now(UTC)
    floor = now - _WINDOW_DELTAS[window]
    return int(floor.timestamp() * 1000)


def _build_event_filter(
    *,
    window: TimeWindow | None,
    min_mag: float | None,
    bbox: tuple[float, float, float, float] | None,
) -> dict[str, Any]:
    filt: dict[str, Any] = {}
    if window is not None:
        filt["properties.time"] = {"$gte": window_to_epoch_ms_floor(window)}
    if min_mag is not None:
        filt["properties.mag"] = {"$gte": min_mag}
    if bbox is not None:
        # bbox = (min_lon, min_lat, max_lon, max_lat)
        min_lon, min_lat, max_lon, max_lat = bbox
        filt["geometry"] = {
            "$geoWithin": {
                "$box": [[min_lon, min_lat], [max_lon, max_lat]],
            }
        }
    return filt


async def list_events(
    mongo: MongoClient,
    *,
    window: TimeWindow = "24h",
    min_mag: float | None = None,
    bbox: tuple[float, float, float, float] | None = None,
    limit: int = 500,
) -> list[dict[str, Any]]:
    """List events for the global incident tracker."""
    filt = _build_event_filter(window=window, min_mag=min_mag, bbox=bbox)
    cursor = mongo.collection(COLL_EVENTS).find(filt).sort("properties.time", -1).limit(limit)
    return [doc async for doc in cursor]


async def list_events_near(
    mongo: MongoClient,
    *,
    lat: float,
    lon: float,
    radius_km: float,
    window: TimeWindow = "30d",
    limit: int = 500,
) -> list[dict[str, Any]]:
    """Events within `radius_km` of a point, within the time window."""
    filt = _build_event_filter(window=window, min_mag=None, bbox=None)
    filt["geometry"] = {
        "$geoWithin": {
            "$centerSphere": [[lon, lat], km_to_radians(radius_km)],
        }
    }
    cursor = mongo.collection(COLL_EVENTS).find(filt).sort("properties.time", -1).limit(limit)
    return [doc async for doc in cursor]


async def count_events_near(
    mongo: MongoClient,
    *,
    lat: float,
    lon: float,
    radius_km: float,
    window: TimeWindow,
) -> int:
    """Cheap count for the per-location summary card."""
    filt = _build_event_filter(window=window, min_mag=None, bbox=None)
    filt["geometry"] = {
        "$geoWithin": {
            "$centerSphere": [[lon, lat], km_to_radians(radius_km)],
        }
    }
    return await mongo.collection(COLL_EVENTS).count_documents(filt)


async def largest_event_near(
    mongo: MongoClient,
    *,
    lat: float,
    lon: float,
    radius_km: float,
    window: TimeWindow,
) -> dict[str, Any] | None:
    """The largest-magnitude event within the radius + window. None if no matches."""
    filt = _build_event_filter(window=window, min_mag=None, bbox=None)
    filt["geometry"] = {
        "$geoWithin": {
            "$centerSphere": [[lon, lat], km_to_radians(radius_km)],
        }
    }
    cursor = mongo.collection(COLL_EVENTS).find(filt).sort("properties.mag", -1).limit(1)
    docs = [doc async for doc in cursor]
    return docs[0] if docs else None


# ============================================================================
# System Health card
# ============================================================================


async def get_system_health(mongo: MongoClient) -> dict[str, Any]:
    """Aggregated view powering the always-visible System Health card.

    Returns:
    * `last_poll_ts`         — most recent `system_health` row (any feed)
    * `last_successful_poll` — most recent row with status=ok
    * `success_rate_1h`      — fraction of polls in last hour that returned ok
    * `consecutive_failures` — current streak of trailing errors (0 if last is ok)
    * `backfill`             — {status, events_loaded, completed_at}
    """
    coll = mongo.collection(COLL_SYSTEM_HEALTH)
    now = datetime.now(UTC)
    one_hour_ago = now - timedelta(hours=1)

    # Most recent poll of any kind.
    last_any = await coll.find_one(sort=[("ts", -1)])
    last_ok = await coll.find_one({"status": "ok"}, sort=[("ts", -1)])

    # Success rate in the last hour.
    pipeline = [
        {"$match": {"ts": {"$gte": one_hour_ago}}},
        {"$group": {"_id": "$status", "n": {"$sum": 1}}},
    ]
    counts: dict[str, int] = {}
    async for row in coll.aggregate(pipeline):
        counts[row["_id"]] = row["n"]
    total = sum(counts.values())
    success_rate_1h = (counts.get("ok", 0) / total) if total else None

    # Trailing failure streak (look back ~50 rows).
    recent = [doc async for doc in coll.find().sort("ts", -1).limit(50)]
    streak = 0
    for doc in recent:
        if doc.get("status") == "ok":
            break
        streak += 1

    backfill_doc = await mongo.collection(COLL_META).find_one({"_id": "backfill"})

    return {
        "now": now.isoformat(),
        "last_poll_ts": last_any.get("ts").isoformat() if last_any else None,
        "last_poll_status": last_any.get("status") if last_any else None,
        "last_successful_poll_ts": last_ok.get("ts").isoformat() if last_ok else None,
        "success_rate_1h": success_rate_1h,
        "consecutive_failures": streak,
        "polls_last_hour": total,
        "backfill": {
            "status": (backfill_doc or {}).get("status", "pending"),
            "events_loaded": (backfill_doc or {}).get("events_loaded"),
            "completed_at": (
                backfill_doc["completed_at"].isoformat()
                if backfill_doc and backfill_doc.get("completed_at")
                else None
            ),
        },
    }


# ============================================================================
# Live event stream (Mongo change stream → SSE)
# ============================================================================


async def stream_event_changes(
    mongo: MongoClient,
    *,
    poll_fallback_seconds: int = 30,
) -> AsyncIterator[dict[str, Any]]:
    """Yield events as they are inserted or updated.

    Tries Mongo change streams first (the production path on Atlas); falls
    back to a poll-the-last-N-rows loop if change streams aren't available
    (e.g. local Mongo not running as a replica set in dev).
    """
    coll = mongo.collection(COLL_EVENTS)
    try:
        async with coll.watch(
            [{"$match": {"operationType": {"$in": ["insert", "update", "replace"]}}}],
            full_document="updateLookup",
        ) as stream:
            log.info("api.sse.changestream.opened")
            async for change in stream:
                doc = change.get("fullDocument")
                if doc is None:
                    continue
                yield doc
            return
    except Exception as exc:
        log.warning("api.sse.changestream.unavailable", error=str(exc), mode="poll_fallback")

    # Polling fallback for dev environments without replica-set Mongo.
    last_seen: datetime | None = None
    while True:
        filt: dict[str, Any] = {}
        if last_seen is not None:
            filt["_last_seen_at"] = {"$gt": last_seen}
        cursor = coll.find(filt).sort("_last_seen_at", 1).limit(100)
        async for doc in cursor:
            yield doc
            last_seen = doc.get("_last_seen_at") or last_seen
        await asyncio.sleep(poll_fallback_seconds)
