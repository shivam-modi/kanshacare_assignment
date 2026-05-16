from __future__ import annotations

from functools import lru_cache

from kanshacare_shared.config import BaseAppSettings


class ApiSettings(BaseAppSettings):
    service_name: str = "api-svc"
    api_port: int = 8001
    max_locations_per_user: int = 3


@lru_cache(maxsize=1)
def get_settings() -> ApiSettings:
    return ApiSettings()
