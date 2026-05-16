"""Mongo change-stream listener — the production path for real-time alert detection.

Falls back to a polling loop if change streams aren't supported (single-node
Mongo in local dev). Either way, every event that lands gets evaluated by the
rule engine.
"""

from __future__ import annotations

import asyncio
import contextlib
from datetime import datetime
from typing import Any

from arq.connections import ArqRedis

from kanshacare_shared.config import BaseAppSettings
from kanshacare_shared.db import COLL_EVENTS, MongoClient
from kanshacare_shared.logging import get_logger

from .dispatcher import dispatch
from .rules import evaluate_event

log = get_logger(__name__)


class EventConsumer:
    """Runs in the background of alerts-svc; never raises out."""

    def __init__(self, *, mongo: MongoClient, arq: ArqRedis, settings: BaseAppSettings) -> None:
        self._mongo = mongo
        self._arq = arq
        self._settings = settings
        self._task: asyncio.Task[None] | None = None
        self._stop = asyncio.Event()

    def start(self) -> None:
        if self._task and not self._task.done():
            return
        self._task = asyncio.create_task(self._run(), name="alerts-event-consumer")

    async def stop(self) -> None:
        self._stop.set()
        if self._task:
            self._task.cancel()
            with contextlib.suppress(asyncio.CancelledError, Exception):
                await self._task

    async def _run(self) -> None:
        while not self._stop.is_set():
            try:
                await self._consume_change_stream()
            except Exception as exc:
                log.warning("alerts.changestream.failed_falling_back", error=str(exc))
                try:
                    await self._consume_poll_fallback()
                except Exception:
                    log.exception("alerts.poll_fallback.crashed")
                    await asyncio.sleep(30)

    async def _consume_change_stream(self) -> None:
        coll = self._mongo.collection(COLL_EVENTS)
        async with coll.watch(
            [{"$match": {"operationType": {"$in": ["insert", "update", "replace"]}}}],
            full_document="updateLookup",
        ) as stream:
            log.info("alerts.changestream.opened")
            async for change in stream:
                if self._stop.is_set():
                    break
                doc = change.get("fullDocument")
                if doc:
                    await self._evaluate(doc)

    async def _consume_poll_fallback(self) -> None:
        coll = self._mongo.collection(COLL_EVENTS)
        last_seen: datetime | None = None
        while not self._stop.is_set():
            filt: dict[str, Any] = {}
            if last_seen is not None:
                filt["_last_seen_at"] = {"$gt": last_seen}
            cursor = coll.find(filt).sort("_last_seen_at", 1).limit(200)
            async for doc in cursor:
                await self._evaluate(doc)
                last_seen = doc.get("_last_seen_at") or last_seen
            await asyncio.sleep(15)

    async def _evaluate(self, doc: dict[str, Any]) -> None:
        try:
            candidates = await evaluate_event(doc, settings=self._settings, mongo=self._mongo)
        except Exception:
            log.exception("alerts.rule_eval.crashed", event_id=doc.get("_id"))
            return
        for cand in candidates:
            try:
                await dispatch(cand, mongo=self._mongo, arq=self._arq)
            except Exception:
                log.exception("alerts.dispatch.crashed", rule=cand.rule)
