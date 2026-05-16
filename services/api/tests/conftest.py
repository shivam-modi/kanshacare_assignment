"""Service-root onto sys.path + shared fixtures for api-svc tests."""

from __future__ import annotations

import sys
from collections.abc import Iterator
from pathlib import Path

import pytest

_SERVICE_ROOT = Path(__file__).resolve().parent.parent
if str(_SERVICE_ROOT) not in sys.path:
    sys.path.insert(0, str(_SERVICE_ROOT))


@pytest.fixture
def client_with_fakes() -> Iterator[tuple[object, object, object, object]]:
    """Construct the FastAPI app with fake Mongo / arq / Geocoder injected.

    Returns: (TestClient, FakeMongoClient, FakeArq, FakeGeocoder)
    """
    from api_app.main import app
    from api_app.routers import summaries
    from api_app.settings import get_settings
    from fastapi.testclient import TestClient
    from ._fakes import FakeArq, FakeGeocoder, FakeMongoClient

    fake_mongo = FakeMongoClient()
    fake_arq = FakeArq()
    fake_geocoder = FakeGeocoder()
    settings = get_settings()

    # Pre-wire app.state so endpoints don't depend on the real lifespan.
    app.state.mongo = fake_mongo
    app.state.arq = fake_arq
    app.state.geocoder = fake_geocoder
    app.state.settings = settings

    # Rate-limit state is module-level; reset between tests so neighbouring
    # tests don't see each other's quota usage.
    summaries.limiter.reset()

    client = TestClient(app)
    yield client, fake_mongo, fake_arq, fake_geocoder
    client.close()
