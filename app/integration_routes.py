"""Tenant-authenticated entry points for the four central domain workflows."""
from __future__ import annotations

import hashlib
import json
from typing import Any

from fastapi import APIRouter, Header, HTTPException
from pydantic import BaseModel, Field

from .agent_workflows import AgentWorkflowInputError, validate_domain_workflow_input
from .durable_jobs import IdempotencyConflict, JobQueueError, enqueue_tenant_job
from .integration_profiles import get_integration_profile, list_integration_profiles
from .extension_registry import list_extensions
from .job_payload_store import JobPayloadError, delete_payload, put_payload
from .tenant_auth import authenticate_tenant_key
from .worker_runtime import worker_ready

router = APIRouter()


class DomainResearchRequest(BaseModel):
    repository: str = Field(min_length=3, max_length=201)
    idempotency_key: str = Field(min_length=1, max_length=128)
    evidence: list[dict[str, Any]]
    target_language: str | None = Field(default=None, min_length=1, max_length=80)
    max_attempts: int = Field(default=3, ge=1, le=10)


def _tenant(raw_key: str | None) -> dict:
    try:
        identity = authenticate_tenant_key(raw_key)
    except RuntimeError as exc:
        raise HTTPException(status_code=503, detail="Tenant authentication is not configured") from exc
    if not identity:
        raise HTTPException(status_code=401, detail="Valid X-Tenant-Key is required")
    return identity


@router.get("/api/integrations")
async def integrations_catalog():
    """List executable shared-core integration contracts without exposing secrets."""
    return {"integrations": list_integration_profiles()}


@router.post("/api/integrations/{domain}/research", status_code=202)
async def submit_domain_research(
    domain: str,
    request: DomainResearchRequest,
    x_tenant_key: str | None = Header(default=None),
):
    identity = _tenant(x_tenant_key)
    repository = request.repository.strip().lower()
    if repository not in [str(item).lower() for item in identity.get("repositories", [])]:
        raise HTTPException(status_code=403, detail="Repository is not assigned to this tenant")

    # Built-in adapters are stable aliases. Future repositories can use the
    # same endpoint by registering an approved connector manifest; no new route
    # or central code change is needed for another general research consumer.
    profile = get_integration_profile(f"koroush.{domain}")
    if profile and profile.get("execution") == "durable-job":
        workflow_domain = domain
        workflow_id = f"koroush.{domain}.research.v1"
        integration_id = f"koroush.{domain}"
    else:
        try:
            registered = list_extensions(repository=repository, kind="connector")
        except Exception as exc:
            raise HTTPException(status_code=503, detail="Integration registry is unavailable") from exc
        extension = next((
            item for item in registered
            if item.get("extension_id") == domain
            and item.get("status") == "active"
            and "general" in item.get("domains", [])
            and "research.workflow.v1" in item.get("capabilities", [])
            and repository in [str(value).lower() for value in item.get("repositories", [])]
        ), None)
        if not extension:
            raise HTTPException(status_code=404, detail="Registered research integration not found")
        workflow_domain = "general"
        integration_id = extension["extension_id"]
        workflow_id = f"{integration_id}@{extension['version']}.research.v1"
    scopes = set(identity.get("scopes", []))
    if not {"jobs:enqueue", "inference:chat"}.issubset(scopes):
        raise HTTPException(status_code=403, detail="Tenant key lacks jobs:enqueue or inference:chat scope")
    if not worker_ready():
        raise HTTPException(status_code=503, detail="Durable job worker is disabled or not configured")

    try:
        payload = validate_domain_workflow_input({
            "domain": domain,
            "evidence": request.evidence,
            "target_language": request.target_language,
        })
    except AgentWorkflowInputError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc

    payload_ref = None
    try:
        payload_ref = put_payload(payload)
        payload_hash = hashlib.sha256(
            json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
        ).hexdigest()
        result = enqueue_tenant_job(
            repository, "agent.workflow", payload_ref, request.idempotency_key,
            tenant_identity=identity, max_attempts=request.max_attempts,
            payload_hash=payload_hash,
        )
        if result.get("idempotent_replay"):
            delete_payload(payload_ref)
        return {
            "job_id": result["id"],
            "repository": result["repository"],
            "domain": domain,
            "workflow_id": f"koroush.{domain}.research.v1",
            "job_type": "agent.workflow",
            "status": result["status"],
            "idempotent_replay": result["idempotent_replay"],
            "created_at": result["created_at"],
            "status_api": f"/api/jobs/{result['id']}?repository={repository}",
        }
    except IdempotencyConflict as exc:
        if payload_ref:
            delete_payload(payload_ref)
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    except JobPayloadError as exc:
        if payload_ref:
            delete_payload(payload_ref)
        raise HTTPException(status_code=503, detail="Secure job payload storage is unavailable") from exc
    except JobQueueError as exc:
        if payload_ref:
            delete_payload(payload_ref)
        raise HTTPException(status_code=403, detail=str(exc)) from exc
