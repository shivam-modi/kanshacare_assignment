"""Alert rule engine.

Each rule is a pure function (mostly) that decides whether an incoming event
*should* fire an alert, returning an `AlertCandidate` or None. The dispatcher
then dedups against alerts_log (unique index on dedup_key) and enqueues delivery.

Rules:
  * high_severity_global — any event with mag ≥ global threshold
  * high_severity_near   — event within radius_km of any registered location
                            AND mag ≥ near threshold
  * swarm                — ≥ N events in a `swarm_window_minutes` rolling
                            window within `swarm_radius_km` of the incoming
                            event (centred on it)
  * source_silence       — fired by a separate scheduler, not the change stream
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any

from kanshacare_shared.config import BaseAppSettings
from kanshacare_shared.db import COLL_EVENTS, COLL_LOCATIONS, MongoClient
from kanshacare_shared.geo import LatLon, haversine_km, km_to_radians
from kanshacare_shared.logging import get_logger
from kanshacare_shared.models import AlertRule, AlertSeverity

log = get_logger(__name__)


@dataclass(frozen=True, slots=True)
class AlertCandidate:
    rule: AlertRule
    dedup_key: str
    severity: AlertSeverity
    event_id: str | None
    location_id: str | None
    payload: dict[str, Any]


async def evaluate_event(
    event: dict[str, Any],
    *,
    settings: BaseAppSettings,
    mongo: MongoClient,
) -> list[AlertCandidate]:
    """Run all event-driven rules against a single change-stream event."""
    candidates: list[AlertCandidate] = []
    mag = event.get("properties", {}).get("mag")
    if mag is None:
        return candidates

    if mag >= settings.alert_global_mag_threshold:
        candidates.append(_make_global(event, mag, severity_for(mag)))

    # Per-location proximity check.
    coords = event.get("geometry", {}).get("coordinates", [])
    if len(coords) >= 2 and mag >= settings.alert_near_mag_threshold:
        ev_lat, ev_lon = float(coords[1]), float(coords[0])
        locs = await _load_locations(mongo)
        for loc in locs:
            loc_lon, loc_lat = loc["point"]["coordinates"][0], loc["point"]["coordinates"][1]
            thresholds = loc.get("thresholds") or {}
            near_mag = thresholds.get("near_mag") or settings.alert_near_mag_threshold
            near_radius_km = thresholds.get("near_radius_km") or settings.alert_near_radius_km
            if mag < near_mag:
                continue
            dist = haversine_km(LatLon(ev_lat, ev_lon), LatLon(loc_lat, loc_lon))
            if dist <= near_radius_km:
                candidates.append(_make_near(event, mag, loc, dist, severity_for(mag)))

    # Swarm check — centred on the incoming event.
    if len(coords) >= 2:
        ev_lat, ev_lon = float(coords[1]), float(coords[0])
        time_ms = event.get("properties", {}).get("time")
        if time_ms is not None:
            swarm = await _check_swarm(
                mongo,
                lat=ev_lat,
                lon=ev_lon,
                anchor_time_ms=int(time_ms),
                radius_km=settings.swarm_radius_km,
                window_minutes=settings.swarm_window_minutes,
                min_events=settings.swarm_min_events,
            )
            if swarm is not None:
                candidates.append(_make_swarm(event, swarm))

    return candidates


def severity_for(mag: float) -> AlertSeverity:
    if mag >= 6.0:
        return "critical"
    if mag >= 5.0:
        return "warning"
    return "info"


def _make_global(event: dict[str, Any], mag: float, severity: AlertSeverity) -> AlertCandidate:
    eid = event["_id"]
    return AlertCandidate(
        rule="high_severity_global",
        dedup_key=f"high_severity_global:{eid}",
        severity=severity,
        event_id=eid,
        location_id=None,
        payload={
            "mag": mag,
            "place": event.get("properties", {}).get("place"),
            "time": event.get("properties", {}).get("time"),
            "alert": event.get("properties", {}).get("alert"),
            "tsunami": event.get("properties", {}).get("tsunami"),
            "url": event.get("properties", {}).get("url"),
            "coordinates": event.get("geometry", {}).get("coordinates"),
        },
    )


def _make_near(
    event: dict[str, Any],
    mag: float,
    loc: dict[str, Any],
    dist_km: float,
    severity: AlertSeverity,
) -> AlertCandidate:
    eid = event["_id"]
    lid = loc["_id"]
    return AlertCandidate(
        rule="high_severity_near",
        dedup_key=f"high_severity_near:{eid}:{lid}",
        severity=severity,
        event_id=eid,
        location_id=lid,
        payload={
            "mag": mag,
            "place": event.get("properties", {}).get("place"),
            "time": event.get("properties", {}).get("time"),
            "location_name": loc.get("name"),
            "distance_km": round(dist_km, 1),
            "tsunami": event.get("properties", {}).get("tsunami"),
        },
    )


def _make_swarm(event: dict[str, Any], swarm: dict[str, Any]) -> AlertCandidate:
    # Dedup key uses a 30-min bucket so a continuing swarm doesn't re-fire constantly.
    bucket_ms = (int(event.get("properties", {}).get("time") or 0) // (30 * 60_000)) * (30 * 60_000)
    coords = event.get("geometry", {}).get("coordinates", [0, 0])
    # Rough geohash by truncating coordinates — good enough for a dedup bucket.
    geo_bucket = f"{round(coords[1], 1)}_{round(coords[0], 1)}"
    return AlertCandidate(
        rule="swarm",
        dedup_key=f"swarm:{geo_bucket}:{bucket_ms}",
        severity="warning",
        event_id=event["_id"],
        location_id=None,
        payload={
            "count": swarm["count"],
            "centre": [coords[0], coords[1]],
            "window_minutes": swarm["window_minutes"],
            "radius_km": swarm["radius_km"],
            "largest_mag": swarm["largest_mag"],
        },
    )


async def _load_locations(mongo: MongoClient) -> list[dict[str, Any]]:
    cursor = mongo.collection(COLL_LOCATIONS).find({})
    return [doc async for doc in cursor]


async def _check_swarm(
    mongo: MongoClient,
    *,
    lat: float,
    lon: float,
    anchor_time_ms: int,
    radius_km: float,
    window_minutes: int,
    min_events: int,
) -> dict[str, Any] | None:
    """Return swarm info if ≥min_events occurred in window centred at lat/lon."""
    window_ms = window_minutes * 60_000
    floor_ms = anchor_time_ms - window_ms
    filt = {
        "properties.time": {"$gte": floor_ms, "$lte": anchor_time_ms},
        "geometry": {
            "$geoWithin": {
                "$centerSphere": [[lon, lat], km_to_radians(radius_km)],
            }
        },
    }
    coll = mongo.collection(COLL_EVENTS)
    count = await coll.count_documents(filt)
    if count < min_events:
        return None
    # Find the largest mag in the swarm for the alert payload.
    cursor = coll.find(filt).sort("properties.mag", -1).limit(1)
    docs = [d async for d in cursor]
    largest = docs[0]["properties"].get("mag") if docs else None
    return {
        "count": count,
        "window_minutes": window_minutes,
        "radius_km": radius_km,
        "largest_mag": largest,
    }


def make_silence_candidate(*, age_minutes: float) -> AlertCandidate:
    """Built by the silence scheduler, not from an event."""
    # Dedup bucket by hour so we re-fire if silence persists across hours but don't spam.
    hour_bucket = int(datetime.now(UTC).timestamp() // 3600)
    return AlertCandidate(
        rule="source_silence",
        dedup_key=f"source_silence:{hour_bucket}",
        severity="critical",
        event_id=None,
        location_id=None,
        payload={
            "minutes_since_last_poll": round(age_minutes, 1),
            "detected_at": datetime.now(UTC).isoformat(),
        },
    )


def stale_check(last_ok_iso: str | None, threshold_minutes: int) -> float | None:
    """Returns minutes_since_last_ok if older than threshold; else None."""
    if last_ok_iso is None:
        return None
    try:
        last_ok = datetime.fromisoformat(last_ok_iso.replace("Z", "+00:00"))
    except ValueError:
        return None
    age = datetime.now(UTC) - last_ok
    minutes = age.total_seconds() / 60.0
    return minutes if age > timedelta(minutes=threshold_minutes) else None
