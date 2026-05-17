"""Telegram message formatters. Pure functions — easy to unit test."""

from __future__ import annotations

import html
from datetime import UTC, datetime
from typing import Any

DASHBOARD_LINK_TEMPLATE = "{base}/"


def _esc(value: Any) -> str:
    """HTML-escape a value for safe interpolation into a parse_mode=HTML message.

    Telegram rejects messages where unescaped <, >, & appear in text content.
    USGS place names and user-entered location names can contain any of these,
    so every interpolated string gets run through this.
    """
    return html.escape("" if value is None else str(value), quote=False)


def alert_message(
    *,
    rule: str,
    severity: str,
    payload: dict[str, Any],
    dashboard_base_url: str,
) -> str:
    """Format any alert into a single, scannable Telegram message."""
    sev_emoji = {"critical": "🔴", "warning": "🟠", "info": "🟡"}.get(severity, "🟡")
    header = f"{sev_emoji} <b>{_rule_label(rule)}</b>  ·  <i>{severity}</i>"

    body = ""
    if rule == "high_severity_global":
        body = _global_body(payload)
    elif rule == "high_severity_near":
        body = _near_body(payload)
    elif rule == "swarm":
        body = _swarm_body(payload)
    elif rule == "source_silence":
        body = _silence_body(payload)
    else:
        body = _generic_body(payload)

    link = DASHBOARD_LINK_TEMPLATE.format(base=dashboard_base_url.rstrip("/"))
    footer = (
        f'\n\n<a href="{link}">Open dashboard</a>'
        f"  ·  {datetime.now(UTC).strftime('%Y-%m-%d %H:%M UTC')}"
    )
    return f"{header}\n\n{body}{footer}"


def _rule_label(rule: str) -> str:
    return {
        "high_severity_global": "High-magnitude earthquake",
        "high_severity_near": "Earthquake near you",
        "swarm": "Earthquake swarm",
        "source_silence": "USGS feed silent",
    }.get(rule, rule)


def _global_body(p: dict[str, Any]) -> str:
    mag = p.get("mag")
    place = _esc(p.get("place") or "—")
    ts = _fmt_ms(p.get("time"))
    extras = []
    if p.get("alert"):
        extras.append(f"PAGER {_esc(p['alert'])}")
    if p.get("tsunami"):
        extras.append("Tsunami flag")
    tag_str = (" · " + " · ".join(extras)) if extras else ""
    return f"<b>M{mag:.1f}</b> — {place}\n{ts}{tag_str}"


def _near_body(p: dict[str, Any]) -> str:
    mag = p.get("mag")
    place = _esc(p.get("place") or "—")
    loc = _esc(p.get("location_name") or "your location")
    dist = p.get("distance_km")
    ts = _fmt_ms(p.get("time"))
    return f"<b>M{mag:.1f}</b> — {place}\n{dist:.0f} km from <b>{loc}</b>\n{ts}"


def _swarm_body(p: dict[str, Any]) -> str:
    count = p.get("count")
    window = p.get("window_minutes")
    radius = p.get("radius_km")
    largest = p.get("largest_mag")
    centre = p.get("centre") or [None, None]
    largest_str = f"M{largest:.1f}" if isinstance(largest, (int, float)) else "?"
    return (
        f"<b>{count}</b> quakes in {window} min within {radius:.0f} km\n"
        f"Centre: {centre[1]:.2f}, {centre[0]:.2f} · largest: <b>{largest_str}</b>"
    )


def _silence_body(p: dict[str, Any]) -> str:
    minutes = p.get("minutes_since_last_poll")
    return (
        "The USGS feed has not been successfully polled for "
        f"<b>{minutes:.0f} minutes</b>. The ingestion service may be degraded."
    )


def _generic_body(p: dict[str, Any]) -> str:
    return "\n".join(f"<code>{_esc(k)}</code>: {_esc(v)}" for k, v in p.items())


def _fmt_ms(ms: int | float | None) -> str:
    if ms is None:
        return "(time unknown)"
    return datetime.fromtimestamp(ms / 1000, tz=UTC).strftime("%Y-%m-%d %H:%M UTC")


# ============================================================================
# Daily summary
# ============================================================================


def daily_summary(
    *,
    window_label: str,
    totals: dict[str, int],
    mag_bands: dict[str, int],
    top_regions: list[tuple[str, int]],
    fired_alerts: dict[str, int],
    locations: list[dict[str, Any]],
    health: dict[str, Any],
    dashboard_base_url: str,
) -> str:
    lines = [
        f"📅 <b>Kansha Care — {_esc(window_label)}</b>",
        "",
        f"<b>Total events:</b> {totals.get('total', 0)}",
    ]

    if mag_bands:
        lines.append("\n<b>By magnitude band:</b>")
        for band, n in sorted(mag_bands.items(), reverse=True):
            lines.append(f"  • {_esc(band)}: {n}")

    if top_regions:
        lines.append("\n<b>Top regions:</b>")
        for i, (place, n) in enumerate(top_regions[:3], start=1):
            lines.append(f"  {i}. {_esc(place)} — {n}")

    if fired_alerts:
        lines.append("\n<b>Alerts fired:</b>")
        for rule, n in fired_alerts.items():
            lines.append(f"  • {_esc(_rule_label(rule))}: {n}")
    else:
        lines.append("\nNo alerts fired in this period.")

    if locations:
        lines.append("\n<b>Your locations:</b>")
        for loc in locations:
            score = loc.get("risk_score")
            tier = _esc(loc.get("risk_tier") or "—")
            name = _esc(loc.get("name"))
            lines.append(f"  • {name} — risk {score} ({tier})")

    lines.append("\n<b>System health:</b>")
    sr = health.get("success_rate_1h")
    sr_str = "—" if sr is None else f"{sr * 100:.0f}%"
    lines.append(
        f"  • Poll success (last hour): {sr_str}"
        f" · Failure streak: {health.get('consecutive_failures', 0)}"
    )
    bf = health.get("backfill") or {}
    lines.append(f"  • Backfill: {bf.get('status', '—')}")

    link = DASHBOARD_LINK_TEMPLATE.format(base=dashboard_base_url.rstrip("/"))
    lines.append(f'\n<a href="{link}">Open dashboard</a>')
    return "\n".join(lines)


def mag_band_for(mag: float | None) -> str:
    if mag is None:
        return "?"
    if mag >= 6.0:
        return "M6+"
    if mag >= 5.0:
        return "M5–5.9"
    if mag >= 4.0:
        return "M4–4.9"
    if mag >= 3.0:
        return "M3–3.9"
    if mag >= 2.0:
        return "M2–2.9"
    return "<M2"
