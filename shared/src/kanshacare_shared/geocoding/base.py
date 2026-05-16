"""Geocoder interface. Implementations are interchangeable per env config."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol, runtime_checkable

from ..models import GeocodeResult


@dataclass(frozen=True, slots=True)
class GeocodeQuery:
    """What we send to a provider. Centralised so all impls share the same input."""

    text: str
    limit: int = 1
    country_codes: tuple[str, ...] | None = None  # ISO 3166-1 alpha-2 hints


@runtime_checkable
class Geocoder(Protocol):
    """Provider-neutral async geocoder.

    All implementations MUST:
    * Return `None` on no-result rather than raising
    * Translate transient upstream failures to `UpstreamError`
    * Self-rate-limit if the provider requires it (e.g. Nominatim's 1 req/sec)
    """

    provider_name: str

    async def forward(self, query: GeocodeQuery) -> GeocodeResult | None: ...

    async def reverse(self, lat: float, lon: float) -> GeocodeResult | None: ...

    async def aclose(self) -> None: ...
