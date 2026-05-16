"""FastAPI app factory — wires logging, middleware, metrics, health endpoints.

Each service uses this so the cross-cutting concerns are uniform:

    from kanshacare_shared.app_factory import create_app
    app = create_app(service_name="api-svc", settings=settings, lifespan=lifespan)
"""

from __future__ import annotations

from collections.abc import Callable
from contextlib import AbstractAsyncContextManager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from .config import BaseAppSettings
from .health import HealthState, mount_health
from .logging import configure_logging
from .metrics import PrometheusMiddleware, mount_metrics
from .middleware import RequestContextMiddleware, install_exception_handlers

Lifespan = Callable[[FastAPI], AbstractAsyncContextManager[None]]


def create_app(
    *,
    service_name: str,
    settings: BaseAppSettings,
    lifespan: Lifespan | None = None,
    health_state: HealthState | None = None,
    enable_cors: bool = False,
) -> FastAPI:
    """Standard Kansha Care FastAPI app.

    Logging is configured before the app is constructed so import-time logs are formatted.
    """
    configure_logging(
        service_name=service_name,
        level=settings.log_level,
        fmt=settings.log_format,
    )

    app = FastAPI(
        title=f"Kansha Care — {service_name}",
        version="0.1.0",
        lifespan=lifespan,
    )

    if enable_cors:
        app.add_middleware(
            CORSMiddleware,
            allow_origins=settings.cors_origins_list,
            allow_credentials=True,
            allow_methods=["*"],
            allow_headers=["*"],
            expose_headers=["X-Request-ID"],
        )

    # Order matters: PrometheusMiddleware should wrap RequestContextMiddleware
    # so timing includes everything, but request_id binding happens first.
    app.add_middleware(PrometheusMiddleware)
    app.add_middleware(RequestContextMiddleware)

    install_exception_handlers(app)
    mount_metrics(app)
    mount_health(app, health_state or HealthState())

    return app
