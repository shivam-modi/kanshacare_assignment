"""Base settings used by every service. Service-specific settings extend BaseAppSettings."""

from __future__ import annotations

from functools import lru_cache
from typing import Literal

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class BaseAppSettings(BaseSettings):
    """Settings every Kansha Care service needs.

    Service-specific subclasses add their own fields. All settings are env-driven
    so the same image runs locally, in CI, and in production with no code change.
    """

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
        case_sensitive=False,
    )

    # ----- runtime ----------------------------------------------------------
    env: Literal["local", "ci", "staging", "production"] = "local"
    service_name: str = "kanshacare"
    log_level: Literal["DEBUG", "INFO", "WARNING", "ERROR"] = "INFO"
    log_format: Literal["json", "console"] = "json"

    # ----- mongo ------------------------------------------------------------
    mongo_uri: str = "mongodb://localhost:27017"
    mongo_db: str = "kanshacare"
    mongo_max_pool_size: int = 50
    mongo_server_selection_timeout_ms: int = 5_000

    # ----- redis ------------------------------------------------------------
    redis_url: str = "redis://localhost:6379"

    # ----- USGS -------------------------------------------------------------
    usgs_hour_url: str = (
        "https://earthquake.usgs.gov/earthquakes/feed/v1.0/summary/all_hour.geojson"
    )
    usgs_month_url: str = (
        "https://earthquake.usgs.gov/earthquakes/feed/v1.0/summary/all_month.geojson"
    )
    usgs_request_timeout_seconds: float = 10.0

    # ----- alert rules (read by alerts-svc; here for shared constants) -----
    alert_global_mag_threshold: float = 5.0
    alert_near_mag_threshold: float = 4.0
    alert_near_radius_km: float = 500.0
    swarm_window_minutes: int = 30
    swarm_radius_km: float = 200.0
    swarm_min_events: int = 5
    silence_threshold_minutes: int = 10
    silence_check_interval_seconds: int = 120
    silence_realert_suppression_minutes: int = 30

    # ----- daily summary ----------------------------------------------------
    daily_summary_hour_utc: int = Field(default=9, ge=0, le=23)
    daily_summary_minute: int = Field(default=0, ge=0, le=59)

    # ----- geocoder ---------------------------------------------------------
    geocoder_provider: Literal["nominatim", "locationiq", "mapbox"] = "nominatim"
    geocoder_user_agent: str = "kanshacare-dev (contact@example.com)"
    geocoder_rate_limit_per_sec: float = 1.0
    locationiq_api_key: str = ""
    mapbox_api_key: str = ""

    # ----- telegram (read by alerts-svc + worker-svc) ----------------------
    telegram_bot_token: str = ""
    telegram_webhook_secret: str = ""
    telegram_webhook_base_url: str = ""

    # ----- dashboard / API --------------------------------------------------
    api_cors_origins: str = "http://localhost:3000"
    api_rate_limit_summary_per_minute: int = 1
    dashboard_base_url: str = "http://localhost:3000"

    @property
    def cors_origins_list(self) -> list[str]:
        return [o.strip() for o in self.api_cors_origins.split(",") if o.strip()]


@lru_cache(maxsize=1)
def get_settings() -> BaseAppSettings:
    """Cached singleton accessor. Services typically subclass and define their own."""
    return BaseAppSettings()
