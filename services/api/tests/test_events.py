from __future__ import annotations

from datetime import UTC, datetime, timedelta

from kanshacare_shared.db import COLL_EVENTS

from ._fakes import make_event


def _now_ms(offset: timedelta = timedelta(0)) -> int:
    return int((datetime.now(UTC) + offset).timestamp() * 1000)


def test_get_events_returns_recent(client_with_fakes) -> None:
    client, mongo, _, _ = client_with_fakes
    events = mongo.collection(COLL_EVENTS)
    events.docs = {
        "a": make_event("a", mag=2.0, lat=0, lon=0, time_ms=_now_ms(timedelta(minutes=-30))),
        "b": make_event("b", mag=4.5, lat=10, lon=10, time_ms=_now_ms(timedelta(days=-2))),
        "c": make_event("c", mag=6.0, lat=20, lon=20, time_ms=_now_ms(timedelta(days=-10))),
    }

    r = client.get("/events?window=24h")
    assert r.status_code == 200
    body = r.json()
    assert body["window"] == "24h"
    # Only the 30-minute-old event is inside the 24h window.
    assert body["count"] == 1
    assert body["events"][0]["_id"] == "a"


def test_get_events_min_mag_filter(client_with_fakes) -> None:
    client, mongo, _, _ = client_with_fakes
    events = mongo.collection(COLL_EVENTS)
    events.docs = {
        "small": make_event("small", mag=2.0, lat=0, lon=0, time_ms=_now_ms()),
        "big": make_event("big", mag=5.5, lat=0, lon=0, time_ms=_now_ms()),
    }

    r = client.get("/events?window=24h&min_mag=4")
    assert r.status_code == 200
    body = r.json()
    assert body["count"] == 1
    assert body["events"][0]["_id"] == "big"


def test_get_events_near_uses_geo_filter(client_with_fakes) -> None:
    client, mongo, _, _ = client_with_fakes
    events = mongo.collection(COLL_EVENTS)
    # Tokyo (35.68, 139.65) vs San Francisco (37.77, -122.42) — ~8000 km apart.
    events.docs = {
        "tokyo": make_event("tokyo", mag=4.0, lat=35.7, lon=139.7, time_ms=_now_ms()),
        "sf": make_event("sf", mag=4.0, lat=37.7, lon=-122.4, time_ms=_now_ms()),
    }

    r = client.get("/events/near?lat=35.6762&lon=139.6503&radius_km=300&window=30d")
    assert r.status_code == 200
    body = r.json()
    assert body["count"] == 1
    assert body["events"][0]["_id"] == "tokyo"


def test_bbox_invalid_returns_400(client_with_fakes) -> None:
    client, _, _, _ = client_with_fakes
    r = client.get("/events?bbox=not-a-bbox")
    assert r.status_code == 400
