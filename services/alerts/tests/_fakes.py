"""Fakes for alerts-svc tests. Subset of motor + arq behaviours we need."""

from __future__ import annotations

from datetime import UTC, datetime
from types import SimpleNamespace
from typing import Any

from kanshacare_shared.geo import LatLon, haversine_km
from pymongo.errors import DuplicateKeyError


class _Cursor:
    def __init__(self, docs: list[dict[str, Any]]) -> None:
        self._docs = list(docs)
        self._sort_field: str | None = None
        self._sort_dir: int = 1
        self._limit: int | None = None

    def sort(self, field: str, direction: int = 1) -> _Cursor:
        self._sort_field = field
        self._sort_dir = direction
        return self

    def limit(self, n: int) -> _Cursor:
        self._limit = n
        return self

    def _materialise(self) -> list[dict[str, Any]]:
        out = list(self._docs)
        if self._sort_field:
            field = self._sort_field

            def keyfn(d: dict[str, Any]) -> Any:
                cur: Any = d
                for part in field.split("."):
                    cur = (cur or {}).get(part) if isinstance(cur, dict) else None
                return cur if cur is not None else 0

            out.sort(key=keyfn, reverse=self._sort_dir < 0)
        if self._limit is not None:
            out = out[: self._limit]
        return out

    def __aiter__(self) -> _Cursor:
        self._iter = iter(self._materialise())
        return self

    async def __anext__(self) -> dict[str, Any]:
        try:
            return next(self._iter)
        except StopIteration as exc:
            raise StopAsyncIteration from exc


class FakeCollection:
    def __init__(self) -> None:
        self.docs: dict[Any, dict[str, Any]] = {}
        # For uniqueness simulation
        self.unique_field: str | None = None

    def find(
        self,
        filt: dict[str, Any] | None = None,
        projection: dict[str, Any] | None = None,
    ) -> _Cursor:
        filt = filt or {}
        matched = [d for d in self.docs.values() if _match(d, filt)]
        return _Cursor(matched)

    async def find_one(
        self,
        filt: dict[str, Any] | None = None,
        sort: list[tuple[str, int]] | None = None,
    ) -> dict[str, Any] | None:
        filt = filt or {}
        candidates = [d for d in self.docs.values() if _match(d, filt)]
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
        return sum(1 for d in self.docs.values() if _match(d, filt))

    async def insert_one(self, doc: dict[str, Any]) -> object:
        # Enforce dedup_key uniqueness if requested.
        if self.unique_field is not None:
            key = doc.get(self.unique_field)
            if any(d.get(self.unique_field) == key for d in self.docs.values()):
                raise DuplicateKeyError(f"duplicate {self.unique_field}={key}")
        _id = doc.get("_id") or len(self.docs)
        doc = {**doc, "_id": _id}
        self.docs[_id] = doc
        return SimpleNamespace(inserted_id=_id)

    async def update_one(
        self,
        filt: dict[str, Any],
        update: dict[str, Any],
        upsert: bool = False,
    ) -> object:
        for _k, v in self.docs.items():
            if _match(v, filt):
                v.update(update.get("$set", {}))
                return SimpleNamespace(modified_count=1, upserted_id=None)
        if upsert:
            new: dict[str, Any] = {}
            new.update(filt)
            new.update(update.get("$set", {}))
            new.update(update.get("$setOnInsert", {}))
            _id = new.get("_id") or len(self.docs)
            new["_id"] = _id
            self.docs[_id] = new
            return SimpleNamespace(modified_count=0, upserted_id=_id)
        return SimpleNamespace(modified_count=0, upserted_id=None)


def _match(doc: dict[str, Any], filt: dict[str, Any]) -> bool:
    for field, expected in filt.items():
        value = _get(doc, field)
        if isinstance(expected, dict):
            for op, arg in expected.items():
                if op == "$gte":
                    if value is None or value < arg:
                        return False
                elif op == "$lte":
                    if value is None or value > arg:
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
                elif op == "$geoWithin":
                    if not _match_geo(doc, field, arg):
                        return False
                else:
                    return False
        elif expected is None:
            if value is not None:
                return False
        elif value != expected:
            return False
    return True


def _get(doc: dict[str, Any], path: str) -> Any:
    cur: Any = doc
    for part in path.split("."):
        if not isinstance(cur, dict):
            return None
        cur = cur.get(part)
    return cur


def _match_geo(doc: dict[str, Any], field: str, spec: dict[str, Any]) -> bool:
    geom = _get(doc, field)
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
    return False


class FakeMongoClient:
    def __init__(self) -> None:
        self._collections: dict[str, FakeCollection] = {}

    def collection(self, name: str) -> FakeCollection:
        if name not in self._collections:
            self._collections[name] = FakeCollection()
            # Mirror the unique index in production.
            if name == "alerts_log":
                self._collections[name].unique_field = "dedup_key"
        return self._collections[name]

    async def ping(self) -> bool:
        return True

    async def close(self) -> None:
        pass


class FakeArq:
    def __init__(self) -> None:
        self.jobs: list[dict[str, Any]] = []
        self._counter = 0

    async def enqueue_job(self, name: str, **kwargs: Any) -> SimpleNamespace:
        self._counter += 1
        self.jobs.append({"job_id": f"job-{self._counter}", "name": name, "kwargs": kwargs})
        return SimpleNamespace(job_id=f"job-{self._counter}")


def make_event(
    fid: str,
    *,
    mag: float,
    lat: float,
    lon: float,
    time_ms: int | None = None,
    place: str = "Test",
    tsunami: int = 0,
    alert: str | None = None,
) -> dict[str, Any]:
    return {
        "_id": fid,
        "properties": {
            "mag": mag,
            "place": place,
            "time": time_ms if time_ms is not None else int(datetime.now(UTC).timestamp() * 1000),
            "tsunami": tsunami,
            "alert": alert,
            "url": f"https://earthquake.usgs.gov/{fid}",
        },
        "geometry": {"type": "Point", "coordinates": [lon, lat, 10.0]},
    }
