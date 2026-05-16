"""MongoDB client management + collection accessors + index bootstrap."""

from __future__ import annotations

from typing import TYPE_CHECKING

from motor.motor_asyncio import AsyncIOMotorClient, AsyncIOMotorCollection, AsyncIOMotorDatabase
from pymongo import ASCENDING, DESCENDING, GEOSPHERE, IndexModel

from .logging import get_logger

if TYPE_CHECKING:
    from .config import BaseAppSettings

log = get_logger(__name__)

# ----- collection names (single source of truth) -------------------------
COLL_EVENTS = "events"
COLL_EVENTS_QUARANTINE = "events_quarantine"
COLL_LOCATIONS = "locations"
COLL_SYSTEM_HEALTH = "system_health"
COLL_ALERTS_LOG = "alerts_log"
COLL_SUBSCRIBERS = "telegram_subscribers"
COLL_GEOCODE_CACHE = "geocode_cache"
COLL_META = "meta"

_SYSTEM_HEALTH_TTL_DAYS = 7
_GEOCODE_CACHE_TTL_DAYS = 30


class MongoClient:
    """Thin async wrapper. One instance per process; created at startup."""

    def __init__(self, settings: BaseAppSettings) -> None:
        self._client: AsyncIOMotorClient = AsyncIOMotorClient(
            settings.mongo_uri,
            maxPoolSize=settings.mongo_max_pool_size,
            serverSelectionTimeoutMS=settings.mongo_server_selection_timeout_ms,
            tz_aware=True,
        )
        self._db: AsyncIOMotorDatabase = self._client[settings.mongo_db]

    @property
    def db(self) -> AsyncIOMotorDatabase:
        return self._db

    @property
    def client(self) -> AsyncIOMotorClient:
        return self._client

    def collection(self, name: str) -> AsyncIOMotorCollection:
        return self._db[name]

    async def ping(self) -> bool:
        try:
            await self._client.admin.command("ping")
        except Exception as exc:
            log.warning("mongo.ping.failed", error=str(exc))
            return False
        return True

    async def close(self) -> None:
        self._client.close()


async def ensure_indexes(client: MongoClient) -> None:
    """Idempotent index creation. Run on startup of any service that writes."""

    events_indexes = [
        IndexModel([("geometry", GEOSPHERE)], name="ix_geometry_2dsphere"),
        IndexModel([("properties.time", DESCENDING)], name="ix_props_time_desc"),
        IndexModel([("properties.mag", DESCENDING)], name="ix_props_mag_desc"),
        IndexModel([("properties.sig", DESCENDING)], name="ix_props_sig_desc"),
        IndexModel([("properties.updated", DESCENDING)], name="ix_props_updated_desc"),
        IndexModel([("_ingested_at", DESCENDING)], name="ix_ingested_at"),
    ]
    await client.collection(COLL_EVENTS).create_indexes(events_indexes)

    await client.collection(COLL_LOCATIONS).create_indexes(
        [
            IndexModel([("point", GEOSPHERE)], name="ix_point_2dsphere"),
            IndexModel([("created_at", DESCENDING)], name="ix_created_at"),
        ]
    )

    await client.collection(COLL_SYSTEM_HEALTH).create_indexes(
        [
            IndexModel(
                [("ts", DESCENDING)],
                name="ix_ts_ttl",
                expireAfterSeconds=_SYSTEM_HEALTH_TTL_DAYS * 86400,
            ),
            IndexModel([("status", ASCENDING), ("ts", DESCENDING)], name="ix_status_ts"),
        ]
    )

    await client.collection(COLL_ALERTS_LOG).create_indexes(
        [
            IndexModel([("dedup_key", ASCENDING)], name="ix_dedup_key", unique=True),
            IndexModel([("fired_at", DESCENDING)], name="ix_fired_at"),
            IndexModel([("rule", ASCENDING), ("fired_at", DESCENDING)], name="ix_rule_fired"),
        ]
    )

    await client.collection(COLL_SUBSCRIBERS).create_indexes(
        [IndexModel([("stopped_at", ASCENDING)], name="ix_stopped_at")]
    )

    await client.collection(COLL_GEOCODE_CACHE).create_indexes(
        [
            IndexModel(
                [("cached_at", DESCENDING)],
                name="ix_cached_at_ttl",
                expireAfterSeconds=_GEOCODE_CACHE_TTL_DAYS * 86400,
            ),
            IndexModel(
                [("provider", ASCENDING), ("query", ASCENDING)],
                name="ix_provider_query",
            ),
        ]
    )

    log.info("mongo.indexes.ensured")
