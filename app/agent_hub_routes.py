"""Tenant-aware discovery endpoints for the central agent hub."""
from __future__ import annotations

import secrets

from fastapi import APIRouter, Header, HTTPException, Query

from .agent_registry import get_agent, list_agents, list_apis, platform_manifest
from .config import settings
from .tenant_auth import TenantAuthError, authenticate_tenant_key

router = APIRouter()


def _admin_ok(raw_key: str | None) -> bool:
    return bool(
        settings.admin_api_key and raw_key
        and secrets.compare_digest(raw_key, settings.admin_api_key)
    )


def _tenant_identity(raw_key: str | None, repository: str | None) -> dict:
    try:
        identity = authenticate_tenant_key(raw_key)
    except RuntimeError as exc:
        raise HTTPException(status_code=503, detail="Tenant authentication is not configured") from exc
    if not identity:
        raise HTTPException(status_code=401, detail="Valid X-Tenant-Key or X-Admin-Key is required")
    repo = (repository or "").strip().lower()
    if not repo or repo not in [item.lower() for item in identity.get("repositories", [])]:
        raise HTTPException(status_code=403, detail="Repository is not assigned to this tenant")
    return identity


@router.get("/api/platform/manifest")
async def get_platform_manifest():
    """Public, non-secret integration contract and capability discovery."""
    return platform_manifest()


@router.get("/api/agents")
async def agents_catalog(
    repository: str | None = Query(default=None, min_length=3, max_length=201),
    x_tenant_key: str | None = Header(default=None),
    x_admin_key: str | None = Header(default=None),
):
    """List only agents the caller is allowed to discover."""
    if _admin_ok(x_admin_key):
        return {"repository": repository, "agents": list_agents(include_operator=True)}
    identity = _tenant_identity(x_tenant_key, repository)
    scopes = set(identity.get("scopes", []))
    visible = []
    for agent in list_agents(include_operator=False):
        required = set(agent.get("required_scopes", []))
        if required.issubset(scopes):
            visible.append(agent)
    return {
        "repository": repository.strip().lower(),
        "team_id": identity.get("team_id"),
        "agents": visible,
        "notes": ["Only agents whose declared scopes are held by this tenant key are listed."],
    }


@router.get("/api/agents/{agent_id}")
async def agent_details(
    agent_id: str,
    repository: str | None = Query(default=None, min_length=3, max_length=201),
    x_tenant_key: str | None = Header(default=None),
    x_admin_key: str | None = Header(default=None),
):
    if _admin_ok(x_admin_key):
        agent = get_agent(agent_id)
        if not agent:
            raise HTTPException(status_code=404, detail="Agent not found")
        return agent
    identity = _tenant_identity(x_tenant_key, repository)
    agent = get_agent(agent_id)
    if not agent or "operator" in agent.get("required_scopes", []):
        raise HTTPException(status_code=404, detail="Agent not found")
    if not set(agent.get("required_scopes", [])).issubset(set(identity.get("scopes", []))):
        raise HTTPException(status_code=403, detail="Tenant key lacks the required agent scopes")
    return agent



@router.get("/api/apis")
async def api_catalog(
    repository: str | None = Query(default=None, min_length=3, max_length=201),
    x_tenant_key: str | None = Header(default=None),
    x_admin_key: str | None = Header(default=None),
):
    """Discover central API contracts with authentication requirements visible."""
    if _admin_ok(x_admin_key):
        return {"repository": repository, "apis": list_apis(include_admin=True)}
    identity = _tenant_identity(x_tenant_key, repository)
    scopes = set(identity.get("scopes", []))
    visible = []
    for api in list_apis(include_admin=False):
        auth = api["auth"]
        if auth == "tenant:jobs:enqueue+inference:chat" and not {
            "jobs:enqueue", "inference:chat"
        }.issubset(scopes):
            continue
        if auth == "tenant:jobs:read" and "jobs:read" not in scopes:
            continue
        if auth == "tenant:evidence:write" and "evidence:write" not in scopes:
            continue
        if auth == "tenant:evidence:read" and "evidence:read" not in scopes:
            continue
        if auth == "tenant:registry:read" and "registry:read" not in scopes:
            continue
        if auth == "tenant-or-admin" and "inference:chat" not in scopes:
            continue
        visible.append(api)
    return {"repository": repository.strip().lower(), "apis": visible}
