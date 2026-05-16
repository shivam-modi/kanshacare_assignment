from __future__ import annotations

from datetime import UTC, datetime, timedelta

from kanshacare_shared.geo import LatLon
from kanshacare_shared.risk import EventForRisk, compute_risk


def _make_event(mag: float, lat: float, lon: float, age_days: float, now: datetime) -> EventForRisk:
    return EventForRisk(
        mag=mag,
        lat=lat,
        lon=lon,
        time_utc=now - timedelta(days=age_days),
    )


def test_no_events_is_low_risk() -> None:
    now = datetime.now(UTC)
    breakdown = compute_risk([], location=LatLon(0, 0), radius_km=500, now=now)
    assert breakdown.score == 0.0
    assert breakdown.tier == "low"
    assert breakdown.event_count == 0
    assert breakdown.largest_mag is None


def test_recent_strong_event_scores_higher_than_old_one() -> None:
    now = datetime.now(UTC)
    loc = LatLon(0, 0)
    recent = compute_risk(
        [_make_event(mag=6.0, lat=0.0, lon=0.5, age_days=0.1, now=now)],
        location=loc,
        radius_km=500,
        now=now,
    )
    old = compute_risk(
        [_make_event(mag=6.0, lat=0.0, lon=0.5, age_days=21, now=now)],
        location=loc,
        radius_km=500,
        now=now,
    )
    assert recent.score > old.score


def test_close_event_scores_higher_than_far_one() -> None:
    now = datetime.now(UTC)
    loc = LatLon(0, 0)
    close_event = compute_risk(
        [_make_event(mag=5.0, lat=0.0, lon=0.05, age_days=1, now=now)],
        location=loc,
        radius_km=500,
        now=now,
    )
    far_event = compute_risk(
        [_make_event(mag=5.0, lat=0.0, lon=4.4, age_days=1, now=now)],  # ~490 km away
        location=loc,
        radius_km=500,
        now=now,
    )
    assert close_event.score > far_event.score


def test_events_outside_radius_excluded() -> None:
    now = datetime.now(UTC)
    loc = LatLon(0, 0)
    breakdown = compute_risk(
        [_make_event(mag=8.0, lat=0.0, lon=20.0, age_days=0.1, now=now)],  # ~2200 km away
        location=loc,
        radius_km=500,
        now=now,
    )
    assert breakdown.score == 0.0
    assert breakdown.event_count == 0


def test_largest_mag_and_closest_km_tracked() -> None:
    now = datetime.now(UTC)
    events = [
        _make_event(mag=3.5, lat=0.0, lon=0.5, age_days=2, now=now),
        _make_event(mag=5.2, lat=0.0, lon=1.0, age_days=4, now=now),
        _make_event(mag=4.1, lat=0.0, lon=0.1, age_days=1, now=now),
    ]
    breakdown = compute_risk(events, location=LatLon(0, 0), radius_km=500, now=now)
    assert breakdown.event_count == 3
    assert breakdown.largest_mag == 5.2
    assert breakdown.closest_km is not None and breakdown.closest_km < 20
