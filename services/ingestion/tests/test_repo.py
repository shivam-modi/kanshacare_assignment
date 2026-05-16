"""Upsert classification: new / updated / unchanged."""

from __future__ import annotations

from datetime import UTC, datetime

import pytest
from ingestion_app.repo import upsert_features

from kanshacare_shared.models import USGSFeature

from ._fakes import FakeCollection


def _feature(fid: str, mag: float, updated_ms: int | None) -> USGSFeature:
    return USGSFeature.model_validate(
        {
            "type": "Feature",
            "id": fid,
            "properties": {
                "mag": mag,
                "place": "Test",
                "time": updated_ms,
                "updated": updated_ms,
                "tsunami": 0,
            },
            "geometry": {"type": "Point", "coordinates": [10.0, 20.0, 5.0]},
        }
    )


@pytest.mark.asyncio
async def test_all_new_when_db_empty() -> None:
    coll = FakeCollection()
    now = datetime.now(UTC)
    features = [_feature("a", 2.0, 100), _feature("b", 3.0, 200)]

    outcome = await upsert_features(coll, features, now=now)

    assert outcome.new == 2
    assert outcome.updated == 0
    assert outcome.unchanged == 0
    assert set(coll.docs.keys()) == {"a", "b"}
    # Ingestion stamps should be present on new docs.
    assert all("_ingested_at" in coll.docs[k] for k in ("a", "b"))


@pytest.mark.asyncio
async def test_unchanged_when_updated_timestamp_matches() -> None:
    coll = FakeCollection()
    coll.docs["a"] = {
        "_id": "a",
        "properties": {"updated": 200, "mag": 2.0},
        "_ingested_at": datetime.now(UTC),
    }
    feature_unchanged = _feature("a", 2.0, 200)  # same updated ms

    outcome = await upsert_features(coll, [feature_unchanged])
    assert outcome.new == 0
    assert outcome.updated == 0
    assert outcome.unchanged == 1
    # No bulk write should have been issued.
    assert coll.bulk_ops == []


@pytest.mark.asyncio
async def test_updated_when_usgs_revised_timestamp() -> None:
    coll = FakeCollection()
    coll.docs["a"] = {
        "_id": "a",
        "properties": {"updated": 200, "mag": 2.0},
        "_ingested_at": datetime.now(UTC),
    }
    revised = _feature("a", 2.3, 350)  # newer updated

    outcome = await upsert_features(coll, [revised])
    assert outcome.new == 0
    assert outcome.updated == 1
    assert outcome.unchanged == 0
    assert coll.docs["a"]["properties"]["mag"] == 2.3


@pytest.mark.asyncio
async def test_mixed_batch_partitions_correctly() -> None:
    coll = FakeCollection()
    coll.docs["existing-unchanged"] = {
        "_id": "existing-unchanged",
        "properties": {"updated": 500},
    }
    coll.docs["existing-revised"] = {
        "_id": "existing-revised",
        "properties": {"updated": 500},
    }
    features = [
        _feature("new-1", 1.0, 600),
        _feature("new-2", 1.5, 700),
        _feature("existing-unchanged", 2.0, 500),
        _feature("existing-revised", 2.5, 800),
    ]

    outcome = await upsert_features(coll, features)
    assert outcome.new == 2
    assert outcome.updated == 1
    assert outcome.unchanged == 1


@pytest.mark.asyncio
async def test_empty_input_is_no_op() -> None:
    coll = FakeCollection()
    outcome = await upsert_features(coll, [])
    assert outcome.new == outcome.updated == outcome.unchanged == 0
    assert coll.bulk_ops == []
