"""Admin-only lifecycle endpoints for tenant API credentials."""
import secrets

from fastapi import APIRouter, Header, HTTPException
from pydantic import BaseModel, Field

from .config import settings
from .tenant_auth import TenantAuthError, create_tenant_key, list_tenant_keys, revoke_tenant_key

router = APIRouter()


class TenantKeyCreateRequest(BaseModel):
    user_id: str = Field(min_length=1, max_length=128)
    team_id: str = Field(min_length=1, max_length=128)
    repositories: list[str] = Field(min_length=1, max_length=50)
    scopes: list[str] = Field(default_factory=lambda: ["inference:chat"], max_length=5)


def _require_admin(key: str | None) -> None:
    if not settings.admin_api_key:
        raise HTTPException(status_code=503, detail="ADMIN_API_KEY is not configured")
    if not key or not secrets.compare_digest(key, settings.admin_api_key):
        raise HTTPException(status_code=401, detail="Unauthorized")


@router.post("/api/admin/tenant-keys")
async def create_tenant_api_key(
    request: TenantKeyCreateRequest,
    x_admin_key: str | None = Header(default=None),
):
    """Create a team/user-scoped key. The raw key is returned exactly once."""
    _require_admin(x_admin_key)
    try:
        return create_tenant_key(
            user_id=request.user_id,
            team_id=request.team_id,
            repositories=request.repositories,
            scopes=request.scopes,
        )
    except TenantAuthError as exc:
        raise HTTPException(status_code=422, detail=str(exc))
    except RuntimeError as exc:
        raise HTTPException(status_code=503, detail=str(exc))


@router.get("/api/admin/tenant-keys")
async def get_tenant_api_keys(
    team_id: str | None = None,
    x_admin_key: str | None = Header(default=None),
):
    _require_admin(x_admin_key)
    return {"keys": list_tenant_keys(team_id=team_id)}


@router.post("/api/admin/tenant-keys/{key_id}/revoke")
async def revoke_tenant_api_key(
    key_id: str,
    x_admin_key: str | None = Header(default=None),
):
    _require_admin(x_admin_key)
    return {"key_id": key_id, "revoked": revoke_tenant_key(key_id)}
