"""/healthz (liveness) and /readyz (readiness) endpoints.

* /healthz returns 200 if the process is alive at all. Used by Fly's
  liveness probe — if this 500s, the VM gets restarted.
* /readyz probes downstream deps (Mongo, Redis). Used by the load balancer
  to decide whether to route traffic. A 503 means "I'm alive but not ready,
  don't send me traffic yet."
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from dataclasses import dataclass

from fastapi import FastAPI, Response

from .db import MongoClient
from .redis_client import RedisClient

ReadinessCheck = Callable[[], Awaitable[tuple[str, bool]]]


@dataclass
class HealthState:
    """Each service constructs one of these and passes it to mount_health()."""

    mongo: MongoClient | None = None
    redis: RedisClient | None = None
    extra_checks: list[ReadinessCheck] | None = None


def mount_health(app: FastAPI, state: HealthState) -> None:
    @app.get("/healthz", include_in_schema=False)
    async def healthz() -> dict[str, str]:
        return {"status": "ok"}

    @app.get("/readyz", include_in_schema=False)
    async def readyz(response: Response) -> dict[str, object]:
        checks: dict[str, bool] = {}
        if state.mongo is not None:
            checks["mongo"] = await state.mongo.ping()
        if state.redis is not None:
            checks["redis"] = await state.redis.ping()
        if state.extra_checks:
            for fn in state.extra_checks:
                name, ok = await fn()
                checks[name] = ok
        overall = all(checks.values()) if checks else True
        response.status_code = 200 if overall else 503
        return {"status": "ready" if overall else "not_ready", "checks": checks}
