from __future__ import annotations

from datetime import UTC, datetime, timedelta

from kanshacare_shared.db import COLL_EVENTS, COLL_LOCATIONS

from ._fakes import make_event


def _now_ms(offset: timedelta = timedelta(0)) -> int:
    return int((datetime.now(UTC) + offset).timestamp() * 1000)


def test_create_location_via_lat_lon(client_with_fakes) -> None:
    client, mongo, _, _ = client_with_fakes
    r = client.post("/locations", json={"name": "Home", "lat": 35.0, "lon": 139.0})
    assert r.status_code == 201
    body = r.json()
    assert body["name"] == "Home"
    assert body["point"]["coordinates"] == [139.0, 35.0]
    assert len(mongo.collection(COLL_LOCATIONS).docs) == 1


def test_create_location_via_geocoded_query(client_with_fakes) -> None:
    client, _, _, geocoder = client_with_fakes
    r = client.post("/locations", json={"name": "Tokyo", "query": "Tokyo"})
    assert r.status_code == 201
    body = r.json()
    assert body["name"] == "Tokyo"
    # FakeGeocoder maps Tokyo → (35.6762, 139.6503)
    assert body["point"]["coordinates"][0] == 139.6503


def test_create_location_neither_query_nor_coords_fails(client_with_fakes) -> None:
    client, _, _, _ = client_with_fakes
    r = client.post("/locations", json={"name": "Empty"})
    assert r.status_code == 400


def test_create_location_unknown_query_fails(client_with_fakes) -> None:
    client, _, _, _ = client_with_fakes
    r = client.post("/locations", json={"name": "Mars", "query": "NotARealPlace"})
    assert r.status_code == 400


def test_location_cap_enforced(client_with_fakes) -> None:
    client, _, _, _ = client_with_fakes
    for i in range(3):
        r = client.post("/locations", json={"name": f"L{i}", "lat": i * 1.0, "lon": i * 1.0})
        assert r.status_code == 201
    r = client.post("/locations", json={"name": "L4", "lat": 4.0, "lon": 4.0})
    assert r.status_code == 409


def test_delete_location(client_with_fakes) -> None:
    client, mongo, _, _ = client_with_fakes
    r = client.post("/locations", json={"name": "Tmp", "lat": 1.0, "lon": 1.0})
    location_id = r.json()["_id"]
    r = client.delete(f"/locations/{location_id}")
    assert r.status_code == 204
    assert location_id not in mongo.collection(COLL_LOCATIONS).docs


def test_location_summary_includes_risk_counts_and_thresholds(client_with_fakes) -> None:
    client, mongo, _, _ = client_with_fakes
    events = mongo.collection(COLL_EVENTS)
    events.docs = {
        "near": make_event(
            "near", mag=4.5, lat=35.7, lon=139.7, time_ms=_now_ms(timedelta(hours=-2))
        ),
        "far": make_event("far", mag=6.0, lat=10, lon=10, time_ms=_now_ms()),
    }
    r = client.post("/locations", json={"name": "Tokyo", "query": "Tokyo", "radius_km": 200})
    location_id = r.json()["_id"]

    r = client.get(f"/locations/{location_id}/summary")
    assert r.status_code == 200
    body = r.json()
    assert "risk" in body
    assert body["risk"]["event_count"] == 1
    assert body["counts"]["24h"] == 1
    assert body["counts"]["7d"] == 1
    assert body["thresholds"]["near_mag"] == 4.0
    assert body["thresholds"]["near_radius_km"] == 500
    assert body["largest_event"]["_id"] == "near"
