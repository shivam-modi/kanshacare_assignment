"""Tiny in-memory fakes for Motor / MongoClient — enough to exercise the
ingestion code paths without a running Mongo. We're testing our own logic,
not the driver.
"""

from __future__ import annotations

from typing import Any

from pymongo import UpdateOne


class _FakeCursor:
    def __init__(self, docs: list[dict[str, Any]]) -> None:
        self._iter = iter(docs)

    def __aiter__(self) -> _FakeCursor:
        return self

    async def __anext__(self) -> dict[str, Any]:
        try:
            return next(self._iter)
        except StopIteration as exc:
            raise StopAsyncIteration from exc


class FakeCollection:
    """Records writes, serves reads from a per-test dict."""

    def __init__(self) -> None:
        self.docs: dict[Any, dict[str, Any]] = {}
        self.inserts: list[list[dict[str, Any]]] = []
        self.bulk_ops: list[list[UpdateOne]] = []

    # --- read API used by upsert_features ----------------------------------
    def find(
        self,
        filt: dict[str, Any],
        projection: dict[str, Any] | None = None,
    ) -> _FakeCursor:
        ids = filt.get("_id", {}).get("$in", [])
        docs = [self.docs[i] for i in ids if i in self.docs]
        # Apply minimal projection: include _id + nested properties.updated when asked.
        if projection:
            projected = []
            for d in docs:
                p: dict[str, Any] = {"_id": d["_id"]}
                if "properties.updated" in projection or projection.get("properties.updated"):
                    p["properties"] = {"updated": d.get("properties", {}).get("updated")}
                projected.append(p)
            return _FakeCursor(projected)
        return _FakeCursor(docs)

    async def find_one(
        self,
        filt: dict[str, Any],
        projection: dict[str, Any] | None = None,
    ) -> dict[str, Any] | None:
        _id = filt.get("_id")
        return self.docs.get(_id)

    # --- write API ---------------------------------------------------------
    async def bulk_write(self, ops: list[UpdateOne], ordered: bool = False) -> object:
        self.bulk_ops.append(ops)
        for op in ops:
            filt = op._filter  # type: ignore[attr-defined]
            update = op._doc  # type: ignore[attr-defined]
            _id = filt["_id"]
            existing = self.docs.get(_id, {})
            new_doc: dict[str, Any] = {**existing, "_id": _id}
            new_doc.update(update.get("$set", {}))
            if _id not in self.docs:
                new_doc.update(update.get("$setOnInsert", {}))
            self.docs[_id] = new_doc
        return object()

    async def insert_many(
        self,
        docs: list[dict[str, Any]],
        ordered: bool = False,
    ) -> object:
        self.inserts.append(docs)
        from types import SimpleNamespace

        return SimpleNamespace(inserted_ids=list(range(len(docs))))

    async def insert_one(self, doc: dict[str, Any]) -> object:
        self.inserts.append([doc])

        class Result:
            inserted_id = 0

        return Result()

    async def update_one(
        self,
        filt: dict[str, Any],
        update: dict[str, Any],
        upsert: bool = False,
    ) -> object:
        _id = filt["_id"]
        existing = self.docs.get(_id)
        if existing is None and not upsert:
            return object()
        new_doc: dict[str, Any] = existing or {"_id": _id}
        new_doc.update(update.get("$set", {}))
        if existing is None:
            new_doc.update(update.get("$setOnInsert", {}))
        self.docs[_id] = new_doc
        return object()


class FakeMongoClient:
    """Stand-in for kanshacare_shared.db.MongoClient. Provides `collection(name)`."""

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
