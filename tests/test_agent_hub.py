import asyncio

import pytest
from fastapi import HTTPException

from app import agent_hub_routes as routes
from app.agent_registry import get_agent, list_agents, platform_manifest
from app.config import settings


def test_platform_manifest_is_non_secret_and_marks_incomplete_transports():
    manifest = platform_manifest()
    assert manifest["integration_model"] == "central-control-plane"
    assert manifest["contract"]["job_submission"] == "POST /api/jobs"
    assert "api_key" not in str(manifest).lower()
    capabilities = {item["id"]: item["status"] for item in manifest["capabilities"]}
    assert capabilities["audio.transcription"] == "planned"
    assert capabilities["repository.custom_agent"] == "planned"


def test_registry_returns_defensive_copies():
    first = get_agent("koroush.model-router")
    first["name"] = "tampered"
    assert get_agent("koroush.model-router")["name"] == "Central Model Router"
    assert all("operator" not in item["required_scopes"] for item in list_agents(include_operator=False))


def test_tenant_agent_catalog_is_scope_filtered(monkeypatch):
    monkeypatch.setattr(routes, "authenticate_tenant_key", lambda key: {
        "team_id": "engineering",
        "repositories": ["org/repo"],
        "scopes": ["inference:chat"],
    })
    result = asyncio.run(routes.agents_catalog(
        repository="org/repo", x_tenant_key="kor_test", x_admin_key=None
    ))
    ids = {item["id"] for item in result["agents"]}
    assert "koroush.model-router" in ids
    assert "koroush.github-auditor" not in ids
    assert "koroush.github-repair" not in ids


def test_tenant_agent_catalog_rejects_unassigned_repository(monkeypatch):
    monkeypatch.setattr(routes, "authenticate_tenant_key", lambda key: {
        "team_id": "engineering", "repositories": ["org/other"], "scopes": ["inference:chat"]
    })
    with pytest.raises(HTTPException) as denied:
        asyncio.run(routes.agents_catalog(
            repository="org/repo", x_tenant_key="kor_test", x_admin_key=None
        ))
    assert denied.value.status_code == 403


def test_admin_catalog_requires_configured_exact_key(monkeypatch):
    monkeypatch.setattr(settings, "admin_api_key", "admin-secret")
    assert routes._admin_ok("admin-secret") is True
    assert routes._admin_ok("wrong") is False
    monkeypatch.setattr(settings, "admin_api_key", "")
    assert routes._admin_ok("admin-secret") is False
