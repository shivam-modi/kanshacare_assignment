"""Aggregations used by the daily summary job."""

from __future__ import annotations

from collections import Counter
from datetime import UTC, datetime, timedelta
from typing import Any

from kanshacare_shared.db import COLL_ALERTS_LOG, COLL_EVENTS, COLL_LOCATIONS, MongoClient
from kanshacare_shared.geo import LatLon
from kanshacare_shared.risk import EventForRisk, compute_risk

from .messages import mag_band_for


async def collect_daily(mongo: MongoClient) -> dict[str, Any]:
    """Return everything needed to render the daily summary message."""
    now = datetime.now(UTC)
    floor_dt = now - timedelta(hours=24)
    floor_ms = int(floor_dt.timestamp() * 1000)

    events_coll = mongo.collection(COLL_EVENTS)
    cursor = events_coll.find({"properties.time": {"$gte": floor_ms}})
    events: list[dict[str, Any]] = [doc async for doc in cursor]

    bands: Counter[str] = Counter()
    regions: Counter[str] = Counter()
    for e in events:
        mag = e.get("properties", {}).get("mag")
        bands[mag_band_for(mag if mag is not None else None)] += 1
        place = e.get("properties", {}).get("place") or "Unknown"
        # Use the suffix after the last "of" — e.g. "10 km E of Anchorage" → "Anchorage"
        region = place.split(" of ")[-1] if " of " in place else place
        regions[region] += 1

    alerts_coll = mongo.collection(COLL_ALERTS_LOG)
    alerts_cursor = alerts_coll.find({"fired_at": {"$gte": floor_dt}})
    alert_rules: Counter[str] = Counter()
    async for a in alerts_cursor:
        alert_rules[a.get("rule", "unknown")] += 1

    return {
        "totals": {"total": len(events)},
        "mag_bands": dict(bands),
        "top_regions": regions.most_common(3),
        "fired_alerts": dict(alert_rules),
        "events": events,
    }


async def compute_location_risks(
    mongo: MongoClient,
    events: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    """For each registered location, run the risk score against the day's events."""
    locations_cursor = mongo.collection(COLL_LOCATIONS).find()
    locs = [doc async for doc in locations_cursor]
    out: list[dict[str, Any]] = []
    for loc in locs:
        lon, lat = loc["point"]["coordinates"][0], loc["point"]["coordinates"][1]
        radius = float(loc.get("radius_km", 500))
        evs = (
            EventForRisk(
                mag=ev["properties"]["mag"],
                lat=ev["geometry"]["coordinates"][1],
                lon=ev["geometry"]["coordinates"][0],
                time_utc=datetime.fromtimestamp(ev["properties"]["time"] / 1000, tz=UTC),
            )
            for ev in events
            if ev.get("properties", {}).get("mag") is not None
            and ev.get("properties", {}).get("time") is not None
        )
        breakdown = compute_risk(evs, location=LatLon(lat, lon), radius_km=radius)
        out.append(
            {
                "name": loc.get("name"),
                "risk_score": breakdown.score,
                "risk_tier": breakdown.tier,
            }
        )
    return out
