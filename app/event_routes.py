"""Tenant-authenticated publish, claim, settle and inspect APIs for platform events."""
from __future__ import annotations

from typing import Any
import hashlib
import json
from fastapi import APIRouter, Header, HTTPException
from pydantic import BaseModel, Field

from .event_bus import EventBusError, claim_event, list_events, publish_event, settle_event
from .job_payload_store import JobPayloadError, delete_payload, get_payload, put_payload
from .tenant_auth import authenticate_tenant_key

router = APIRouter()


class PublishRequest(BaseModel):
    repository: str = Field(min_length=3, max_length=201)
    event_type: str = Field(min_length=2, max_length=120)
    schema_version: int = Field(ge=1, le=1000)
    producer: str = Field(min_length=1, max_length=120)
    consumer: str = Field(min_length=1, max_length=120)
    idempotency_key: str = Field(min_length=1, max_length=128)
    payload: dict[str, Any]
    correlation_id: str | None = Field(default=None, max_length=64)
    causation_id: str | None = Field(default=None, max_length=64)
    max_attempts: int = Field(default=5, ge=1, le=20)


class ClaimRequest(BaseModel):
    repository: str = Field(min_length=3, max_length=201)
    consumer: str = Field(min_length=1, max_length=120)
    worker_id: str = Field(min_length=1, max_length=100)
    lease_seconds: int = Field(default=60, ge=10, le=3600)


class SettleRequest(BaseModel):
    repository: str = Field(min_length=3, max_length=201)
    worker_id: str = Field(min_length=1, max_length=100)
    success: bool
    retryable: bool = True


def _tenant(raw_key):
    try:
        identity = authenticate_tenant_key(raw_key)
    except RuntimeError as exc:
        raise HTTPException(status_code=503, detail="Tenant authentication is not configured") from exc
    if not identity:
        raise HTTPException(status_code=401, detail="Valid X-Tenant-Key is required")
    return identity


def _error(exc):
    message = str(exc)
    status = 403 if "scope" in message or "assigned" in message else 422
    raise HTTPException(status_code=status, detail=message) from exc


@router.post("/api/events", status_code=202)
async def publish(request: PublishRequest, x_tenant_key: str | None = Header(default=None)):
    identity = _tenant(x_tenant_key)
    reference = None
    try:
        reference = put_payload(request.payload)
        result = publish_event(identity=identity, repository=request.repository,
            event_type=request.event_type, schema_version=request.schema_version,
            producer=request.producer, consumer=request.consumer,
            idempotency_key=request.idempotency_key, payload_ref=reference,
            payload_hash=hashlib.sha256(json.dumps(request.payload, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")).hexdigest(),
            correlation_id=request.correlation_id, causation_id=request.causation_id,
            max_attempts=request.max_attempts)
        if result["idempotent_replay"]:
            delete_payload(reference)
        return result
    except JobPayloadError as exc:
        if reference:
            delete_payload(reference)
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    except EventBusError as exc:
        if reference:
            delete_payload(reference)
        _error(exc)


@router.post("/api/events/claim")
async def claim(request: ClaimRequest, x_tenant_key: str | None = Header(default=None)):
    try:
        event = claim_event(identity=_tenant(x_tenant_key), repository=request.repository,
            consumer=request.consumer, worker_id=request.worker_id, lease_seconds=request.lease_seconds)
        if event:
            event["payload"] = get_payload(event["payload_ref"])
        return {"event": event}
    except (EventBusError, JobPayloadError) as exc:
        _error(exc)


@router.post("/api/events/{event_id}/settle")
async def settle(event_id: str, request: SettleRequest, x_tenant_key: str | None = Header(default=None)):
    try:
        return settle_event(identity=_tenant(x_tenant_key), repository=request.repository,
            event_id=event_id, worker_id=request.worker_id, success=request.success,
            retryable=request.retryable)
    except EventBusError as exc:
        _error(exc)


@router.get("/api/events")
async def inspect(repository: str, limit: int = 50, x_tenant_key: str | None = Header(default=None)):
    try:
        events = list_events(identity=_tenant(x_tenant_key), repository=repository, limit=limit)
        return {"repository": repository.strip().lower(), "count": len(events), "events": events}
    except EventBusError as exc:
        _error(exc)
