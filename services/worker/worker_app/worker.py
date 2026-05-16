"""arq WorkerSettings — entry point for `arq worker_app.worker.WorkerSettings`.

Runs as a separate process from the FastAPI health sidecar. Both consume the
same image; the Fly app uses [processes] to run them side by side.
"""

from __future__ import annotations

from typing import Any

import httpx
from arq.connections import RedisSettings

from kanshacare_shared.db import MongoClient
from kanshacare_shared.logging import configure_logging, get_logger

from .jobs import send_alert, summary_job
from .rate_limit import TelegramLimiter
from .settings import get_settings

log = get_logger(__name__)


async def _on_startup(ctx: dict[str, Any]) -> None:
    settings = get_settings()
    configure_logging(
        service_name="worker-svc",
        level=settings.log_level,
        fmt=settings.log_format,
    )
    ctx["mongo"] = MongoClient(settings)
    ctx["http"] = httpx.AsyncClient(timeout=httpx.Timeout(15.0, connect=5.0))
    ctx["limiter"] = TelegramLimiter()
    ctx["tg_token"] = settings.telegram_bot_token
    ctx["dashboard_base_url"] = settings.dashboard_base_url
    log.info("worker.startup", env=settings.env)


async def _on_shutdown(ctx: dict[str, Any]) -> None:
    log.info("worker.shutdown")
    await ctx["http"].aclose()
    await ctx["mongo"].close()


class WorkerSettings:
    """Discovered by `arq worker_app.worker.WorkerSettings`.

    The worker consumes from BOTH the alerts queue and the summaries queue —
    arq calls this 'multi-queue', achieved by running one worker per queue or
    by combining functions and using `_queue_name` at enqueue time. We do the
    latter: single worker, both functions registered, queue routed by the
    enqueue call site."""

    functions = [send_alert, summary_job]
    on_startup = _on_startup
    on_shutdown = _on_shutdown
    max_jobs = 10
    job_timeout = 60
    keep_result = 3600
    max_tries = 5

    @classmethod
    def redis_settings(cls) -> RedisSettings:
        return RedisSettings.from_dsn(get_settings().redis_url)
