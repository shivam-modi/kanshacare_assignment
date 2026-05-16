"""Location CRUD + risk summary. Wraps Mongo with a clean service-facing API."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from typing import Any

from kanshacare_shared.config import BaseAppSettings
from kanshacare_shared.db import COLL_LOCATIONS, MongoClient
from kanshacare_shared.errors import ConflictError, NotFoundError
from kanshacare_shared.geo import LatLon, geojson_point
from kanshacare_shared.models import (
    LocationCreate,
    LocationThresholds,
)
from kanshacare_shared.risk import EventForRisk, RiskBreakdown, compute_risk

from .queries import (
    TimeWindow,
    count_events_near,
    largest_event_near,
    list_events_near,
)


async def list_locations(mongo: MongoClient) -> list[dict[str, Any]]:
    cursor = mongo.collection(COLL_LOCATIONS).find().sort("created_at", 1)
    return [doc async for doc in cursor]


async def create_location(
    mongo: MongoClient,
    data: LocationCreate,
    *,
    max_locations: int,
) -> dict[str, Any]:
    coll = mongo.collection(COLL_LOCATIONS)
    count = await coll.count_documents({})
    if count >= max_locations:
        raise ConflictError(
            f"location cap reached ({max_locations}); delete one before adding another"
        )
    doc = {
        "_id": str(uuid.uuid4()),
        "name": data.name,
        "query": data.query,
        "point": geojson_point(lat=data.lat, lon=data.lon),
        "radius_km": data.radius_km,
        "thresholds": data.thresholds.model_dump(),
        "created_at": datetime.now(UTC),
        "_schema_version": 1,
    }
    await coll.insert_one(doc)
    return doc


async def delete_location(mongo: MongoClient, location_id: str) -> None:
    result = await mongo.collection(COLL_LOCATIONS).delete_one({"_id": location_id})
    if result.deleted_count == 0:
        raise NotFoundError(f"location not found: {location_id}")


async def get_location(mongo: MongoClient, location_id: str) -> dict[str, Any]:
    doc = await mongo.collection(COLL_LOCATIONS).find_one({"_id": location_id})
    if doc is None:
        raise NotFoundError(f"location not found: {location_id}")
    return doc


def effective_thresholds(loc: dict[str, Any], settings: BaseAppSettings) -> dict[str, float]:
    """Per-location overrides fall back to the global defaults from settings.

    These are the strings shown on the dashboard ("next alert fires if mag ≥ X
    within Y km") so the user understands what's being monitored.
    """
    raw = loc.get("thresholds") or {}
    t = LocationThresholds.model_validate(raw)
    return {
        "near_mag": t.near_mag if t.near_mag is not None else settings.alert_near_mag_threshold,
        "near_radius_km": (
            t.near_radius_km if t.near_radius_km is not None else settings.alert_near_radius_km
        ),
    }


async def build_location_summary(
    mongo: MongoClient,
    settings: BaseAppSettings,
    location_id: str,
) -> dict[str, Any]:
    """Everything the per-location card on the dashboard needs."""
    loc = await get_location(mongo, location_id)
    lat = float(loc["point"]["coordinates"][1])
    lon = float(loc["point"]["coordinates"][0])
    radius_km = float(loc.get("radius_km", settings.alert_near_radius_km))

    # 30d events used for both the risk score and the "nearby events" mini-list.
    nearby_30d = await list_events_near(
        mongo, lat=lat, lon=lon, radius_km=radius_km, window="30d", limit=500
    )

    risk: RiskBreakdown = compute_risk(
        (
            EventForRisk(
                mag=ev.get("properties", {}).get("mag", 0.0),
                lat=ev["geometry"]["coordinates"][1],
                lon=ev["geometry"]["coordinates"][0],
                time_utc=_event_time_to_utc(ev.get("properties", {}).get("time")),
            )
            for ev in nearby_30d
            if ev.get("properties", {}).get("mag") is not None
            and ev.get("properties", {}).get("time") is not None
        ),
        location=LatLon(lat, lon),
        radius_km=radius_km,
    )

    counts: dict[str, int] = {}
    for window in ("24h", "7d", "30d"):
        counts[window] = await count_events_near(
            mongo,
            lat=lat,
            lon=lon,
            radius_km=radius_km,
            window=window,  # type: ignore[arg-type]
        )

    largest = await largest_event_near(mongo, lat=lat, lon=lon, radius_km=radius_km, window="30d")

    return {
        "location": loc,
        "thresholds": effective_thresholds(loc, settings),
        "risk": {
            "score": risk.score,
            "tier": risk.tier,
            "event_count": risk.event_count,
            "largest_mag": risk.largest_mag,
            "closest_km": risk.closest_km,
            "formula": (
                "Σ over events in radius/30d of magnitude_weight × recency_decay × proximity_decay"
            ),
        },
        "counts": counts,
        "largest_event": largest,
        "nearby_events": nearby_30d[:50],  # cap on the wire — dashboard paginates locally
    }


def _event_time_to_utc(time_ms: int | float | None) -> datetime:
    if time_ms is None:
        return datetime.now(UTC)
    return datetime.fromtimestamp(time_ms / 1000.0, tz=UTC)


# ---------- window helpers ---------------------------------------------------

ALLOWED_WINDOWS: tuple[TimeWindow, ...] = ("1h", "24h", "7d", "30d")
