"""Telegram message formatter — pure functions, easy to test."""

from __future__ import annotations

from worker_app.messages import alert_message, daily_summary, mag_band_for


def test_global_alert_message_contains_key_facts() -> None:
    msg = alert_message(
        rule="high_severity_global",
        severity="critical",
        payload={
            "mag": 6.4,
            "place": "Off the coast of X",
            "time": 1700000000000,
            "alert": "orange",
            "tsunami": 0,
        },
        dashboard_base_url="https://dash.example.com",
    )
    assert "M6.4" in msg
    assert "Off the coast" in msg
    assert "PAGER orange" in msg
    assert "Open dashboard" in msg


def test_near_alert_includes_distance() -> None:
    msg = alert_message(
        rule="high_severity_near",
        severity="warning",
        payload={
            "mag": 4.7,
            "place": "Near here",
            "time": 1700000000000,
            "location_name": "Home",
            "distance_km": 142.0,
            "tsunami": 0,
        },
        dashboard_base_url="https://x",
    )
    assert "M4.7" in msg
    assert "142" in msg
    assert "Home" in msg


def test_swarm_alert_includes_counts() -> None:
    msg = alert_message(
        rule="swarm",
        severity="warning",
        payload={
            "count": 8,
            "window_minutes": 30,
            "radius_km": 200,
            "largest_mag": 4.2,
            "centre": [-118.0, 34.0],
        },
        dashboard_base_url="https://x",
    )
    assert "8" in msg
    assert "30 min" in msg
    assert "200 km" in msg


def test_silence_alert_phrases_minutes_clearly() -> None:
    msg = alert_message(
        rule="source_silence",
        severity="critical",
        payload={"minutes_since_last_poll": 17.4},
        dashboard_base_url="https://x",
    )
    assert "17 minutes" in msg
    assert "USGS" in msg


def test_daily_summary_renders_all_sections() -> None:
    msg = daily_summary(
        window_label="last 24 hours",
        totals={"total": 142},
        mag_bands={"M5–5.9": 3, "M4–4.9": 12, "M3–3.9": 30, "M2–2.9": 70, "<M2": 27},
        top_regions=[("Anchorage", 18), ("Tokyo", 12), ("Athens", 9)],
        fired_alerts={"high_severity_global": 1, "swarm": 2},
        locations=[{"name": "Home", "risk_score": 88.2, "risk_tier": "moderate"}],
        health={
            "success_rate_1h": 0.95,
            "consecutive_failures": 0,
            "backfill": {"status": "complete"},
        },
        dashboard_base_url="https://dash.example.com",
    )
    assert "142" in msg
    assert "M5–5.9" in msg
    assert "Anchorage" in msg
    assert "Home" in msg
    assert "Open dashboard" in msg


def test_mag_band_buckets() -> None:
    assert mag_band_for(6.1) == "M6+"
    assert mag_band_for(5.0) == "M5–5.9"
    assert mag_band_for(4.99) == "M4–4.9"
    assert mag_band_for(2.5) == "M2–2.9"
    assert mag_band_for(1.0) == "<M2"
    assert mag_band_for(None) == "?"
