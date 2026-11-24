"""Admin-only, bounded dead-letter recovery endpoints."""
from __future__ import annotations

import re
import secrets

from fastapi import APIRouter, Header, HTTPException
from pydantic import BaseModel, Field

from .config import settings
from .durable_jobs import job_queue_summary, requeue_dead_letter_job, list_job_admin_events
from .worker_heartbeat import worker_health

router = APIRouter()


class DeadLetterRequeueRequest(BaseModel):
    repository: str = Field(min_length=3, max_length=201)
    expected_updated_at: str = Field(min_length=20, max_length=64)
    confirm: bool


def _require_admin(raw_key: str | None) -> None:
    if not settings.admin_api_key:
        raise HTTPException(status_code=503, detail="ADMIN_API_KEY is not configured")
    if not raw_key or not secrets.compare_digest(raw_key, settings.admin_api_key):
        raise HTTPException(status_code=401, detail="Unauthorized")


@router.get("/api/admin/jobs/summary")
async def admin_job_summary(
    repository: str | None = None,
    x_admin_key: str | None = Header(default=None),
):
    _require_admin(x_admin_key)
    if repository and not re.fullmatch(
        r"[a-z0-9][a-z0-9._-]{0,99}/[a-z0-9][a-z0-9._-]{0,99}",
        repository.strip().lower(),
    ):
        raise HTTPException(status_code=422, detail="Invalid repository identity")
    try:
        return {
            "queue": job_queue_summary(repository),
            "worker": worker_health(),
            "notes": [
                "Counts contain no job IDs, tenant IDs, prompts, payloads, secrets, or filesystem paths.",
                "Worker heartbeat is a liveness signal, not proof of provider reachability.",
                "Queue metrics reflect the configured SQLite database and require persistent storage for durability.",
            ],
        }
    except Exception as exc:
        raise HTTPException(status_code=503, detail="Queue observability is temporarily unavailable") from exc


@router.post("/api/admin/jobs/{job_id}/requeue")
async def admin_requeue_dead_letter(
    job_id: str,
    request: DeadLetterRequeueRequest,
    x_admin_key: str | None = Header(default=None),
):
    """Requeue one dead-letter job only after explicit confirmation and version match."""
    _require_admin(x_admin_key)
    if request.confirm is not True:
        raise HTTPException(status_code=400, detail="Explicit confirmation is required")
    repository = request.repository.strip().lower()
    if not re.fullmatch(r"[a-z0-9][a-z0-9._-]{0,99}/[a-z0-9][a-z0-9._-]{0,99}", repository):
        raise HTTPException(status_code=422, detail="Invalid repository identity")
    if not re.fullmatch(r"[0-9a-fA-F-]{36}", job_id):
        raise HTTPException(status_code=422, detail="Invalid job identifier")
    try:
        result = requeue_dead_letter_job(job_id, repository, request.expected_updated_at)
    except Exception as exc:
        raise HTTPException(status_code=503, detail="Dead-letter recovery is temporarily unavailable") from exc
    if result is None:
        raise HTTPException(
            status_code=409,
            detail="Job is not recoverable: it may have changed, reached the retry limit, or its encrypted payload expired",
        )
    return {"requeued": True, "job": result}



@router.get("/api/admin/jobs/recovery-audit")
async def admin_job_recovery_audit(
    repository: str | None = None,
    limit: int = 50,
    before_event_at: str | None = None,
    x_admin_key: str | None = Header(default=None),
):
    """Return a bounded, metadata-only audit trail for operator recovery actions."""
    _require_admin(x_admin_key)
    try:
        events = list_job_admin_events(
            repository=repository, limit=limit, before_event_at=before_event_at
        )
        return {
            "events": events,
            "count": len(events),
            "limit": limit,
            "next_before_event_at": events[-1]["event_at"] if len(events) == limit else None,
            "notes": [
                "This audit trail records operator recovery actions only.",
                "It contains no prompts, encrypted payloads, provider credentials, or tenant API keys.",
                "Use repository filtering and the returned cursor to page through older events.",
            ],
        }
    except Exception as exc:
        from .durable_jobs import JobQueueError
        if isinstance(exc, JobQueueError):
            raise HTTPException(status_code=422, detail=str(exc))
        raise HTTPException(status_code=503, detail="Recovery audit is temporarily unavailable") from exc
