"""Geocoding subsystem — provider-agnostic interface + caching wrapper.

Usage:

    from kanshacare_shared.geocoding import get_geocoder
    geocoder = get_geocoder(settings, mongo)
    result = await geocoder.forward("Tokyo")
"""

from .base import GeocodeQuery, Geocoder
from .factory import get_geocoder

__all__ = ["GeocodeQuery", "Geocoder", "get_geocoder"]
