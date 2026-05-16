"""Source-silence detection."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest

from alerts_app.silence import check_silence
from alerts_app.settings import get_settings
from kanshacare_shared.db import COLL_SYSTEM_HEALTH

from ._fakes import FakeArq, FakeMongoClient


@pytest.mark.asyncio
async def test_no_health_rows_doesnt_alert() -> None:
    mongo = FakeMongoClient()
    arq = FakeArq()
    fired = await check_silence(settings=get_settings(), mongo=mongo, arq=arq)  # type: ignore[arg-type]
    assert fired is False


@pytest.mark.asyncio
async def test_recent_success_doesnt_alert() -> None:
    settings = get_settings()
    mongo = FakeMongoClient()
    arq = FakeArq()
    mongo.collection(COLL_SYSTEM_HEALTH).docs[1] = {
        "_id": 1,
        "ts": datetime.now(UTC) - timedelta(minutes=2),
        "status": "ok",
    }
    fired = await check_silence(settings=settings, mongo=mongo, arq=arq)  # type: ignore[arg-type]
    assert fired is False


@pytest.mark.asyncio
async def test_stale_success_does_alert() -> None:
    settings = get_settings()
    mongo = FakeMongoClient()
    arq = FakeArq()
    # Older than 10-min threshold.
    mongo.collection(COLL_SYSTEM_HEALTH).docs[1] = {
        "_id": 1,
        "ts": datetime.now(UTC) - timedelta(minutes=20),
        "status": "ok",
    }
    fired = await check_silence(settings=settings, mongo=mongo, arq=arq)  # type: ignore[arg-type]
    assert fired is True
    # Second consecutive call within the same hour should dedup.
    fired_again = await check_silence(settings=settings, mongo=mongo, arq=arq)  # type: ignore[arg-type]
    assert fired_again is False
