from __future__ import annotations

from functools import lru_cache

from kanshacare_shared.config import BaseAppSettings


class IngestionSettings(BaseAppSettings):
    """ingestion-svc-specific knobs. Inherits everything from BaseAppSettings."""

    service_name: str = "ingestion-svc"
    usgs_poll_interval_seconds: int = 60
    usgs_backfill_on_boot: bool = True
    ingestion_port: int = 8000


@lru_cache(maxsize=1)
def get_settings() -> IngestionSettings:
    return IngestionSettings()
