from __future__ import annotations

from functools import lru_cache

from kanshacare_shared.config import BaseAppSettings


class WorkerSettings(BaseAppSettings):
    service_name: str = "worker-svc"
    worker_health_port: int = 8003


@lru_cache(maxsize=1)
def get_settings() -> WorkerSettings:
    return WorkerSettings()
