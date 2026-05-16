"""arq WorkerSettings — entry point for `arq worker_app.worker.WorkerSettings`.

Runs as a separate process from the FastAPI health sidecar. Both consume the
same image; the Fly app uses [processes] to run them side by side.

Single worker, single queue (`arq:queue`, the arq default), both functions
registered: arq routes incoming jobs to the right function by name.
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

_settings = get_settings()


async def _on_startup(ctx: dict[str, Any]) -> None:
    configure_logging(
        service_name="worker-svc",
        level=_settings.log_level,
        fmt=_settings.log_format,
    )
    ctx["mongo"] = MongoClient(_settings)
    ctx["http"] = httpx.AsyncClient(timeout=httpx.Timeout(15.0, connect=5.0))
    ctx["limiter"] = TelegramLimiter()
    ctx["tg_token"] = _settings.telegram_bot_token
    ctx["dashboard_base_url"] = _settings.dashboard_base_url
    log.info("worker.startup", env=_settings.env)


async def _on_shutdown(ctx: dict[str, Any]) -> None:
    log.info("worker.shutdown")
    await ctx["http"].aclose()
    await ctx["mongo"].close()


class WorkerSettings:
    """Discovered by `arq worker_app.worker.WorkerSettings`.

    Note: arq reads these as class attributes via __dict__, not via getattr —
    so `redis_settings` MUST be an instance, not a classmethod.
    """

    functions = [send_alert, summary_job]
    on_startup = _on_startup
    on_shutdown = _on_shutdown
    max_jobs = 10
    job_timeout = 60
    keep_result = 3600
    max_tries = 5
    redis_settings = RedisSettings.from_dsn(_settings.redis_url)
