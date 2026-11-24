"""Admin-only aggregate observability for the durable job queue."""
from __future__ import annotations

import re
import secrets

from fastapi import APIRouter, Header, HTTPException, Query

from .config import settings
from .durable_jobs import job_queue_summary
from .worker_heartbeat import worker_health

router = APIRouter()


def _require_admin(raw_key: str | None) -> None:
    if not settings.admin_api_key:
        raise HTTPException(status_code=503, detail="ADMIN_API_KEY is not configured")
    if not raw_key or not secrets.compare_digest(raw_key, settings.admin_api_key):
        raise HTTPException(status_code=401, detail="Unauthorized")


@router.get("/api/admin/jobs/summary")
async def admin_job_summary(
    repository: str | None = Query(default=None, min_length=3, max_length=201),
    x_admin_key: str | None = Header(default=None),
):
    """Expose aggregate queue and worker health only to the operator admin key."""
    _require_admin(x_admin_key)
    if repository and not re.fullmatch(
        r"[a-z0-9][a-z0-9._-]{0,99}/[a-z0-9][a-z0-9._-]{0,99}",
        repository.strip().lower(),
    ):
        raise HTTPException(status_code=422, detail="Invalid repository identity")
    try:
        queue = job_queue_summary(repository)
        worker = worker_health()
    except Exception as exc:
        # Keep internal database errors and paths out of the public response.
        raise HTTPException(status_code=503, detail="Queue observability is temporarily unavailable") from exc
    return {
        "queue": queue,
        "worker": worker,
        "notes": [
            "Counts contain no job IDs, tenant IDs, prompts, payloads, secrets, or filesystem paths.",
            "Worker heartbeat is a liveness signal, not proof of provider reachability.",
            "Queue metrics reflect the configured SQLite database and require persistent storage for durability.",
        ],
    }
