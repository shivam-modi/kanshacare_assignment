"""Source-silence detector. Runs as a periodic job — not change-stream-driven.

If the most recent `system_health` row with status=ok is older than the
threshold, fire a silence alert (deduped per hour bucket so a long outage
doesn't spam Telegram every 2 minutes).
"""

from __future__ import annotations

from datetime import UTC, datetime

from arq.connections import ArqRedis

from kanshacare_shared.config import BaseAppSettings
from kanshacare_shared.db import COLL_SYSTEM_HEALTH, MongoClient
from kanshacare_shared.logging import get_logger

from .dispatcher import dispatch
from .rules import make_silence_candidate

log = get_logger(__name__)


async def check_silence(
    *,
    settings: BaseAppSettings,
    mongo: MongoClient,
    arq: ArqRedis,
) -> bool:
    """Return True if a silence alert was fired this cycle."""
    coll = mongo.collection(COLL_SYSTEM_HEALTH)
    last_ok = await coll.find_one({"status": "ok"}, sort=[("ts", -1)])
    if last_ok is None:
        # We've never had a successful poll. Wait for at least one before alerting —
        # otherwise we'd page on first boot, before backfill even started.
        return False
    last_ok_ts = last_ok.get("ts")
    if not isinstance(last_ok_ts, datetime):
        return False
    age = datetime.now(UTC) - last_ok_ts.astimezone(UTC)
    minutes = age.total_seconds() / 60.0
    if minutes < settings.silence_threshold_minutes:
        return False

    candidate = make_silence_candidate(age_minutes=minutes)
    fired = await dispatch(candidate, mongo=mongo, arq=arq)
    if fired:
        log.warning("alerts.silence.fired", minutes_since_last_ok=round(minutes, 1))
    return fired
