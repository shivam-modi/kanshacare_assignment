from __future__ import annotations

from fastapi.testclient import TestClient


def test_healthz_returns_ok() -> None:
    from api_app.main import app

    with TestClient(app) as client:
        resp = client.get("/healthz")
        assert resp.status_code == 200
        assert resp.json() == {"status": "ok"}


def test_metrics_endpoint_exists() -> None:
    from api_app.main import app

    with TestClient(app) as client:
        resp = client.get("/metrics")
        assert resp.status_code == 200
        assert "http_requests_total" in resp.text
