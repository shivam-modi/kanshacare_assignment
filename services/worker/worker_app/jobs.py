"""arq job functions: send_alert + summary_job.

Both take a `ctx` dict that arq populates with shared resources (mongo, redis,
tg client, limiter). Resources are constructed once in WorkerSettings.on_startup.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Any

import httpx

from kanshacare_shared.db import (
    COLL_ALERTS_LOG,
    COLL_META,
    COLL_SUBSCRIBERS,
    COLL_SYSTEM_HEALTH,
    MongoClient,
)
from kanshacare_shared.logging import get_logger
from kanshacare_shared.metrics import TELEGRAM_DELIVERY

from .aggregations import collect_daily, compute_location_risks
from .messages import alert_message, daily_summary

log = get_logger(__name__)


async def send_alert(
    ctx: dict[str, Any],
    *,
    rule: str,
    dedup_key: str,
    severity: str,
    event_id: str | None,
    location_id: str | None,
    payload: dict[str, Any],
) -> dict[str, Any]:
    """Send a single alert to all active subscribers (or just one for /summary).

    Marks alerts_log.delivery_status to `sent` / `failed` so the daily digest
    can report on it accurately."""
    mongo: MongoClient = ctx["mongo"]
    text = alert_message(
        rule=rule,
        severity=severity,
        payload=payload,
        dashboard_base_url=ctx["dashboard_base_url"],
    )

    subscribers = await _active_subscribers(mongo)
    if not subscribers:
        log.info("worker.send_alert.no_subscribers", rule=rule)
        await _update_alert_status(mongo, dedup_key, "skipped_dedup")
        return {"sent": 0, "failed": 0}

    sent = 0
    failed = 0
    for chat_id in subscribers:
        ok = await _send_one(ctx, chat_id, text, kind="alert")
        sent += int(ok)
        failed += int(not ok)
    status = "sent" if sent > 0 else "failed"
    await _update_alert_status(mongo, dedup_key, status)
    log.info("worker.send_alert.done", rule=rule, sent=sent, failed=failed)
    return {"sent": sent, "failed": failed}


async def summary_job(
    ctx: dict[str, Any],
    *,
    chat_id: int | None,
) -> dict[str, Any]:
    """Generate the 24h digest and send.

    If `chat_id` is None, broadcast to all active subscribers (daily cron path
    and dashboard button). If chat_id is set, send only to that chat (bot
    /summary command path)."""
    mongo: MongoClient = ctx["mongo"]
    payload = await collect_daily(mongo)
    risks = await compute_location_risks(mongo, payload["events"])
    health = await _current_health(mongo)

    text = daily_summary(
        window_label="last 24 hours",
        totals=payload["totals"],
        mag_bands=payload["mag_bands"],
        top_regions=payload["top_regions"],
        fired_alerts=payload["fired_alerts"],
        locations=risks,
        health=health,
        dashboard_base_url=ctx["dashboard_base_url"],
    )

    if chat_id is not None:
        ok = await _send_one(ctx, chat_id, text, kind="summary")
        return {"sent": int(ok), "failed": int(not ok)}

    subscribers = await _active_subscribers(mongo)
    sent = 0
    failed = 0
    for cid in subscribers:
        ok = await _send_one(ctx, cid, text, kind="summary")
        sent += int(ok)
        failed += int(not ok)
    log.info("worker.summary_job.done", sent=sent, failed=failed)
    return {"sent": sent, "failed": failed}


# ----- helpers ---------------------------------------------------------------


async def _send_one(ctx: dict[str, Any], chat_id: int, text: str, *, kind: str) -> bool:
    """Send a single Telegram message respecting rate limits. Best-effort —
    failures are logged and metrics incremented; arq's retry mechanism handles
    transient errors at the job level."""
    limiter = ctx["limiter"]
    await limiter.acquire(chat_id)
    tg_token: str = ctx["tg_token"]
    if not tg_token:
        log.warning("worker.send.no_token")
        TELEGRAM_DELIVERY.labels(kind, "skipped").inc()
        return False
    client: httpx.AsyncClient = ctx["http"]
    try:
        resp = await client.post(
            f"https://api.telegram.org/bot{tg_token}/sendMessage",
            json={
                "chat_id": chat_id,
                "text": text,
                "parse_mode": "HTML",
                "disable_web_page_preview": True,
            },
        )
    except httpx.HTTPError as exc:
        log.warning("worker.send.http_error", chat_id=chat_id, error=str(exc))
        TELEGRAM_DELIVERY.labels(kind, "network_error").inc()
        return False

    if resp.status_code == 429:
        # Honor Retry-After if Telegram tells us to back off — arq's retry will pick it up.
        TELEGRAM_DELIVERY.labels(kind, "rate_limited").inc()
        return False
    if resp.status_code >= 500:
        TELEGRAM_DELIVERY.labels(kind, "upstream_5xx").inc()
        return False
    if not resp.is_success:
        TELEGRAM_DELIVERY.labels(kind, f"http_{resp.status_code}").inc()
        return False
    body = resp.json()
    if not body.get("ok"):
        TELEGRAM_DELIVERY.labels(kind, "not_ok").inc()
        return False
    TELEGRAM_DELIVERY.labels(kind, "ok").inc()
    return True


async def _active_subscribers(mongo: MongoClient) -> list[int]:
    cursor = mongo.collection(COLL_SUBSCRIBERS).find({"stopped_at": None})
    return [int(doc["_id"]) async for doc in cursor]


async def _update_alert_status(mongo: MongoClient, dedup_key: str, status: str) -> None:
    await mongo.collection(COLL_ALERTS_LOG).update_one(
        {"dedup_key": dedup_key},
        {"$set": {"delivery_status": status, "delivered_at": datetime.now(UTC)}},
    )


async def _current_health(mongo: MongoClient) -> dict[str, Any]:
    coll = mongo.collection(COLL_SYSTEM_HEALTH)
    now = datetime.now(UTC)
    one_hour_ago = now - timedelta(hours=1)
    total = await coll.count_documents({"ts": {"$gte": one_hour_ago}})
    ok = await coll.count_documents({"ts": {"$gte": one_hour_ago}, "status": "ok"})
    recent = [doc async for doc in coll.find().sort("ts", -1).limit(50)]
    streak = 0
    for doc in recent:
        if doc.get("status") == "ok":
            break
        streak += 1
    bf = await mongo.collection(COLL_META).find_one({"_id": "backfill"})
    return {
        "success_rate_1h": (ok / total) if total else None,
        "consecutive_failures": streak,
        "backfill": {"status": (bf or {}).get("status", "pending")},
    }
