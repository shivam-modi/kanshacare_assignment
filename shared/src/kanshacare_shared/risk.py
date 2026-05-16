"""Risk scoring for a user-selected location.

Formula
-------
For each event within `radius_km` of the location in the last `lookback_days`:

    contrib = magnitude_weight × recency_decay × proximity_decay

where:

* magnitude_weight = 10 ** (1.5 × max(0, mag - 2))
  Earthquake energy scales as 10^(1.5·M). Subtract 2 so M2 quakes contribute ~1.0
  rather than swamping the score with tiny background events.

* recency_decay = exp(-age_days / RECENCY_HALF_LIFE_DAYS · ln 2)
  Exponential half-life (default 7 days). Events from today count fully; an event
  from 7 days ago counts half; from 14 days ago, a quarter.

* proximity_decay = max(0, 1 - distance_km / radius_km) ** 2
  Quadratic falloff: an event at the centre is full weight, at the radius edge is zero.

Score is summed across events, then mapped to a tier (low / moderate / elevated / high).
Tier thresholds are calibrated to feel intuitive on real USGS data; they are deliberate
and documented (not auto-tuned), because operators need a stable mental model.
"""

from __future__ import annotations

import math
from collections.abc import Iterable
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Literal

from .geo import LatLon, haversine_km

RECENCY_HALF_LIFE_DAYS: float = 7.0
MAG_BASELINE: float = 2.0
LOOKBACK_DAYS: int = 30

RiskTier = Literal["low", "moderate", "elevated", "high"]

# Tier thresholds — calibrated, see module docstring
_TIER_THRESHOLDS: tuple[tuple[float, RiskTier], ...] = (
    (1000.0, "high"),
    (250.0, "elevated"),
    (50.0, "moderate"),
    (0.0, "low"),
)


@dataclass(frozen=True, slots=True)
class EventForRisk:
    """Minimal projection of an event needed for scoring. Keeps this module pure."""

    mag: float
    lat: float
    lon: float
    time_utc: datetime


@dataclass(frozen=True, slots=True)
class RiskBreakdown:
    score: float
    tier: RiskTier
    event_count: int
    largest_mag: float | None
    closest_km: float | None


def _magnitude_weight(mag: float) -> float:
    effective = max(0.0, mag - MAG_BASELINE)
    return float(10 ** (1.5 * effective))


def _recency_decay(age_days: float) -> float:
    if age_days <= 0:
        return 1.0
    return math.exp(-age_days / RECENCY_HALF_LIFE_DAYS * math.log(2))


def _proximity_decay(distance_km: float, radius_km: float) -> float:
    if distance_km >= radius_km:
        return 0.0
    return (1.0 - distance_km / radius_km) ** 2


def _tier_for(score: float) -> RiskTier:
    for threshold, tier in _TIER_THRESHOLDS:
        if score >= threshold:
            return tier
    return "low"


def compute_risk(
    events: Iterable[EventForRisk],
    *,
    location: LatLon,
    radius_km: float,
    now: datetime | None = None,
) -> RiskBreakdown:
    """Compute the risk breakdown for a location given an iterable of nearby events.

    Caller is responsible for filtering events to the radius + lookback window
    (typically via a Mongo `$geoWithin` + time filter), but this function still
    applies proximity_decay so events near the radius edge contribute less.
    """
    now = now or datetime.now(UTC)
    score = 0.0
    count = 0
    largest: float | None = None
    closest: float | None = None

    for ev in events:
        dist = haversine_km(LatLon(ev.lat, ev.lon), location)
        if dist > radius_km:
            continue
        age_days = (now - ev.time_utc).total_seconds() / 86400.0
        score += (
            _magnitude_weight(ev.mag) * _recency_decay(age_days) * _proximity_decay(dist, radius_km)
        )
        count += 1
        if largest is None or ev.mag > largest:
            largest = ev.mag
        if closest is None or dist < closest:
            closest = dist

    return RiskBreakdown(
        score=round(score, 2),
        tier=_tier_for(score),
        event_count=count,
        largest_mag=largest,
        closest_km=round(closest, 2) if closest is not None else None,
    )
