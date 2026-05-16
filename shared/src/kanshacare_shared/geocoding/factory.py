"""Env-driven geocoder construction. The only place that knows about providers."""

from __future__ import annotations

from ..config import BaseAppSettings
from ..db import MongoClient
from ..errors import ValidationError
from .base import Geocoder
from .cached import CachedGeocoder
from .nominatim import NominatimGeocoder


def get_geocoder(settings: BaseAppSettings, mongo: MongoClient | None = None) -> Geocoder:
    """Construct the configured geocoder, wrapped in the Mongo cache if available.

    Adding a new provider is a 3-line change here plus one new module — the
    Geocoder interface is the contract that keeps callers untouched.
    """
    provider = settings.geocoder_provider

    inner: Geocoder
    if provider == "nominatim":
        inner = NominatimGeocoder(
            user_agent=settings.geocoder_user_agent,
            rate_limit_per_sec=settings.geocoder_rate_limit_per_sec,
        )
    elif provider == "locationiq":
        raise ValidationError("locationiq geocoder not yet implemented")
    elif provider == "mapbox":
        raise ValidationError("mapbox geocoder not yet implemented")
    else:
        raise ValidationError(f"unknown geocoder provider: {provider}")

    if mongo is not None:
        return CachedGeocoder(inner, mongo)
    return inner
