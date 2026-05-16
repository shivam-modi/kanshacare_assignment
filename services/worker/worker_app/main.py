"""worker-svc — arq consumer for Telegram delivery + summary generation.

In production this image runs two Fly processes:
    [processes]
    worker = "arq app.worker.WorkerSettings"
    health = "uvicorn app.main:app --host 0.0.0.0 --port 8003"

For Phase 1, only the health sidecar exists. The arq WorkerSettings ships in Phase 5.
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI

from kanshacare_shared.app_factory import create_app
from kanshacare_shared.db import MongoClient
from kanshacare_shared.health import HealthState
from kanshacare_shared.logging import get_logger
from kanshacare_shared.redis_client import RedisClient

from .settings import get_settings

settings = get_settings()
log = get_logger(__name__)

mongo = MongoClient(settings)
redis = RedisClient(settings)


@asynccontextmanager
async def lifespan(_app: FastAPI) -> AsyncIterator[None]:
    log.info("worker.boot", env=settings.env)
    try:
        yield
    finally:
        log.info("worker.shutdown")
        await mongo.close()
        await redis.close()


app: FastAPI = create_app(
    service_name="worker-svc",
    settings=settings,
    lifespan=lifespan,
    health_state=HealthState(mongo=mongo, redis=redis),
)


@app.get("/")
async def root() -> dict[str, str]:
    return {"service": "worker-svc", "status": "running"}
