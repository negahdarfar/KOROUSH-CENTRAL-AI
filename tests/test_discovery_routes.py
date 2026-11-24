import asyncio
from datetime import datetime, timezone

import httpx
import pytest
from fastapi import HTTPException

from app import discovery_routes
from app.config import settings
from app.discovery_engine import ResourceCandidate


def sample_candidate():
    return ResourceCandidate(
        source_id="owner/agent-project",
        name="Agent Project",
        url="https://github.com/owner/agent-project",
        kind="agent",
        description="An open agent framework",
        stars=150,
        forks=20,
        archived=False,
        pushed_at="2026-11-01T00:00:00Z",
        license_spdx="MIT",
    )


def test_admin_discovery_returns_review_only_candidates(monkeypatch):
    monkeypatch.setattr(settings, "admin_api_key", "test-admin-key")

    async def fake_search(query, token=""):
        assert query.kind == "agent"
        assert query.terms == ("agent framework",)
        assert query.limit == 3
        return [sample_candidate()]

    monkeypatch.setattr(discovery_routes, "search_github_repositories", fake_search)
    request = discovery_routes.DiscoverySearchRequest(
        kind="agent", terms=["agent framework"], limit=3, require_recent_days=730
    )
    result = asyncio.run(
        discovery_routes.discover_resources(request, x_admin_key="test-admin-key")
    )

    assert result["source"] == "github-public-search"
    assert result["count"] == 1
    item = result["results"][0]
    assert item["source_id"] == "owner/agent-project"
    assert item["registration"] == "requires_admin_review"
    assert item["assessment"]["free_status"] == "unverified"
    assert result["safety"] == {
        "auto_registration": False,
        "code_execution": False,
        "installation": False,
        "pricing_verified": False,
        "tenant_assignment": False,
    }


def test_discovery_requires_admin_key(monkeypatch):
    monkeypatch.setattr(settings, "admin_api_key", "test-admin-key")
    request = discovery_routes.DiscoverySearchRequest(
        kind="repository", terms=["agent"]
    )
    with pytest.raises(HTTPException) as denied:
        asyncio.run(discovery_routes.discover_resources(request, x_admin_key="wrong"))
    assert denied.value.status_code == 401


def test_discovery_maps_upstream_timeout_to_gateway_timeout(monkeypatch):
    monkeypatch.setattr(settings, "admin_api_key", "test-admin-key")

    async def timeout_search(query, token=""):
        raise httpx.TimeoutException("simulated timeout")

    monkeypatch.setattr(discovery_routes, "search_github_repositories", timeout_search)
    request = discovery_routes.DiscoverySearchRequest(
        kind="repository", terms=["agent"]
    )
    with pytest.raises(HTTPException) as timed_out:
        asyncio.run(
            discovery_routes.discover_resources(request, x_admin_key="test-admin-key")
        )
    assert timed_out.value.status_code == 504
