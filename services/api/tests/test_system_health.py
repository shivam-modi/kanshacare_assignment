from __future__ import annotations

from datetime import UTC, datetime, timedelta

from kanshacare_shared.db import COLL_META, COLL_SYSTEM_HEALTH


def test_system_health_reflects_recent_polls(client_with_fakes) -> None:
    client, mongo, _, _ = client_with_fakes
    now = datetime.now(UTC)
    rows = [
        {
            "_id": i,
            "ts": now - timedelta(minutes=i),
            "status": "ok",
            "feed": "hour",
            "latency_ms": 100,
        }
        for i in range(5)
    ]
    # Inject one trailing failure.
    rows.insert(
        0,
        {
            "_id": "fail",
            "ts": now,
            "status": "error",
            "feed": "hour",
            "latency_ms": 0,
            "error_class": "UpstreamError",
        },
    )
    for row in rows:
        mongo.collection(COLL_SYSTEM_HEALTH).docs[row["_id"]] = row

    mongo.collection(COLL_META).docs["backfill"] = {
        "_id": "backfill",
        "status": "complete",
        "events_loaded": 1234,
        "completed_at": now,
    }

    r = client.get("/system/health")
    assert r.status_code == 200
    body = r.json()
    assert body["consecutive_failures"] == 1
    assert body["backfill"]["status"] == "complete"
    assert body["backfill"]["events_loaded"] == 1234
    assert body["polls_last_hour"] == 6
    assert 0 < body["success_rate_1h"] < 1


def test_system_health_empty(client_with_fakes) -> None:
    client, _, _, _ = client_with_fakes
    r = client.get("/system/health")
    assert r.status_code == 200
    body = r.json()
    assert body["last_poll_ts"] is None
    assert body["backfill"]["status"] == "pending"
