from __future__ import annotations

from fastapi.testclient import TestClient


def test_healthz_returns_ok() -> None:
    from worker_app.main import app

    with TestClient(app) as client:
        resp = client.get("/healthz")
        assert resp.status_code == 200
        assert resp.json() == {"status": "ok"}
