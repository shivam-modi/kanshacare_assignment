"""Pydantic v2 domain models. Storage representation + API DTOs."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Annotated, Any, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator

SCHEMA_VERSION = 1


# ============================================================================
# USGS feature parsing
# ============================================================================


class USGSGeometry(BaseModel):
    """USGS feed gives `coordinates: [lon, lat, depth_km]` for earthquakes."""

    type: Literal["Point"] = "Point"
    coordinates: list[float]

    @field_validator("coordinates")
    @classmethod
    def _check_coords(cls, v: list[float]) -> list[float]:
        if len(v) < 2:
            raise ValueError("coordinates must have at least [lon, lat]")
        lon, lat = v[0], v[1]
        if not -180 <= lon <= 180:
            raise ValueError(f"lon out of range: {lon}")
        if not -90 <= lat <= 90:
            raise ValueError(f"lat out of range: {lat}")
        return v

    @property
    def lon(self) -> float:
        return float(self.coordinates[0])

    @property
    def lat(self) -> float:
        return float(self.coordinates[1])

    @property
    def depth_km(self) -> float | None:
        return float(self.coordinates[2]) if len(self.coordinates) > 2 else None


class USGSProperties(BaseModel):
    """A deliberately permissive view of USGS properties.

    We capture the fields we use; unknown fields are kept in `extra` so we never
    lose data if USGS adds something. Many fields are nullable for small quakes.
    """

    model_config = ConfigDict(extra="allow")

    mag: float | None = None
    place: str | None = None
    time: int | None = None  # epoch ms
    updated: int | None = None  # epoch ms
    tz: int | None = None
    url: str | None = None
    detail: str | None = None
    felt: int | None = None
    cdi: float | None = None
    mmi: float | None = None
    alert: Literal["green", "yellow", "orange", "red"] | None = None
    status: Literal["automatic", "reviewed", "deleted"] | None = None
    tsunami: int = 0
    sig: int | None = None
    net: str | None = None
    code: str | None = None
    ids: str | None = None
    sources: str | None = None
    types: str | None = None
    nst: int | None = None
    dmin: float | None = None
    rms: float | None = None
    gap: float | None = None
    magType: str | None = None
    type: str | None = "earthquake"
    title: str | None = None


class USGSFeature(BaseModel):
    """A single GeoJSON Feature from a USGS feed."""

    type: Literal["Feature"] = "Feature"
    id: str
    properties: USGSProperties
    geometry: USGSGeometry


class USGSFeatureCollection(BaseModel):
    """Top-level container returned by the USGS feeds."""

    type: Literal["FeatureCollection"] = "FeatureCollection"
    metadata: dict[str, Any] = Field(default_factory=dict)
    features: list[USGSFeature]


# ============================================================================
# Storage representations
# ============================================================================


class EventDoc(BaseModel):
    """How an earthquake is stored in Mongo. Keyed by USGS id (string)."""

    model_config = ConfigDict(populate_by_name=True)

    id: str = Field(alias="_id")
    properties: USGSProperties
    geometry: USGSGeometry
    ingested_at: datetime = Field(alias="_ingested_at")
    last_seen_at: datetime = Field(alias="_last_seen_at")
    schema_version: int = Field(default=SCHEMA_VERSION, alias="_schema_version")


def event_doc_from_feature(feature: USGSFeature, *, now: datetime | None = None) -> dict[str, Any]:
    """Convert a USGSFeature to the Mongo upsert payload (raw dict, not the Pydantic model).

    The shape is what `update_one(..., {"$set": ..., "$setOnInsert": ...})` consumes.
    """
    now = now or datetime.now(UTC)
    return {
        "_id": feature.id,
        "properties": feature.properties.model_dump(exclude_none=False),
        "geometry": feature.geometry.model_dump(),
        "_last_seen_at": now,
        "_schema_version": SCHEMA_VERSION,
        # _ingested_at is set via $setOnInsert at the call site
    }


# ============================================================================
# Locations
# ============================================================================


class LocationThresholds(BaseModel):
    """Per-location override of the global alert rules. None → use global default."""

    near_mag: float | None = None
    near_radius_km: float | None = None


class LocationCreate(BaseModel):
    name: str = Field(min_length=1, max_length=120)
    query: str | None = None  # original input from user (e.g. "Tokyo")
    lat: float = Field(ge=-90, le=90)
    lon: float = Field(ge=-180, le=180)
    radius_km: float = Field(default=500.0, gt=0, le=20_000)
    thresholds: LocationThresholds = Field(default_factory=LocationThresholds)


class LocationDoc(BaseModel):
    """How a user-selected location is stored."""

    model_config = ConfigDict(populate_by_name=True, arbitrary_types_allowed=True)

    id: Annotated[str, Field(alias="_id")]
    name: str
    query: str | None = None
    point: dict[str, Any]  # GeoJSON Point
    radius_km: float
    thresholds: LocationThresholds
    created_at: datetime
    schema_version: int = Field(default=SCHEMA_VERSION, alias="_schema_version")


# ============================================================================
# Health
# ============================================================================


class HealthRecord(BaseModel):
    """One row per poll attempt — feeds the System Health card."""

    ts: datetime
    feed: Literal["hour", "month"]
    status: Literal["ok", "error", "timeout"]
    latency_ms: int
    events_new: int = 0
    events_updated: int = 0
    events_quarantined: int = 0
    http_status: int | None = None
    error_class: str | None = None
    error_message: str | None = None
    schema_version: int = Field(default=SCHEMA_VERSION, alias="_schema_version")


# ============================================================================
# Alerts
# ============================================================================

AlertRule = Literal[
    "high_severity_global",
    "high_severity_near",
    "swarm",
    "source_silence",
]
AlertSeverity = Literal["info", "warning", "critical"]
DeliveryStatus = Literal["queued", "sent", "failed", "skipped_dedup"]


class AlertRecord(BaseModel):
    """Audit log of every alert decision (fired, skipped, or failed delivery)."""

    rule: AlertRule
    dedup_key: str
    severity: AlertSeverity
    event_id: str | None = None
    location_id: str | None = None
    payload: dict[str, Any]
    delivery_status: DeliveryStatus
    fired_at: datetime
    delivered_at: datetime | None = None
    schema_version: int = Field(default=SCHEMA_VERSION, alias="_schema_version")


# ============================================================================
# Telegram
# ============================================================================


class SubscriberDoc(BaseModel):
    """One telegram chat that has /start-ed the bot."""

    model_config = ConfigDict(populate_by_name=True)

    chat_id: int = Field(alias="_id")
    username: str | None = None
    first_name: str | None = None
    started_at: datetime
    last_seen_at: datetime
    stopped_at: datetime | None = None
    schema_version: int = Field(default=SCHEMA_VERSION, alias="_schema_version")


# ============================================================================
# Geocoding
# ============================================================================


class GeocodeResult(BaseModel):
    """Provider-neutral geocoder output."""

    query: str
    name: str  # human-readable display name
    lat: float = Field(ge=-90, le=90)
    lon: float = Field(ge=-180, le=180)
    country: str | None = None
    country_code: str | None = None
    provider: str
