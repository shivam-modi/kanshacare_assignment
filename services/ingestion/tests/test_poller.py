"""End-to-end poll cycle: respx mocks USGS, FakeMongoClient stands in for Motor."""

from __future__ import annotations

import json
from pathlib import Path

import httpx
import pytest
import respx
from ingestion_app.poller import run_poll_cycle

from kanshacare_shared.db import COLL_EVENTS, COLL_EVENTS_QUARANTINE, COLL_SYSTEM_HEALTH
from kanshacare_shared.usgs import USGSClient

from ._fakes import FakeMongoClient

_HOUR_URL = "https://earthquake.usgs.gov/earthquakes/feed/v1.0/summary/all_hour.geojson"
_MONTH_URL = "https://earthquake.usgs.gov/earthquakes/feed/v1.0/summary/all_month.geojson"
_FIXTURE = Path(__file__).parent / "fixtures" / "usgs_hour_sample.json"


def _hour_payload() -> dict[str, object]:
    return json.loads(_FIXTURE.read_text())


@pytest.fixture
def usgs() -> USGSClient:
    return USGSClient(hour_url=_HOUR_URL, month_url=_MONTH_URL, timeout_seconds=5.0)


@pytest.fixture
def fake_mongo() -> FakeMongoClient:
    return FakeMongoClient()


@respx.mock
@pytest.mark.asyncio
async def test_happy_path_writes_events_and_health(
    usgs: USGSClient,
    fake_mongo: FakeMongoClient,
) -> None:
    respx.get(_HOUR_URL).mock(return_value=httpx.Response(200, json=_hour_payload()))

    await run_poll_cycle(usgs=usgs, mongo=fake_mongo, feed="hour")  # type: ignore[arg-type]
    await usgs.aclose()

    events = fake_mongo.collection(COLL_EVENTS)
    assert set(events.docs.keys()) == {"ci-event-001", "ci-event-002", "ci-event-003"}

    health = fake_mongo.collection(COLL_SYSTEM_HEALTH)
    assert len(health.inserts) == 1
    row = health.inserts[0][0]
    assert row["feed"] == "hour"
    assert row["status"] == "ok"
    assert row["events_new"] == 3
    assert row["events_updated"] == 0
    assert row["http_status"] == 200
    assert row["latency_ms"] >= 0


@respx.mock
@pytest.mark.asyncio
async def test_upstream_5xx_records_error_does_not_raise(
    usgs: USGSClient,
    fake_mongo: FakeMongoClient,
) -> None:
    respx.get(_HOUR_URL).mock(return_value=httpx.Response(503))

    # Must not raise — scheduler depends on this guarantee.
    await run_poll_cycle(usgs=usgs, mongo=fake_mongo, feed="hour")  # type: ignore[arg-type]
    await usgs.aclose()

    assert fake_mongo.collection(COLL_EVENTS).docs == {}
    health = fake_mongo.collection(COLL_SYSTEM_HEALTH)
    assert len(health.inserts) == 1
    row = health.inserts[0][0]
    assert row["status"] == "error"
    assert row["error_class"] == "UpstreamError"


@respx.mock
@pytest.mark.asyncio
async def test_network_failure_is_logged_not_raised(
    usgs: USGSClient,
    fake_mongo: FakeMongoClient,
) -> None:
    respx.get(_HOUR_URL).mock(side_effect=httpx.ConnectError("network unreachable"))

    await run_poll_cycle(usgs=usgs, mongo=fake_mongo, feed="hour")  # type: ignore[arg-type]
    await usgs.aclose()

    health = fake_mongo.collection(COLL_SYSTEM_HEALTH)
    assert len(health.inserts) == 1
    assert health.inserts[0][0]["status"] == "error"


@respx.mock
@pytest.mark.asyncio
async def test_corrupt_feature_is_quarantined_not_dropped(
    usgs: USGSClient,
    fake_mongo: FakeMongoClient,
) -> None:
    payload = _hour_payload()
    # Inject a bogus feature mid-batch; the rest must still ingest.
    payload["features"].insert(  # type: ignore[index]
        1,
        {
            "type": "Feature",
            "id": "bogus-1",
            "properties": {"mag": 1.0, "tsunami": 0},
            "geometry": {"type": "Point", "coordinates": [999, 999, 0]},  # invalid
        },
    )
    respx.get(_HOUR_URL).mock(return_value=httpx.Response(200, json=payload))

    await run_poll_cycle(usgs=usgs, mongo=fake_mongo, feed="hour")  # type: ignore[arg-type]
    await usgs.aclose()

    # Three good features still in events.
    assert len(fake_mongo.collection(COLL_EVENTS).docs) == 3
    # Bad one in quarantine.
    quarantine = fake_mongo.collection(COLL_EVENTS_QUARANTINE)
    assert len(quarantine.inserts) == 1
    assert quarantine.inserts[0][0]["feature_id"] == "bogus-1"
    # Health row records the quarantined count.
    row = fake_mongo.collection(COLL_SYSTEM_HEALTH).inserts[0][0]
    assert row["events_quarantined"] == 1


@respx.mock
@pytest.mark.asyncio
async def test_304_not_modified_treated_as_healthy(
    usgs: USGSClient,
    fake_mongo: FakeMongoClient,
) -> None:
    # Prime the etag on the first call, then return 304 on the second.
    respx.get(_HOUR_URL).mock(
        side_effect=[
            httpx.Response(200, json=_hour_payload(), headers={"ETag": "abc"}),
            httpx.Response(304),
        ]
    )

    await run_poll_cycle(usgs=usgs, mongo=fake_mongo, feed="hour")  # type: ignore[arg-type]
    await run_poll_cycle(usgs=usgs, mongo=fake_mongo, feed="hour")  # type: ignore[arg-type]
    await usgs.aclose()

    rows = fake_mongo.collection(COLL_SYSTEM_HEALTH).inserts
    assert len(rows) == 2
    assert rows[0][0]["status"] == "ok"
    assert rows[1][0]["status"] == "ok"
    assert rows[1][0]["http_status"] == 304
