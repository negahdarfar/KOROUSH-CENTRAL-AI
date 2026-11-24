"""Admin-only live discovery API for public GitHub repository metadata."""
from __future__ import annotations

import secrets

import httpx
from fastapi import APIRouter, Header, HTTPException
from pydantic import BaseModel, ConfigDict, Field

from .config import settings
from .discovery_engine import DiscoveryQuery, IntelligentDiscoveryEngine, search_github_repositories

router = APIRouter()


class DiscoverySearchRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    kind: str = Field(default="repository", pattern=r"^(repository|agent|model|api|tool|dataset|connector)$")
    terms: list[str] = Field(min_length=1, max_length=8)
    limit: int = Field(default=20, ge=1, le=50)
    require_recent_days: int = Field(default=730, ge=1, le=3650)


def _require_admin(raw_key: str | None) -> None:
    if not settings.admin_api_key or not raw_key or not secrets.compare_digest(raw_key, settings.admin_api_key):
        raise HTTPException(status_code=401, detail="Valid X-Admin-Key is required")


@router.post("/api/admin/discovery/search")
async def discover_resources(
    request: DiscoverySearchRequest,
    x_admin_key: str | None = Header(default=None),
):
    """Search public GitHub metadata; returns review candidates and never auto-registers them."""
    _require_admin(x_admin_key)
    try:
        query = DiscoveryQuery(
            kind=request.kind,
            terms=tuple(request.terms),
            require_recent_days=request.require_recent_days,
            limit=request.limit,
        )
        candidates = await search_github_repositories(query, token=settings.github_token)
        class _Backend:
            def search(self, _query):
                return candidates
        assessments = IntelligentDiscoveryEngine(_Backend()).discover(query)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    except httpx.TimeoutException as exc:
        raise HTTPException(status_code=504, detail="GitHub discovery timed out") from exc
    except httpx.HTTPStatusError as exc:
        status = exc.response.status_code
        if status == 401 or status == 403:
            raise HTTPException(status_code=503, detail="GitHub search access or rate limit is unavailable") from exc
        raise HTTPException(status_code=502, detail="GitHub search returned an upstream error") from exc
    except (httpx.HTTPError, RuntimeError) as exc:
        raise HTTPException(status_code=502, detail="GitHub discovery could not complete safely") from exc

    by_id = {item.source_id: item for item in assessments}
    return {
        "source": "github-public-search",
        "count": len(candidates),
        "results": [
            {
                "source_id": item.source_id,
                "name": item.name,
                "url": item.url,
                "kind": item.kind,
                "description": item.description,
                "stars": item.stars,
                "forks": item.forks,
                "pushed_at": item.pushed_at,
                "license_spdx": item.license_spdx,
                "assessment": {
                    "score": by_id[item.source_id].score,
                    "status": by_id[item.source_id].status,
                    "free_status": by_id[item.source_id].free_status,
                    "reasons": list(by_id[item.source_id].reasons),
                    "missing_evidence": list(by_id[item.source_id].missing_evidence),
                },
                "registration": "requires_admin_review",
            }
            for item in candidates
        ],
        "safety": {
            "auto_registration": False,
            "code_execution": False,
            "installation": False,
            "pricing_verified": False,
            "tenant_assignment": False,
        },
    }
