"""Rule engine — high-severity-global, high-severity-near, swarm."""

from __future__ import annotations

import pytest

from alerts_app.rules import evaluate_event
from alerts_app.settings import get_settings
from kanshacare_shared.db import COLL_EVENTS, COLL_LOCATIONS

from ._fakes import FakeMongoClient, make_event


@pytest.mark.asyncio
async def test_global_threshold_fires() -> None:
    mongo = FakeMongoClient()
    event = make_event("e1", mag=5.5, lat=0, lon=0)
    cands = await evaluate_event(event, settings=get_settings(), mongo=mongo)  # type: ignore[arg-type]
    rules = {c.rule for c in cands}
    assert "high_severity_global" in rules


@pytest.mark.asyncio
async def test_global_below_threshold_doesnt_fire() -> None:
    mongo = FakeMongoClient()
    event = make_event("e1", mag=3.0, lat=0, lon=0)
    cands = await evaluate_event(event, settings=get_settings(), mongo=mongo)  # type: ignore[arg-type]
    assert all(c.rule != "high_severity_global" for c in cands)


@pytest.mark.asyncio
async def test_near_fires_only_when_event_inside_radius() -> None:
    settings = get_settings()
    mongo = FakeMongoClient()
    # Plant a location in Tokyo (35.6762, 139.6503).
    mongo.collection(COLL_LOCATIONS).docs["loc-tokyo"] = {
        "_id": "loc-tokyo",
        "name": "Tokyo",
        "point": {"type": "Point", "coordinates": [139.6503, 35.6762]},
        "radius_km": 500,
        "thresholds": {"near_mag": None, "near_radius_km": None},
    }

    # ~50 km away — should fire near.
    inside = make_event("e1", mag=4.5, lat=36.0, lon=140.0)
    cands = await evaluate_event(inside, settings=settings, mongo=mongo)  # type: ignore[arg-type]
    near = [c for c in cands if c.rule == "high_severity_near"]
    assert len(near) == 1
    assert near[0].location_id == "loc-tokyo"

    # San Francisco — outside the 500 km radius.
    outside = make_event("e2", mag=4.5, lat=37.7749, lon=-122.4194)
    cands = await evaluate_event(outside, settings=settings, mongo=mongo)  # type: ignore[arg-type]
    assert all(c.rule != "high_severity_near" for c in cands)


@pytest.mark.asyncio
async def test_near_respects_per_location_threshold_override() -> None:
    settings = get_settings()
    mongo = FakeMongoClient()
    mongo.collection(COLL_LOCATIONS).docs["loc"] = {
        "_id": "loc",
        "name": "Stricter",
        "point": {"type": "Point", "coordinates": [0.0, 0.0]},
        "radius_km": 500,
        # Custom threshold: only fire on M ≥ 5.5
        "thresholds": {"near_mag": 5.5, "near_radius_km": 200},
    }

    # M5 close by — would fire globally with default 4.0 but custom is 5.5.
    event = make_event("e1", mag=5.0, lat=0.5, lon=0.5)
    cands = await evaluate_event(event, settings=settings, mongo=mongo)  # type: ignore[arg-type]
    assert all(c.rule != "high_severity_near" for c in cands)


@pytest.mark.asyncio
async def test_swarm_fires_when_threshold_met() -> None:
    settings = get_settings()
    mongo = FakeMongoClient()
    # Seed many nearby recent events.
    now_ms = 1_700_000_000_000
    events_coll = mongo.collection(COLL_EVENTS)
    for i in range(6):
        ev = make_event(
            f"seed-{i}", mag=3.0, lat=10.0 + i * 0.1, lon=10.0, time_ms=now_ms - i * 60_000
        )
        events_coll.docs[ev["_id"]] = ev

    # Incoming event in the same area.
    incoming = make_event("incoming", mag=3.0, lat=10.0, lon=10.0, time_ms=now_ms)
    cands = await evaluate_event(incoming, settings=settings, mongo=mongo)  # type: ignore[arg-type]
    swarm = [c for c in cands if c.rule == "swarm"]
    assert len(swarm) == 1
    assert swarm[0].payload["count"] >= settings.swarm_min_events


@pytest.mark.asyncio
async def test_swarm_doesnt_fire_below_threshold() -> None:
    settings = get_settings()
    mongo = FakeMongoClient()
    # Only 2 nearby — below default min of 5.
    now_ms = 1_700_000_000_000
    events_coll = mongo.collection(COLL_EVENTS)
    for i in range(2):
        ev = make_event(f"seed-{i}", mag=3.0, lat=10.0, lon=10.0, time_ms=now_ms - i * 60_000)
        events_coll.docs[ev["_id"]] = ev

    incoming = make_event("incoming", mag=3.0, lat=10.0, lon=10.0, time_ms=now_ms)
    cands = await evaluate_event(incoming, settings=settings, mongo=mongo)  # type: ignore[arg-type]
    assert all(c.rule != "swarm" for c in cands)
