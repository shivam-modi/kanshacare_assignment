"""Prometheus metrics registry + standard HTTP middleware metrics."""

from __future__ import annotations

import time
from collections.abc import Awaitable, Callable

from fastapi import FastAPI, Request, Response
from prometheus_client import (
    CONTENT_TYPE_LATEST,
    CollectorRegistry,
    Counter,
    Histogram,
    generate_latest,
)
from starlette.middleware.base import BaseHTTPMiddleware

# Process-global registry so all metrics from a service appear at /metrics.
REGISTRY = CollectorRegistry()

HTTP_REQUESTS_TOTAL = Counter(
    "http_requests_total",
    "Total HTTP requests handled by this service.",
    labelnames=("method", "path", "status"),
    registry=REGISTRY,
)
HTTP_REQUEST_DURATION_SECONDS = Histogram(
    "http_request_duration_seconds",
    "Request latency (seconds).",
    labelnames=("method", "path"),
    buckets=(0.005, 0.01, 0.025, 0.05, 0.1, 0.25, 0.5, 1.0, 2.5, 5.0, 10.0),
    registry=REGISTRY,
)

# Domain metrics — registered here so any service can import + use them.
USGS_POLL_LATENCY = Histogram(
    "usgs_poll_latency_seconds",
    "Latency of a single USGS feed fetch + parse cycle.",
    labelnames=("feed",),
    registry=REGISTRY,
)
USGS_POLL_RESULT = Counter(
    "usgs_poll_result_total",
    "Outcomes of USGS poll attempts.",
    labelnames=("feed", "status"),
    registry=REGISTRY,
)
EVENTS_INGESTED = Counter(
    "events_ingested_total",
    "Earthquake events written to Mongo.",
    labelnames=("kind",),  # "new" | "updated" | "quarantined"
    registry=REGISTRY,
)
ALERTS_FIRED = Counter(
    "alerts_fired_total",
    "Alert rule firings (after dedup).",
    labelnames=("rule", "severity"),
    registry=REGISTRY,
)
ALERTS_SUPPRESSED = Counter(
    "alerts_suppressed_total",
    "Alert rule triggerings suppressed because of dedup.",
    labelnames=("rule",),
    registry=REGISTRY,
)
TELEGRAM_DELIVERY = Counter(
    "telegram_delivery_total",
    "Telegram API send outcomes.",
    labelnames=("kind", "status"),
    registry=REGISTRY,
)


class PrometheusMiddleware(BaseHTTPMiddleware):
    """Counts requests and observes latency. Path label is the *route template*
    when available, so high-cardinality URLs don't blow up the registry."""

    async def dispatch(
        self,
        request: Request,
        call_next: Callable[[Request], Awaitable[Response]],
    ) -> Response:
        start = time.perf_counter()
        response: Response = await call_next(request)
        duration = time.perf_counter() - start
        route = request.scope.get("route")
        path_label = getattr(route, "path", request.url.path)
        HTTP_REQUEST_DURATION_SECONDS.labels(request.method, path_label).observe(duration)
        HTTP_REQUESTS_TOTAL.labels(request.method, path_label, str(response.status_code)).inc()
        return response


def mount_metrics(app: FastAPI) -> None:
    """Expose /metrics on the given FastAPI app."""

    @app.get("/metrics", include_in_schema=False)
    def metrics() -> Response:
        return Response(generate_latest(REGISTRY), media_type=CONTENT_TYPE_LATEST)
