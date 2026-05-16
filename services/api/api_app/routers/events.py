"""Event read endpoints + SSE stream."""

from __future__ import annotations

import asyncio
import json
from typing import Annotated, Any

from fastapi import APIRouter, Query, Request
from sse_starlette.sse import EventSourceResponse

from kanshacare_shared.errors import ValidationError
from kanshacare_shared.logging import get_logger

from ..deps import MongoDep
from ..queries import TimeWindow, list_events, list_events_near, stream_event_changes

router = APIRouter(prefix="/events", tags=["events"])
log = get_logger(__name__)


@router.get("")
async def get_events(
    mongo: MongoDep,
    window: TimeWindow = "24h",
    min_mag: Annotated[float | None, Query(ge=-1, le=11)] = None,
    bbox: Annotated[
        str | None,
        Query(description="min_lon,min_lat,max_lon,max_lat"),
    ] = None,
    limit: Annotated[int, Query(ge=1, le=2000)] = 500,
) -> dict[str, Any]:
    """Global event feed. The dashboard's incident tracker calls this."""
    bbox_tuple: tuple[float, float, float, float] | None = None
    if bbox is not None:
        try:
            parts = [float(x) for x in bbox.split(",")]
            if len(parts) != 4:
                raise ValueError
            bbox_tuple = (parts[0], parts[1], parts[2], parts[3])
        except ValueError:
            raise ValidationError("bbox must be 'min_lon,min_lat,max_lon,max_lat'") from None

    events = await list_events(mongo, window=window, min_mag=min_mag, bbox=bbox_tuple, limit=limit)
    return {"window": window, "count": len(events), "events": events}


@router.get("/near")
async def get_events_near(
    mongo: MongoDep,
    lat: Annotated[float, Query(ge=-90, le=90)],
    lon: Annotated[float, Query(ge=-180, le=180)],
    radius_km: Annotated[float, Query(gt=0, le=20_000)] = 500.0,
    window: TimeWindow = "30d",
    limit: Annotated[int, Query(ge=1, le=2000)] = 500,
) -> dict[str, Any]:
    events = await list_events_near(
        mongo,
        lat=lat,
        lon=lon,
        radius_km=radius_km,
        window=window,
        limit=limit,
    )
    return {
        "window": window,
        "radius_km": radius_km,
        "count": len(events),
        "events": events,
    }


@router.get("/stream")
async def stream(request: Request, mongo: MongoDep) -> EventSourceResponse:
    """Server-Sent Events of new/updated events. Falls back to polling
    if Mongo isn't running as a replica set (i.e. local dev)."""

    async def _generator() -> Any:
        try:
            async for doc in stream_event_changes(mongo, poll_fallback_seconds=15):
                if await request.is_disconnected():
                    break
                payload = json.dumps(doc, default=str)
                yield {"event": "event", "data": payload}
        except asyncio.CancelledError:
            return

    return EventSourceResponse(_generator())
