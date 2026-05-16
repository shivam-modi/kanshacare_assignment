"""Telegram subscriber lifecycle. `/start` adds, `/stop` marks stopped, others tick last_seen."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

from kanshacare_shared.db import COLL_SUBSCRIBERS, MongoClient


async def register(
    mongo: MongoClient,
    *,
    chat_id: int,
    username: str | None,
    first_name: str | None,
) -> None:
    now = datetime.now(UTC)
    await mongo.collection(COLL_SUBSCRIBERS).update_one(
        {"_id": chat_id},
        {
            "$set": {
                "username": username,
                "first_name": first_name,
                "last_seen_at": now,
                "stopped_at": None,
                "_schema_version": 1,
            },
            "$setOnInsert": {"started_at": now},
        },
        upsert=True,
    )


async def mark_stopped(mongo: MongoClient, *, chat_id: int) -> None:
    await mongo.collection(COLL_SUBSCRIBERS).update_one(
        {"_id": chat_id},
        {"$set": {"stopped_at": datetime.now(UTC)}},
    )


async def touch(mongo: MongoClient, *, chat_id: int) -> None:
    await mongo.collection(COLL_SUBSCRIBERS).update_one(
        {"_id": chat_id},
        {"$set": {"last_seen_at": datetime.now(UTC)}},
    )


async def list_active(mongo: MongoClient) -> list[dict[str, Any]]:
    cursor = mongo.collection(COLL_SUBSCRIBERS).find({"stopped_at": None})
    return [doc async for doc in cursor]
