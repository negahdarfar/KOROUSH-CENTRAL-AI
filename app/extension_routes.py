"""Admin registration and tenant-scoped discovery of dynamic extension manifests."""
from __future__ import annotations

import secrets

from fastapi import APIRouter, Header, HTTPException, Query
from pydantic import BaseModel, Field

from .config import settings
from .extension_registry import ExtensionRegistryError, list_extensions, register_extension
from .tenant_auth import authenticate_tenant_key

router = APIRouter()


class ExtensionManifestRequest(BaseModel):
    manifest: dict = Field()


def _admin_ok(raw_key: str | None) -> bool:
    return bool(settings.admin_api_key and raw_key and secrets.compare_digest(raw_key, settings.admin_api_key))


@router.post("/api/extensions", status_code=201)
async def create_extension(request: ExtensionManifestRequest, x_admin_key: str | None = Header(default=None)):
    if not _admin_ok(x_admin_key):
        raise HTTPException(status_code=401, detail="Valid X-Admin-Key is required")
    try:
        return {"extension": register_extension(request.manifest)}
    except ExtensionRegistryError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


@router.get("/api/extensions")
async def discover_extensions(
    repository: str = Query(min_length=3, max_length=201),
    kind: str | None = Query(default=None, max_length=30),
    x_tenant_key: str | None = Header(default=None),
    x_admin_key: str | None = Header(default=None),
):
    if not _admin_ok(x_admin_key):
        try:
            identity = authenticate_tenant_key(x_tenant_key)
        except RuntimeError as exc:
            raise HTTPException(status_code=503, detail="Tenant authentication is not configured") from exc
        if not identity:
            raise HTTPException(status_code=401, detail="Valid X-Tenant-Key or X-Admin-Key is required")
        repo = repository.strip().lower()
        if repo not in [value.lower() for value in identity.get("repositories", [])]:
            raise HTTPException(status_code=403, detail="Repository is not assigned to this tenant")
        if "registry:read" not in identity.get("scopes", []):
            raise HTTPException(status_code=403, detail="Tenant key lacks registry:read scope")
    try:
        items = list_extensions(repository=repository, kind=kind, include_disabled=_admin_ok(x_admin_key))
    except ExtensionRegistryError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    return {"repository": repository.strip().lower(), "count": len(items), "extensions": items}
