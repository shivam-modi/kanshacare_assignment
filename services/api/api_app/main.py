"""api-svc — REST + SSE for the dashboard. Wires routers, geocoder, arq pool."""

from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from arq import create_pool
from arq.connections import RedisSettings
from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
from slowapi.errors import RateLimitExceeded
from slowapi.middleware import SlowAPIMiddleware

from kanshacare_shared.app_factory import create_app
from kanshacare_shared.db import MongoClient
from kanshacare_shared.geocoding import get_geocoder
from kanshacare_shared.health import HealthState
from kanshacare_shared.logging import get_logger
from kanshacare_shared.redis_client import RedisClient

from .routers import events, locations, summaries, system
from .settings import get_settings

settings = get_settings()
log = get_logger(__name__)

mongo = MongoClient(settings)
redis = RedisClient(settings)


@asynccontextmanager
async def lifespan(fastapi_app: FastAPI) -> AsyncIterator[None]:
    log.info("api.boot", env=settings.env)
    arq_pool = await create_pool(RedisSettings.from_dsn(settings.redis_url))
    geocoder = get_geocoder(settings, mongo)
    fastapi_app.state.settings = settings
    fastapi_app.state.mongo = mongo
    fastapi_app.state.redis = redis
    fastapi_app.state.arq = arq_pool
    fastapi_app.state.geocoder = geocoder
    try:
        yield
    finally:
        log.info("api.shutdown")
        await geocoder.aclose()
        await arq_pool.close()
        await mongo.close()
        await redis.close()


app: FastAPI = create_app(
    service_name="api-svc",
    settings=settings,
    lifespan=lifespan,
    health_state=HealthState(mongo=mongo, redis=redis),
    enable_cors=True,
)

# slowapi setup — uses the limiter defined in routers/summaries.py
app.state.limiter = summaries.limiter
app.add_middleware(SlowAPIMiddleware)


@app.exception_handler(RateLimitExceeded)
async def _rate_limit_handler(_request: Request, exc: RateLimitExceeded) -> JSONResponse:
    return JSONResponse(
        status_code=429,
        content={"error": {"code": "rate_limited", "message": str(exc.detail)}},
    )


app.include_router(events.router)
app.include_router(locations.router)
app.include_router(system.router)
app.include_router(summaries.router)


@app.get("/")
async def root() -> dict[str, str]:
    return {"service": "api-svc", "status": "running"}
