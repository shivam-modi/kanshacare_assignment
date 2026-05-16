"""ingestion-svc — backfill on first boot, poll every 60s, write to Mongo.

The whole service is asyncio: the scheduler, the USGS HTTP client, and the
Mongo driver (motor) are all async. APScheduler runs jobs as coroutines on
the FastAPI event loop, so no separate thread.
"""

from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.interval import IntervalTrigger
from fastapi import FastAPI

from kanshacare_shared.app_factory import create_app
from kanshacare_shared.db import MongoClient, ensure_indexes
from kanshacare_shared.health import HealthState
from kanshacare_shared.logging import get_logger
from kanshacare_shared.redis_client import RedisClient
from kanshacare_shared.usgs import USGSClient

from .backfill import run_backfill
from .poller import run_poll_cycle
from .settings import get_settings

settings = get_settings()
log = get_logger(__name__)

mongo = MongoClient(settings)
redis = RedisClient(settings)
usgs = USGSClient(
    hour_url=settings.usgs_hour_url,
    month_url=settings.usgs_month_url,
    timeout_seconds=settings.usgs_request_timeout_seconds,
)
scheduler = AsyncIOScheduler(timezone="UTC")


# Strong references to background tasks so the asyncio loop's GC doesn't drop them mid-run.
_background_tasks: set[asyncio.Task[None]] = set()


def _spawn(coro: object, *, name: str) -> asyncio.Task[None]:
    task = asyncio.create_task(coro, name=name)  # type: ignore[arg-type]
    _background_tasks.add(task)
    task.add_done_callback(_background_tasks.discard)
    return task


async def _scheduled_poll() -> None:
    """Wrapper for the scheduler job. Errors are absorbed inside run_poll_cycle
    but we double-belt-and-braces here so apscheduler can never see an exception."""
    try:
        await run_poll_cycle(usgs=usgs, mongo=mongo, feed="hour")
    except Exception:
        log.exception("ingestion.scheduled_poll.unhandled")


async def _kickoff_backfill() -> None:
    """Run backfill as a background task so app startup isn't blocked.

    The poller will start in parallel; both share the same upsert path so they
    cannot corrupt each other (Mongo upsert is atomic per-doc)."""
    try:
        await run_backfill(usgs=usgs, mongo=mongo, force=False)
    except Exception:
        log.exception("ingestion.backfill.unhandled")


@asynccontextmanager
async def lifespan(_app: FastAPI) -> AsyncIterator[None]:
    log.info(
        "ingestion.boot",
        env=settings.env,
        db=settings.mongo_db,
        poll_interval_s=settings.usgs_poll_interval_seconds,
        backfill_on_boot=settings.usgs_backfill_on_boot,
    )
    try:
        await ensure_indexes(mongo)
    except Exception as exc:
        log.warning("ingestion.indexes.deferred", error=str(exc))

    backfill_task: asyncio.Task[None] | None = None
    if settings.usgs_backfill_on_boot:
        backfill_task = _spawn(_kickoff_backfill(), name="ingestion-backfill")

    scheduler.add_job(
        _scheduled_poll,
        trigger=IntervalTrigger(seconds=settings.usgs_poll_interval_seconds),
        id="usgs-hour-poll",
        name="USGS hourly feed poll",
        max_instances=1,  # never overlap a slow cycle with a new one
        coalesce=True,  # if we missed runs (e.g. paused), only run once
        next_run_time=None,  # the first run will be triggered explicitly below
    )
    scheduler.start()

    # Fire one poll immediately so the dashboard has data even before the
    # first 60s tick — and so we record a system_health row promptly.
    _spawn(_scheduled_poll(), name="ingestion-initial-poll")

    log.info("ingestion.scheduler.started")
    try:
        yield
    finally:
        log.info("ingestion.shutdown")
        scheduler.shutdown(wait=False)
        if backfill_task is not None and not backfill_task.done():
            backfill_task.cancel()
        await usgs.aclose()
        await mongo.close()
        await redis.close()


app: FastAPI = create_app(
    service_name="ingestion-svc",
    settings=settings,
    lifespan=lifespan,
    health_state=HealthState(mongo=mongo, redis=redis),
)


@app.get("/")
async def root() -> dict[str, str]:
    return {"service": "ingestion-svc", "status": "running"}
