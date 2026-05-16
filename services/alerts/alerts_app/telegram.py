"""Thin Telegram Bot API client. Verifies the webhook secret on inbound calls
and sends messages. Worker-svc has its own copy of the send path with retries +
rate-limit; this one is for things that absolutely must go out from alerts-svc
itself (e.g. immediate /start acknowledgement)."""

from __future__ import annotations

from typing import Any

import httpx

from kanshacare_shared.errors import UpstreamError
from kanshacare_shared.logging import get_logger
from kanshacare_shared.retry import RetryError, upstream_retry

log = get_logger(__name__)

TG_API_BASE = "https://api.telegram.org"
SECRET_HEADER = "X-Telegram-Bot-Api-Secret-Token"


class TelegramClient:
    def __init__(self, token: str, *, timeout_seconds: float = 10.0) -> None:
        self._token = token
        self._client = httpx.AsyncClient(
            base_url=f"{TG_API_BASE}/bot{token}",
            timeout=httpx.Timeout(timeout_seconds, connect=5.0),
        )

    async def aclose(self) -> None:
        await self._client.aclose()

    async def send_message(
        self,
        *,
        chat_id: int,
        text: str,
        parse_mode: str = "HTML",
        disable_web_page_preview: bool = True,
    ) -> dict[str, Any]:
        payload = {
            "chat_id": chat_id,
            "text": text,
            "parse_mode": parse_mode,
            "disable_web_page_preview": disable_web_page_preview,
        }
        return await self._call("sendMessage", payload)

    async def set_webhook(self, url: str, secret: str) -> dict[str, Any]:
        return await self._call(
            "setWebhook",
            {
                "url": url,
                "secret_token": secret,
                "allowed_updates": ["message"],
                "drop_pending_updates": True,
            },
        )

    async def get_me(self) -> dict[str, Any]:
        return await self._call("getMe", {})

    async def _call(self, method: str, payload: dict[str, Any]) -> dict[str, Any]:
        try:
            async for attempt in upstream_retry(attempts=3, max_wait=4.0):
                with attempt:
                    resp = await self._client.post(f"/{method}", json=payload)
        except RetryError as exc:
            raise UpstreamError(f"telegram {method} unreachable") from exc

        if resp.status_code == 429:
            raise UpstreamError("telegram rate-limited (429)")
        if resp.status_code >= 500:
            raise UpstreamError(f"telegram {method} {resp.status_code}")
        body: dict[str, Any] = resp.json()
        if not body.get("ok"):
            log.warning("telegram.api.not_ok", method=method, body=body)
            raise UpstreamError(f"telegram {method}: {body.get('description')}")
        return body
