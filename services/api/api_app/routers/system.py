"""System health endpoint — powers the always-visible dashboard card."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter

from ..deps import MongoDep
from ..queries import get_system_health

router = APIRouter(prefix="/system", tags=["system"])


@router.get("/health")
async def system_health(mongo: MongoDep) -> dict[str, Any]:
    return await get_system_health(mongo)
