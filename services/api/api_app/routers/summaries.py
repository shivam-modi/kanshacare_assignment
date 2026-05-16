"""On-demand summary requests — enqueue an arq job, return 202.

The actual job lives in worker-svc (Phase 5). The job name + queue are the
contract: api-svc only needs to enqueue and surface job status. If worker-svc
isn't running yet (Phase 1-4 builds), the request still queues — the work
just sits there until a worker drains it.
"""

from __future__ import annotations

from typing import Annotated

from arq.connections import ArqRedis
from arq.jobs import Job
from fastapi import APIRouter, Body, Request
from pydantic import BaseModel, Field
from slowapi import Limiter
from slowapi.util import get_remote_address

from kanshacare_shared.errors import NotFoundError
from kanshacare_shared.logging import get_logger

from ..deps import ArqDep, SettingsDep

router = APIRouter(prefix="/summaries", tags=["summaries"])
log = get_logger(__name__)

limiter = Limiter(key_func=get_remote_address)

QUEUE_NAME = "kanshacare:summaries"
JOB_NAME = "summary_job"


class SummaryRequest(BaseModel):
    """Either send to a single chat_id (if provided) or broadcast to all subscribers."""

    chat_id: int | None = Field(
        default=None,
        description="Telegram chat_id. Omit to broadcast to all /start-ed subscribers.",
    )


@router.post("/request", status_code=202)
@limiter.limit("1/minute")
async def request_summary(
    request: Request,
    arq: ArqDep,
    settings: SettingsDep,
    body: Annotated[SummaryRequest, Body(default_factory=SummaryRequest)],
) -> dict[str, str | None]:
    job = await arq.enqueue_job(
        JOB_NAME,
        chat_id=body.chat_id,
        _queue_name=QUEUE_NAME,
    )
    if job is None:
        # arq returns None if the same job is already queued (dedup by ID).
        return {"status": "already_queued", "job_id": None}
    return {"status": "queued", "job_id": job.job_id}


@router.get("/{job_id}")
async def job_status(arq: ArqDep, job_id: str) -> dict[str, str | None]:
    job_info = await _fetch_job(arq, job_id)
    if job_info is None:
        raise NotFoundError(f"job not found: {job_id}")
    return job_info


async def _fetch_job(arq: ArqRedis, job_id: str) -> dict[str, str | None] | None:
    """Look up an arq job's status from Redis. Returns None if it isn't tracked."""
    job = Job(job_id, arq, _queue_name=QUEUE_NAME)
    try:
        status = await job.status()
    except Exception:
        return None
    if status is None:
        return None
    return {"job_id": job_id, "status": str(status)}
