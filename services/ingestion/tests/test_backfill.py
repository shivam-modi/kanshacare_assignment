"""Backfill: idempotency + happy path."""

from __future__ import annotations

import json
from pathlib import Path

import httpx
import pytest
import respx
from ingestion_app.backfill import run_backfill
from ingestion_app.repo import META_BACKFILL_ID

from kanshacare_shared.db import COLL_EVENTS, COLL_META
from kanshacare_shared.usgs import USGSClient

from ._fakes import FakeMongoClient

_HOUR_URL = "https://earthquake.usgs.gov/earthquakes/feed/v1.0/summary/all_hour.geojson"
_MONTH_URL = "https://earthquake.usgs.gov/earthquakes/feed/v1.0/summary/all_month.geojson"
_FIXTURE = Path(__file__).parent / "fixtures" / "usgs_hour_sample.json"


def _payload() -> dict[str, object]:
    return json.loads(_FIXTURE.read_text())


@pytest.fixture
def usgs() -> USGSClient:
    return USGSClient(hour_url=_HOUR_URL, month_url=_MONTH_URL, timeout_seconds=5.0)


@respx.mock
@pytest.mark.asyncio
async def test_backfill_skipped_when_already_complete(usgs: USGSClient) -> None:
    mongo = FakeMongoClient()
    # Mark backfill complete up-front.
    mongo.collection(COLL_META).docs[META_BACKFILL_ID] = {
        "_id": META_BACKFILL_ID,
        "status": "complete",
    }

    ran = await run_backfill(usgs=usgs, mongo=mongo, force=False)  # type: ignore[arg-type]
    await usgs.aclose()

    assert ran is False
    # No events should have been loaded — backfill short-circuited.
    assert mongo.collection(COLL_EVENTS).docs == {}


@respx.mock
@pytest.mark.asyncio
async def test_backfill_loads_events_and_marks_complete(usgs: USGSClient) -> None:
    mongo = FakeMongoClient()
    respx.get(_MONTH_URL).mock(return_value=httpx.Response(200, json=_payload()))

    ran = await run_backfill(usgs=usgs, mongo=mongo, force=False)  # type: ignore[arg-type]
    await usgs.aclose()

    assert ran is True
    assert len(mongo.collection(COLL_EVENTS).docs) == 3
    meta = mongo.collection(COLL_META).docs[META_BACKFILL_ID]
    assert meta["status"] == "complete"
    assert meta["events_loaded"] == 3


@respx.mock
@pytest.mark.asyncio
async def test_backfill_force_overrides_complete_flag(usgs: USGSClient) -> None:
    mongo = FakeMongoClient()
    mongo.collection(COLL_META).docs[META_BACKFILL_ID] = {
        "_id": META_BACKFILL_ID,
        "status": "complete",
    }
    respx.get(_MONTH_URL).mock(return_value=httpx.Response(200, json=_payload()))

    ran = await run_backfill(usgs=usgs, mongo=mongo, force=True)  # type: ignore[arg-type]
    await usgs.aclose()

    assert ran is True
    assert len(mongo.collection(COLL_EVENTS).docs) == 3
