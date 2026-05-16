"""Geo math primitives. Pure functions, no I/O."""

from __future__ import annotations

import math
from dataclasses import dataclass

EARTH_RADIUS_KM = 6371.0088


@dataclass(frozen=True, slots=True)
class LatLon:
    lat: float
    lon: float

    def __post_init__(self) -> None:
        if not -90 <= self.lat <= 90:
            raise ValueError(f"lat out of range: {self.lat}")
        if not -180 <= self.lon <= 180:
            raise ValueError(f"lon out of range: {self.lon}")


def haversine_km(a: LatLon, b: LatLon) -> float:
    """Great-circle distance between two lat/lon points, in km."""
    lat1, lon1, lat2, lon2 = map(math.radians, (a.lat, a.lon, b.lat, b.lon))
    dlat = lat2 - lat1
    dlon = lon2 - lon1
    h = math.sin(dlat / 2) ** 2 + math.cos(lat1) * math.cos(lat2) * math.sin(dlon / 2) ** 2
    return 2 * EARTH_RADIUS_KM * math.asin(math.sqrt(h))


def km_to_radians(km: float) -> float:
    """Convert distance in km to radians on a unit sphere — for Mongo $centerSphere."""
    return km / EARTH_RADIUS_KM


def geojson_point(lat: float, lon: float) -> dict[str, object]:
    """GeoJSON Point. Mongo 2dsphere expects [lon, lat] order — easy to get wrong."""
    return {"type": "Point", "coordinates": [lon, lat]}


def lat_lon_from_geojson(geom: dict[str, object]) -> LatLon:
    coords = geom["coordinates"]
    if not isinstance(coords, list) or len(coords) < 2:
        raise ValueError("invalid GeoJSON Point coordinates")
    return LatLon(lat=float(coords[1]), lon=float(coords[0]))
