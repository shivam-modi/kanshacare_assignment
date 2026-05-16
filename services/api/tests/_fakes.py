"""In-memory test doubles for Mongo + arq + Geocoder.

Just enough behaviour to exercise api-svc's read paths and CRUD. Operations
not used by the endpoints are intentionally omitted — adding them risks
hiding bugs that real Mongo would catch.
"""

from __future__ import annotations

import operator
from datetime import UTC, datetime
from types import SimpleNamespace
from typing import Any

from kanshacare_shared.geo import LatLon, haversine_km
from kanshacare_shared.geocoding.base import GeocodeQuery
from kanshacare_shared.models import GeocodeResult

# ============================================================================
# Mongo fakes
# ============================================================================


class _FakeCursor:
    """Supports sort + limit + async iteration."""

    def __init__(self, docs: list[dict[str, Any]]) -> None:
        self._docs = docs
        self._sort_field: str | None = None
        self._sort_dir: int = 1
        self._limit: int | None = None

    def sort(self, field: str, direction: int = 1) -> _FakeCursor:
        self._sort_field = field
        self._sort_dir = direction
        return self

    def limit(self, n: int) -> _FakeCursor:
        self._limit = n
        return self

    def _materialise(self) -> list[dict[str, Any]]:
        docs = list(self._docs)
        if self._sort_field:

            def keyfn(d: dict[str, Any]) -> Any:
                # support dotted nested keys ("properties.time")
                cur: Any = d
                for part in self._sort_field.split("."):  # type: ignore[union-attr]
                    cur = (cur or {}).get(part) if isinstance(cur, dict) else None
                return cur if cur is not None else 0

            docs.sort(key=keyfn, reverse=self._sort_dir < 0)
        if self._limit is not None:
            docs = docs[: self._limit]
        return docs

    def __aiter__(self) -> _FakeCursor:
        self._iter = iter(self._materialise())
        return self

    async def __anext__(self) -> dict[str, Any]:
        try:
            return next(self._iter)
        except StopIteration as exc:
            raise StopAsyncIteration from exc


class FakeCollection:
    """Subset of motor.AsyncIOMotorCollection used by api-svc."""

    def __init__(self) -> None:
        self.docs: dict[Any, dict[str, Any]] = {}

    # --- reads -----------------------------------------------------------
    def find(
        self,
        filt: dict[str, Any] | None = None,
        projection: dict[str, Any] | None = None,
    ) -> _FakeCursor:
        filt = filt or {}
        matched = [d for d in self.docs.values() if self._match(d, filt)]
        return _FakeCursor(matched)

    async def find_one(
        self,
        filt: dict[str, Any] | None = None,
        sort: list[tuple[str, int]] | None = None,
    ) -> dict[str, Any] | None:
        filt = filt or {}
        candidates = [d for d in self.docs.values() if self._match(d, filt)]
        if sort:
            field, direction = sort[0]

            def keyfn(d: dict[str, Any]) -> Any:
                cur: Any = d
                for part in field.split("."):
                    cur = (cur or {}).get(part) if isinstance(cur, dict) else None
                return cur if cur is not None else 0

            candidates.sort(key=keyfn, reverse=direction < 0)
        return candidates[0] if candidates else None

    async def count_documents(self, filt: dict[str, Any]) -> int:
        return sum(1 for d in self.docs.values() if self._match(d, filt))

    def aggregate(self, pipeline: list[dict[str, Any]]) -> _FakeCursor:
        # Minimal aggregate support: $match → $group { _id, n: $sum: 1 }
        docs = list(self.docs.values())
        for stage in pipeline:
            if "$match" in stage:
                docs = [d for d in docs if self._match(d, stage["$match"])]
            elif "$group" in stage:
                key = stage["$group"]["_id"]
                if isinstance(key, str) and key.startswith("$"):
                    key = key[1:]
                buckets: dict[Any, int] = {}
                for d in docs:
                    bucket_key = d.get(key)
                    buckets[bucket_key] = buckets.get(bucket_key, 0) + 1
                docs = [{"_id": k, "n": v} for k, v in buckets.items()]
        return _FakeCursor(docs)

    # --- writes ----------------------------------------------------------
    async def insert_one(self, doc: dict[str, Any]) -> object:
        _id = doc.get("_id")
        self.docs[_id] = dict(doc)
        return SimpleNamespace(inserted_id=_id)

    async def insert_many(
        self,
        docs: list[dict[str, Any]],
        ordered: bool = False,
    ) -> object:
        ids = []
        for d in docs:
            _id = d.get("_id", len(self.docs))
            self.docs[_id] = dict(d)
            ids.append(_id)
        return SimpleNamespace(inserted_ids=ids)

    async def delete_one(self, filt: dict[str, Any]) -> object:
        _id = filt.get("_id")
        if _id in self.docs:
            del self.docs[_id]
            return SimpleNamespace(deleted_count=1)
        return SimpleNamespace(deleted_count=0)

    async def update_one(
        self,
        filt: dict[str, Any],
        update: dict[str, Any],
        upsert: bool = False,
    ) -> object:
        _id = filt.get("_id")
        existing = self.docs.get(_id)
        if existing is None and not upsert:
            return SimpleNamespace(modified_count=0, upserted_id=None)
        new_doc: dict[str, Any] = existing or {"_id": _id}
        new_doc.update(update.get("$set", {}))
        if existing is None:
            new_doc.update(update.get("$setOnInsert", {}))
        self.docs[_id] = new_doc
        return SimpleNamespace(
            modified_count=0 if existing is None else 1,
            upserted_id=None if existing else _id,
        )

    # --- filter matcher --------------------------------------------------
    @classmethod
    def _match(cls, doc: dict[str, Any], filt: dict[str, Any]) -> bool:
        for field, expected in filt.items():
            value = cls._get(doc, field)
            if isinstance(expected, dict):
                for op, arg in expected.items():
                    if op == "$gte":
                        if value is None or value < arg:
                            return False
                    elif op == "$gt":
                        if value is None or value <= arg:
                            return False
                    elif op == "$lt":
                        if value is None or value >= arg:
                            return False
                    elif op == "$in":
                        if value not in arg:
                            return False
                    elif op == "$exists":
                        present = value is not None
                        if bool(arg) != present:
                            return False
                    elif op == "$geoWithin":
                        if not cls._match_geo_within(doc, field, arg):
                            return False
                    else:
                        return False
            elif value != expected:
                return False
        return True

    @staticmethod
    def _get(doc: dict[str, Any], path: str) -> Any:
        cur: Any = doc
        for part in path.split("."):
            if not isinstance(cur, dict):
                return None
            cur = cur.get(part)
        return cur

    @classmethod
    def _match_geo_within(cls, doc: dict[str, Any], field: str, spec: dict[str, Any]) -> bool:
        geom = cls._get(doc, field)
        if not isinstance(geom, dict) or geom.get("type") != "Point":
            return False
        coords = geom.get("coordinates")
        if not coords or len(coords) < 2:
            return False
        lon, lat = float(coords[0]), float(coords[1])
        if "$centerSphere" in spec:
            center, radius_rad = spec["$centerSphere"]
            center_lat = float(center[1])
            center_lon = float(center[0])
            radius_km = float(radius_rad) * 6371.0088
            return haversine_km(LatLon(lat, lon), LatLon(center_lat, center_lon)) <= radius_km
        if "$box" in spec:
            (min_lon, min_lat), (max_lon, max_lat) = spec["$box"]
            return min_lon <= lon <= max_lon and min_lat <= lat <= max_lat
        return False


