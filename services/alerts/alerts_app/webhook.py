"""Telegram webhook + bot command handlers.

The webhook signature is verified via the `X-Telegram-Bot-Api-Secret-Token`
header (set when we register the webhook). Commands handled:
  * /start  — register the chat; reply with locations + thresholds
  * /stop   — mark subscriber stopped
  * /summary — enqueue an on-demand summary for THIS chat only
  * /locations — show current locations + thresholds
"""

from __future__ import annotations

from typing import Any

from arq.connections import ArqRedis
from fastapi import APIRouter, Header, HTTPException, Request

from kanshacare_shared.config import BaseAppSettings
from kanshacare_shared.db import COLL_LOCATIONS, MongoClient
from kanshacare_shared.logging import get_logger

from . import subscribers
from .telegram import SECRET_HEADER, TelegramClient

log = get_logger(__name__)


def build_router(
    *,
    settings: BaseAppSettings,
    mongo: MongoClient,
    arq: ArqRedis,
    tg: TelegramClient,
) -> APIRouter:
    router = APIRouter(prefix="/telegram", tags=["telegram"])

    @router.post("/webhook")
    async def webhook(
        request: Request,
        x_telegram_bot_api_secret_token: str | None = Header(default=None, alias=SECRET_HEADER),
    ) -> dict[str, str]:
        # Reject anything not signed with our shared secret.
        expected = settings.telegram_webhook_secret
        if expected and x_telegram_bot_api_secret_token != expected:
            log.warning("telegram.webhook.bad_secret")
            raise HTTPException(status_code=401, detail="bad secret")

        update = await request.json()
        message = update.get("message") or update.get("edited_message")
        if not message:
            return {"status": "ignored"}

        chat = message.get("chat", {})
        chat_id = chat.get("id")
        if chat_id is None:
            return {"status": "ignored"}

        text = (message.get("text") or "").strip()
        username = (message.get("from") or {}).get("username")
        first_name = (message.get("from") or {}).get("first_name")

        await subscribers.touch(mongo, chat_id=chat_id)
        await _dispatch_command(
            text,
            chat_id=chat_id,
            username=username,
            first_name=first_name,
            mongo=mongo,
            arq=arq,
            tg=tg,
            settings=settings,
        )
        return {"status": "ok"}

    return router


async def _dispatch_command(
    text: str,
    *,
    chat_id: int,
    username: str | None,
    first_name: str | None,
    mongo: MongoClient,
    arq: ArqRedis,
    tg: TelegramClient,
    settings: BaseAppSettings,
) -> None:
    cmd = text.split(maxsplit=1)[0].lower() if text else ""

    if cmd in ("/start", "/help"):
        await subscribers.register(mongo, chat_id=chat_id, username=username, first_name=first_name)
        await tg.send_message(
            chat_id=chat_id,
            text=_welcome_text(settings, await _list_locations(mongo)),
        )
        return

    if cmd == "/stop":
        await subscribers.mark_stopped(mongo, chat_id=chat_id)
        await tg.send_message(
            chat_id=chat_id,
            text="🛑 You won't receive further alerts. Send /start to resume.",
        )
        return

    if cmd == "/summary":
        await arq.enqueue_job(
            "summary_job",
            chat_id=chat_id,
            _queue_name="kanshacare:summaries",
        )
        await tg.send_message(
            chat_id=chat_id, text="⏳ Generating summary — should arrive in a few seconds."
        )
        return

    if cmd == "/locations":
        await tg.send_message(chat_id=chat_id, text=_format_locations(await _list_locations(mongo)))
        return

    # Anything else — show help.
    await tg.send_message(
        chat_id=chat_id,
        text="Commands: /start, /summary, /locations, /stop",
    )


async def _list_locations(mongo: MongoClient) -> list[dict[str, Any]]:
    cursor = mongo.collection(COLL_LOCATIONS).find().sort("created_at", 1)
    return [doc async for doc in cursor]


def _welcome_text(settings: BaseAppSettings, locations: list[dict[str, Any]]) -> str:
    lines = [
        "<b>Kansha Care</b> — earthquake telemetry.",
        "",
        f"You'll receive alerts for events ≥ M{settings.alert_global_mag_threshold:.1f} globally, "
        f"≥ M{settings.alert_near_mag_threshold:.1f} within "
        f"{int(settings.alert_near_radius_km)} km of any registered location, "
        f"swarms (≥ {settings.swarm_min_events} quakes in {settings.swarm_window_minutes} min / "
        f"{int(settings.swarm_radius_km)} km), and source silence "
        f"(> {settings.silence_threshold_minutes} min).",
        "",
        "Commands: /summary · /locations · /stop",
        "",
        _format_locations(locations),
    ]
    return "\n".join(lines)


def _format_locations(locations: list[dict[str, Any]]) -> str:
    if not locations:
        return "No locations configured yet. Add some in the dashboard."
    lines = ["<b>Active locations:</b>"]
    for loc in locations:
        lines.append(f"• {loc.get('name')} (r={int(loc.get('radius_km', 0))} km)")
    return "\n".join(lines)
