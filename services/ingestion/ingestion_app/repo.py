"""Mongo write layer for ingestion-svc.

Single source of truth for how events get into the database. Keeps the
backfill and the poller using the exact same upsert path so they cannot
diverge.
"""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

from motor.motor_asyncio import AsyncIOMotorCollection
from pymongo import UpdateOne

from kanshacare_shared.db import (
    COLL_EVENTS,
    COLL_EVENTS_QUARANTINE,
    COLL_META,
    COLL_SYSTEM_HEALTH,
    MongoClient,
)
from kanshacare_shared.logging import get_logger
from kanshacare_shared.models import SCHEMA_VERSION, USGSFeature

log = get_logger(__name__)

META_BACKFILL_ID = "backfill"


@dataclass(frozen=True, slots=True)
class UpsertOutcome:
    """Per-cycle accounting. Used to write a system_health row and emit metrics."""

    new: int
    updated: int
    unchanged: int

    @property
    def total(self) -> int:
        return self.new + self.updated + self.unchanged


async def upsert_features(
    coll: AsyncIOMotorCollection,
    features: Iterable[USGSFeature],
    *,
    now: datetime | None = None,
) -> UpsertOutcome:
    """Bulk upsert features keyed by USGS id.

    "Updated" specifically means USGS revised the event (`properties.updated`
    moved forward), not "we wrote bytes to disk". We split features into
    new / updated / unchanged by reading current `properties.updated` first.
    Two round trips, but the counts are then semantically precise — exactly
    what the dashboard needs.
    """
    now = now or datetime.now(UTC)
    features = list(features)
    if not features:
        return UpsertOutcome(new=0, updated=0, unchanged=0)

    ids = [f.id for f in features]
    existing_cursor = coll.find(
        {"_id": {"$in": ids}},
        {"_id": 1, "properties.updated": 1},
    )
    existing: dict[str, int | None] = {}
    async for doc in existing_cursor:
        existing[doc["_id"]] = doc.get("properties", {}).get("updated")

    new_features: list[USGSFeature] = []
    updated_features: list[USGSFeature] = []
    unchanged = 0
    for f in features:
        if f.id not in existing:
            new_features.append(f)
            continue
        current = existing[f.id]
        incoming = f.properties.updated
        if incoming is None or current is None or incoming > current:
            updated_features.append(f)
        else:
            unchanged += 1

    ops = [_upsert_op(f, now) for f in (*new_features, *updated_features)]
    if ops:
        await coll.bulk_write(ops, ordered=False)

    return UpsertOutcome(
        new=len(new_features),
        updated=len(updated_features),
        unchanged=unchanged,
    )


def _upsert_op(feature: USGSFeature, now: datetime) -> UpdateOne:
    return UpdateOne(
        {"_id": feature.id},
        {
            "$set": {
                "properties": feature.properties.model_dump(),
                "geometry": feature.geometry.model_dump(),
                "_last_seen_at": now,
                "_schema_version": SCHEMA_VERSION,
            },
            "$setOnInsert": {"_ingested_at": now},
        },
        upsert=True,
    )


async def quarantine_features(
    coll: AsyncIOMotorCollection,
    bad: Iterable[dict[str, Any]],
    *,
    feed: str,
    now: datetime | None = None,
) -> int:
    """Insert malformed features into events_quarantine for later inspection.

    Never block ingestion on this — best-effort. If quarantine writes fail we
    log and move on. Caller still gets a count of attempted writes.
    """
    now = now or datetime.now(UTC)
    docs = []
    for item in bad:
        raw = item.get("raw", {})
        feature_id = raw.get("id") if isinstance(raw, dict) else None
        docs.append(
            {
                "feature_id": feature_id,
                "feed": feed,
                "raw": raw,
                "error": item.get("error"),
                "ts": now,
            }
        )
    if not docs:
        return 0
    try:
        result = await coll.insert_many(docs, ordered=False)
        return len(result.inserted_ids)
    except Exception as exc:
        log.warning("ingestion.quarantine.failed", error=str(exc))
        return 0


async def record_health(
    mongo: MongoClient,
    *,
    feed: str,
    status: str,
    latency_ms: int,
    new: int = 0,
    updated: int = 0,
    quarantined: int = 0,
    http_status: int | None = None,
    error_class: str | None = None,
    error_message: str | None = None,
    now: datetime | None = None,
) -> None:
    """Append one row to system_health. Never raises — we don't want the
    health logger itself to be the thing that takes down the poller."""
    now = now or datetime.now(UTC)
    doc = {
        "ts": now,
        "feed": feed,
        "status": status,
        "latency_ms": latency_ms,
        "events_new": new,
        "events_updated": updated,
        "events_quarantined": quarantined,
        "http_status": http_status,
        "error_class": error_class,
        "error_message": error_message,
        "_schema_version": SCHEMA_VERSION,
    }
    try:
        await mongo.collection(COLL_SYSTEM_HEALTH).insert_one(doc)
    except Exception as exc:
        log.warning("ingestion.health.insert_failed", error=str(exc))


async def is_backfill_complete(mongo: MongoClient) -> bool:
    """True if a previous run successfully completed backfill."""
    doc = await mongo.collection(COLL_META).find_one({"_id": META_BACKFILL_ID})
    return bool(doc and doc.get("status") == "complete")


async def mark_backfill(
    mongo: MongoClient,
    *,
    status: str,
    events_loaded: int | None = None,
    error: str | None = None,
) -> None:
    """Record backfill state. Used by /system/health on the dashboard."""
    now = datetime.now(UTC)
    update: dict[str, Any] = {"status": status, "updated_at": now}
    if events_loaded is not None:
        update["events_loaded"] = events_loaded
    if error is not None:
        update["error"] = error
    if status == "running":
        update["started_at"] = now
    if status == "complete":
        update["completed_at"] = now
    await mongo.collection(COLL_META).update_one(
        {"_id": META_BACKFILL_ID},
        {"$set": update},
        upsert=True,
    )


def get_events_collection(mongo: MongoClient) -> AsyncIOMotorCollection:
    return mongo.collection(COLL_EVENTS)


def get_quarantine_collection(mongo: MongoClient) -> AsyncIOMotorCollection:
    return mongo.collection(COLL_EVENTS_QUARANTINE)
