"""Tenant-scoped evidence provenance registry API."""
from __future__ import annotations

from fastapi import APIRouter, Header, HTTPException, Query
from pydantic import BaseModel, Field

from .evidence_store import EvidenceConflict, EvidenceStoreError, register_evidence, list_evidence
from .tenant_auth import authenticate_tenant_key

router = APIRouter()


class EvidenceRecordRequest(BaseModel):
    repository: str = Field(min_length=3, max_length=201)
    domain: str = Field(pattern=r"^(forex|youtube|ptc|nft)$")
    source_id: str = Field(min_length=1, max_length=80)
    text: str = Field(min_length=1, max_length=5000)
    publisher: str | None = Field(default=None, max_length=160)
    source_url: str | None = Field(default=None, max_length=2048)
    observed_at: str | None = Field(default=None, max_length=40)


def _identity(raw_key: str | None, repository: str, scope: str) -> dict:
    try:
        identity = authenticate_tenant_key(raw_key)
    except RuntimeError as exc:
        raise HTTPException(status_code=503, detail="Tenant authentication is not configured") from exc
    if not identity:
        raise HTTPException(status_code=401, detail="Valid X-Tenant-Key is required")
    repo = repository.strip().lower()
    if repo not in [item.lower() for item in identity.get("repositories", [])]:
        raise HTTPException(status_code=403, detail="Repository is not assigned to this tenant")
    if scope not in identity.get("scopes", []):
        raise HTTPException(status_code=403, detail=f"Tenant key lacks {scope} scope")
    return identity


@router.post("/api/evidence", status_code=201)
async def create_evidence_record(request: EvidenceRecordRequest, x_tenant_key: str | None = Header(default=None)):
    identity = _identity(x_tenant_key, request.repository, "evidence:write")
    try:
        record = register_evidence(
            identity=identity, repository=request.repository.strip().lower(),
            domain=request.domain, item=request.model_dump(exclude={"repository", "domain"}),
        )
    except EvidenceConflict as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    except EvidenceStoreError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    return {
        "evidence_id": record["evidence_id"], "repository": record["repository"],
        "domain": record["domain"], "source_id": record["source_id"],
        "content_sha256": record["content_sha256"], "content_chars": record["content_chars"],
        "publisher": record["publisher"], "source_host": record["source_host"],
        "observed_at": record["observed_at"], "freshness": record["freshness"],
        "created_at": record["created_at"], "idempotent_replay": record["idempotent_replay"],
        "content_stored": False,
    }


@router.get("/api/evidence")
async def get_evidence_records(
    repository: str = Query(min_length=3, max_length=201),
    domain: str | None = Query(default=None, pattern=r"^(forex|youtube|ptc|nft)$"),
    limit: int = Query(default=50, ge=1, le=100),
    x_tenant_key: str | None = Header(default=None),
):
    identity = _identity(x_tenant_key, repository, "evidence:read")
    records = list_evidence(identity=identity, repository=repository.strip().lower(), domain=domain, limit=limit)
    return {"repository": repository.strip().lower(), "count": len(records), "records": records}
