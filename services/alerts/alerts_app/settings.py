from __future__ import annotations

from functools import lru_cache

from kanshacare_shared.config import BaseAppSettings


class AlertsSettings(BaseAppSettings):
    service_name: str = "alerts-svc"
    alerts_port: int = 8002


@lru_cache(maxsize=1)
def get_settings() -> AlertsSettings:
    return AlertsSettings()
