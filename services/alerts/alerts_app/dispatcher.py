"""Alert dispatch: dedup against alerts_log + enqueue delivery on the arq queue."""

from __future__ import annotations

from datetime import UTC, datetime

from arq.connections import ArqRedis
from pymongo.errors import DuplicateKeyError

from kanshacare_shared.db import COLL_ALERTS_LOG, MongoClient
from kanshacare_shared.logging import get_logger
from kanshacare_shared.metrics import ALERTS_FIRED, ALERTS_SUPPRESSED

from .rules import AlertCandidate

log = get_logger(__name__)

DELIVERY_QUEUE = "kanshacare:alerts"
DELIVERY_JOB = "send_alert"


async def dispatch(
    candidate: AlertCandidate,
    *,
    mongo: MongoClient,
    arq: ArqRedis,
) -> bool:
    """Insert dedup record + enqueue delivery. Returns True if newly fired,
    False if suppressed by an existing dedup key.

    The dedup is enforced by a unique index on `alerts_log.dedup_key`. We catch
    the DuplicateKeyError to know whether this was a real first-fire."""
    coll = mongo.collection(COLL_ALERTS_LOG)
    doc = {
        "rule": candidate.rule,
        "dedup_key": candidate.dedup_key,
        "severity": candidate.severity,
        "event_id": candidate.event_id,
        "location_id": candidate.location_id,
        "payload": candidate.payload,
        "delivery_status": "queued",
        "fired_at": datetime.now(UTC),
        "_schema_version": 1,
    }
    try:
        await coll.insert_one(doc)
    except DuplicateKeyError:
        ALERTS_SUPPRESSED.labels(candidate.rule).inc()
        log.info("alerts.dedup", rule=candidate.rule, dedup_key=candidate.dedup_key)
        return False

    await arq.enqueue_job(
        DELIVERY_JOB,
        rule=candidate.rule,
        dedup_key=candidate.dedup_key,
        severity=candidate.severity,
        event_id=candidate.event_id,
        location_id=candidate.location_id,
        payload=candidate.payload,
        _queue_name=DELIVERY_QUEUE,
    )
    ALERTS_FIRED.labels(candidate.rule, candidate.severity).inc()
    log.info(
        "alerts.fired",
        rule=candidate.rule,
        severity=candidate.severity,
        dedup_key=candidate.dedup_key,
        event_id=candidate.event_id,
    )
    return True