class FakeMongoClient:
    def __init__(self) -> None:
        self._collections: dict[str, FakeCollection] = {}

    def collection(self, name: str) -> FakeCollection:
        if name not in self._collections:
            self._collections[name] = FakeCollection()
        return self._collections[name]

    async def ping(self) -> bool:
        return True

    async def close(self) -> None:
        pass


# ============================================================================
# arq fake
# ============================================================================


class FakeArq:
    """Records enqueued jobs in-memory."""

    def __init__(self) -> None:
        self.jobs: list[dict[str, Any]] = []
        self._counter = 0

    async def enqueue_job(self, name: str, **kwargs: Any) -> SimpleNamespace:
        self._counter += 1
        job_id = f"job-{self._counter}"
        self.jobs.append({"job_id": job_id, "name": name, "kwargs": kwargs})
        return SimpleNamespace(job_id=job_id)

    async def close(self) -> None:
        pass


# ============================================================================
# Geocoder fake
# ============================================================================


class FakeGeocoder:
    provider_name = "fake"

    def __init__(self, mapping: dict[str, tuple[float, float]] | None = None) -> None:
        self._mapping = mapping or {
            "Tokyo": (35.6762, 139.6503),
            "San Francisco": (37.7749, -122.4194),
        }

    async def forward(self, query: GeocodeQuery) -> GeocodeResult | None:
        coords = self._mapping.get(query.text)
        if coords is None:
            return None
        return GeocodeResult(
            query=query.text,
            name=query.text,
            lat=coords[0],
            lon=coords[1],
            country=None,
            country_code=None,
            provider="fake",
        )

    async def reverse(self, lat: float, lon: float) -> GeocodeResult | None:
        return None

    async def aclose(self) -> None:
        pass


# ============================================================================
# Helpers
# ============================================================================


def make_event(
    fid: str,
    *,
    mag: float,
    lat: float,
    lon: float,
    time_ms: int,
    updated_ms: int | None = None,
    place: str = "Test",
) -> dict[str, Any]:
    """Realistic event doc shaped like what ingestion writes to Mongo."""
    return {
        "_id": fid,
        "properties": {
            "mag": mag,
            "place": place,
            "time": time_ms,
            "updated": updated_ms or time_ms,
            "tsunami": 0,
            "sig": int(mag * 50),
            "type": "earthquake",
        },
        "geometry": {"type": "Point", "coordinates": [lon, lat, 10.0]},
        "_ingested_at": datetime.now(UTC),
        "_last_seen_at": datetime.now(UTC),
        "_schema_version": 1,
    }


_ = operator  # silence "imported but unused" if operator removed later
