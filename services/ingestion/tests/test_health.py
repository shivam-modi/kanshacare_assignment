"""Smoke test: app constructs, /healthz returns 200 without external deps."""

from __future__ import annotations

from fastapi.testclient import TestClient


def test_healthz_returns_ok() -> None:
    # Import inside the test so module-level Mongo/Redis clients are constructed lazily
    # — we don't actually connect on construction, only on operations.
    from ingestion_app.main import app

    with TestClient(app) as client:
        resp = client.get("/healthz")
        assert resp.status_code == 200
        assert resp.json() == {"status": "ok"}


def test_root_returns_service_metadata() -> None:
    from ingestion_app.main import app

    with TestClient(app) as client:
        resp = client.get("/")
        assert resp.status_code == 200
        assert resp.json()["service"] == "ingestion-svc"
