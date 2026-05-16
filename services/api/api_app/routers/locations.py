"""Locations CRUD + per-location summary endpoints."""

from __future__ import annotations

from typing import Annotated, Any

from fastapi import APIRouter, Body, Path
from pydantic import BaseModel, Field

from kanshacare_shared.errors import ValidationError
from kanshacare_shared.geocoding.base import GeocodeQuery
from kanshacare_shared.models import LocationCreate, LocationThresholds

from ..deps import GeocoderDep, MongoDep, SettingsDep
from ..locations import build_location_summary, create_location, delete_location, list_locations

router = APIRouter(prefix="/locations", tags=["locations"])


class LocationInput(BaseModel):
    """Dashboard input. Either `query` (city name) OR (`lat`, `lon`) is required."""

    name: str = Field(min_length=1, max_length=120)
    query: str | None = None
    lat: float | None = Field(default=None, ge=-90, le=90)
    lon: float | None = Field(default=None, ge=-180, le=180)
    radius_km: float = Field(default=500.0, gt=0, le=20_000)
    thresholds: LocationThresholds = Field(default_factory=LocationThresholds)


@router.get("")
async def get_locations(mongo: MongoDep) -> dict[str, Any]:
    locations = await list_locations(mongo)
    return {"count": len(locations), "locations": locations}


@router.post("", status_code=201)
async def post_location(
    mongo: MongoDep,
    settings: SettingsDep,
    geocoder: GeocoderDep,
    body: Annotated[LocationInput, Body(...)],
) -> dict[str, Any]:
    """Create a location. The query is geocoded if lat/lon weren't provided."""
    if body.lat is not None and body.lon is not None:
        lat, lon = body.lat, body.lon
    elif body.query:
        result = await geocoder.forward(GeocodeQuery(text=body.query))
        if result is None:
            raise ValidationError(f"could not geocode: {body.query!r}")
        lat, lon = result.lat, result.lon
    else:
        raise ValidationError("provide either (lat, lon) or query")

    return await create_location(
        mongo,
        LocationCreate(
            name=body.name,
            query=body.query,
            lat=lat,
            lon=lon,
            radius_km=body.radius_km,
            thresholds=body.thresholds,
        ),
        max_locations=getattr(settings, "max_locations_per_user", 3),
    )


@router.delete("/{location_id}", status_code=204)
async def remove_location(
    mongo: MongoDep,
    location_id: Annotated[str, Path(...)],
) -> None:
    await delete_location(mongo, location_id)


@router.get("/{location_id}/summary")
async def location_summary(
    mongo: MongoDep,
    settings: SettingsDep,
    location_id: Annotated[str, Path(...)],
) -> dict[str, Any]:
    return await build_location_summary(mongo, settings, location_id)
