"""Dispatcher dedup behaviour."""

from __future__ import annotations

import pytest

from alerts_app.dispatcher import dispatch
from alerts_app.rules import AlertCandidate
from kanshacare_shared.db import COLL_ALERTS_LOG

from ._fakes import FakeArq, FakeMongoClient


def _make_cand(dedup: str = "x") -> AlertCandidate:
    return AlertCandidate(
        rule="high_severity_global",
        dedup_key=dedup,
        severity="warning",
        event_id="e1",
        location_id=None,
        payload={"mag": 5.0},
    )


@pytest.mark.asyncio
async def test_first_dispatch_enqueues_and_logs() -> None:
    mongo = FakeMongoClient()
    arq = FakeArq()
    fired = await dispatch(_make_cand(), mongo=mongo, arq=arq)  # type: ignore[arg-type]
    assert fired is True
    assert len(arq.jobs) == 1
    assert len(mongo.collection(COLL_ALERTS_LOG).docs) == 1


@pytest.mark.asyncio
async def test_duplicate_dispatch_is_suppressed() -> None:
    mongo = FakeMongoClient()
    arq = FakeArq()
    await dispatch(_make_cand("dup"), mongo=mongo, arq=arq)  # type: ignore[arg-type]
    fired = await dispatch(_make_cand("dup"), mongo=mongo, arq=arq)  # type: ignore[arg-type]
    assert fired is False
    # First dispatch enqueued once; the second was suppressed before enqueue.
    assert len(arq.jobs) == 1
