"""Tenant-authenticated durable job submission and status API."""
from __future__ import annotations

import re
from typing import Any

from fastapi import APIRouter, Header, HTTPException
from pydantic import BaseModel, Field

from .durable_jobs import JobQueueError, enqueue_tenant_job, tenant_job_status
from .job_payload_store import JobPayloadError, delete_payload, get_payload, put_payload
from .worker_runtime import worker_ready
from .tenant_auth import authenticate_tenant_key

router = APIRouter()


class JobSubmitRequest(BaseModel):
    repository: str = Field(min_length=3, max_length=201)
    job_type: str = Field(min_length=2, max_length=80)
    idempotency_key: str = Field(min_length=1, max_length=128)
    payload: dict[str, Any]
    max_attempts: int = Field(default=5, ge=1, le=20)


def _tenant(raw_key: str | None) -> dict:
    try:
        identity = authenticate_tenant_key(raw_key)
    except RuntimeError as exc:
        raise HTTPException(status_code=503, detail="Tenant authentication is not configured") from exc
    if not identity:
        raise HTTPException(status_code=401, detail="Valid X-Tenant-Key is required")
    return identity


@router.post("/api/jobs", status_code=202)
async def submit_job(request: JobSubmitRequest, x_tenant_key: str | None = Header(default=None)):
    """Encrypt and enqueue a job for the authenticated tenant."""
    identity = _tenant(x_tenant_key)
    repository = request.repository.strip().lower()
    if repository not in [item.lower() for item in identity.get("repositories", [])]:
        raise HTTPException(status_code=403, detail="Repository is not assigned to this tenant")
    if "jobs:enqueue" not in identity.get("scopes", []):
        raise HTTPException(status_code=403, detail="Tenant key lacks jobs:enqueue scope")
    if request.job_type != "chat.completion":
        raise HTTPException(status_code=422, detail="Only chat.completion jobs are currently supported")
    if not worker_ready():
        raise HTTPException(status_code=503, detail="Durable job execution is disabled; enable JOB_WORKER_ENABLED after configuring the required secrets")

    payload_ref = None
    try:
        payload_ref = put_payload(request.payload)
        result = enqueue_tenant_job(
            repository, request.job_type, payload_ref, request.idempotency_key,
            tenant_identity=identity, max_attempts=request.max_attempts,
        )
        if result.get("idempotent_replay"):
            delete_payload(payload_ref)
        return {
            "job_id": result["id"],
            "repository": result["repository"],
            "job_type": result["job_type"],
            "status": result["status"],
            "idempotent_replay": result["idempotent_replay"],
            "created_at": result["created_at"],
        }
    except JobPayloadError as exc:
        if payload_ref:
            delete_payload(payload_ref)
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    except JobQueueError as exc:
        if payload_ref:
            delete_payload(payload_ref)
        raise HTTPException(status_code=403, detail=str(exc)) from exc


@router.get("/api/jobs/{job_id}")
async def get_job_status(
    job_id: str,
    repository: str,
    x_tenant_key: str | None = Header(default=None),
):
    """Expose status only to the exact tenant key/user that submitted the job."""
    identity = _tenant(x_tenant_key)
    result = tenant_job_status(job_id, repository=repository, tenant_identity=identity)
    if result is None:
        raise HTTPException(status_code=404, detail="Job not found")
    result_ref = result.pop("result_ref", None)
    if result_ref:
        try:
            stored = get_payload(result_ref)
            result["result"] = stored.get("result") if isinstance(stored, dict) else stored
        except JobPayloadError:
            result["result_expired"] = True
    else:
        result["result"] = None
    return result
