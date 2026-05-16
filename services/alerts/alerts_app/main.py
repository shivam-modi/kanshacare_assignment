"""alerts-svc — change-stream rule engine + Telegram webhook + silence/daily schedulers."""

from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger
from apscheduler.triggers.interval import IntervalTrigger
from arq import create_pool
from arq.connections import RedisSettings
from fastapi import FastAPI

from kanshacare_shared.app_factory import create_app
from kanshacare_shared.db import MongoClient, ensure_indexes
from kanshacare_shared.health import HealthState
from kanshacare_shared.logging import get_logger
from kanshacare_shared.redis_client import RedisClient

from .change_stream import EventConsumer
from .settings import get_settings
from .silence import check_silence
from .telegram import TelegramClient
from .webhook import build_router

settings = get_settings()
log = get_logger(__name__)

mongo = MongoClient(settings)
redis = RedisClient(settings)
scheduler = AsyncIOScheduler(timezone="UTC")


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    log.info("alerts.boot", env=settings.env)
    try:
        await ensure_indexes(mongo)
    except Exception as exc:
        log.warning("alerts.indexes.deferred", error=str(exc))

    arq_pool = await create_pool(RedisSettings.from_dsn(settings.redis_url))
    tg = TelegramClient(settings.telegram_bot_token) if settings.telegram_bot_token else None
    consumer = EventConsumer(mongo=mongo, arq=arq_pool, settings=settings)
    consumer.start()

    # Source-silence check every N seconds.
    scheduler.add_job(
        check_silence,
        kwargs={"settings": settings, "mongo": mongo, "arq": arq_pool},
        trigger=IntervalTrigger(seconds=settings.silence_check_interval_seconds),
        id="silence-check",
        max_instances=1,
        coalesce=True,
    )

    # Daily summary cron — enqueues the same job that the dashboard button does.
    async def _enqueue_daily_summary() -> None:
        try:
            await arq_pool.enqueue_job(
                "summary_job",
                chat_id=None,  # broadcast
                _queue_name="kanshacare:summaries",
            )
            log.info("alerts.daily_summary.enqueued")
        except Exception:
            log.exception("alerts.daily_summary.enqueue_failed")

    scheduler.add_job(
        _enqueue_daily_summary,
        trigger=CronTrigger(
            hour=settings.daily_summary_hour_utc,
            minute=settings.daily_summary_minute,
        ),
        id="daily-summary",
        max_instances=1,
        coalesce=True,
    )
    scheduler.start()

    # Mount the Telegram webhook router if we have a token.
    if tg is not None:
        app.include_router(build_router(settings=settings, mongo=mongo, arq=arq_pool, tg=tg))

    app.state.settings = settings
    app.state.mongo = mongo
    app.state.redis = redis
    app.state.arq = arq_pool
    app.state.tg = tg

    log.info("alerts.scheduler.started")
    try:
        yield
    finally:
        log.info("alerts.shutdown")
        scheduler.shutdown(wait=False)
        await consumer.stop()
        if tg is not None:
            await tg.aclose()
        await arq_pool.close()
        await mongo.close()
        await redis.close()


app: FastAPI = create_app(
    service_name="alerts-svc",
    settings=settings,
    lifespan=lifespan,
    health_state=HealthState(mongo=mongo, redis=redis),
)


@app.get("/")
async def root() -> dict[str, str]:
    return {"service": "alerts-svc", "status": "running"}
