from __future__ import annotations

import math

import pytest

from kanshacare_shared.geo import (
    LatLon,
    geojson_point,
    haversine_km,
    km_to_radians,
    lat_lon_from_geojson,
)


def test_haversine_zero_distance() -> None:
    p = LatLon(35.6762, 139.6503)  # Tokyo
    assert haversine_km(p, p) == pytest.approx(0.0, abs=1e-9)


def test_haversine_known_distance_tokyo_osaka() -> None:
    tokyo = LatLon(35.6762, 139.6503)
    osaka = LatLon(34.6937, 135.5023)
    # ~392 km great-circle (cross-checked against geopy.distance.great_circle)
    assert haversine_km(tokyo, osaka) == pytest.approx(392, abs=2)


def test_haversine_antipodal() -> None:
    north = LatLon(0.0, 0.0)
    south = LatLon(0.0, 180.0)
    assert haversine_km(north, south) == pytest.approx(math.pi * 6371.0088, rel=1e-3)


def test_lat_out_of_range() -> None:
    with pytest.raises(ValueError, match="lat"):
        LatLon(91.0, 0.0)


def test_lon_out_of_range() -> None:
    with pytest.raises(ValueError, match="lon"):
        LatLon(0.0, 181.0)


def test_geojson_point_order() -> None:
    point = geojson_point(lat=35.0, lon=139.0)
    assert point == {"type": "Point", "coordinates": [139.0, 35.0]}


def test_lat_lon_from_geojson_roundtrip() -> None:
    point = geojson_point(lat=10.0, lon=20.0)
    back = lat_lon_from_geojson(point)
    assert back == LatLon(10.0, 20.0)


def test_km_to_radians() -> None:
    assert km_to_radians(6371.0088) == pytest.approx(1.0)
