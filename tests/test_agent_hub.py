import asyncio

import pytest
from fastapi import HTTPException

from app import agent_hub_routes as routes
from app.agent_registry import get_agent, list_agents, list_apis, platform_manifest
from app.config import settings


def test_platform_manifest_is_non_secret_and_marks_incomplete_transports():
    manifest = platform_manifest()
    assert manifest["integration_model"] == "central-control-plane"
    assert manifest["contract"]["job_submission"] == "POST /api/jobs"
    assert any(api["id"] == "jobs.enqueue" for api in manifest["apis"])
    assert any(api["id"] == "apis.catalog" for api in manifest["apis"])
    assert not any(api["id"] == "github.repair.apply" for api in manifest["apis"])
    assert not any(api["auth"] == "admin" for api in manifest["apis"])
    providers = {item["id"]: item["status"] for item in manifest["providers"]}
    assert providers["avalai"] == "limited"
    assert providers["openrouter"] == "planned"
    assert providers["freellmapi"] == "planned"
    assert providers["gemini"] == "planned"
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



def test_tenant_api_catalog_hides_admin_routes_and_enforces_scopes(monkeypatch):
    monkeypatch.setattr(routes, "authenticate_tenant_key", lambda key: {
        "team_id": "engineering", "repositories": ["org/repo"], "scopes": ["inference:chat"]
    })
    result = asyncio.run(routes.api_catalog(repository="org/repo", x_tenant_key="kor_test", x_admin_key=None))
    ids = {item["id"] for item in result["apis"]}
    assert "provider.avalai.execute" in ids
    assert "jobs.enqueue" not in ids
    assert "github.repair.apply" not in ids
    assert "operations.jobs.recovery" not in ids


def test_admin_api_catalog_includes_admin_routes(monkeypatch):
    monkeypatch.setattr(settings, "admin_api_key", "admin-secret")
    result = asyncio.run(routes.api_catalog(repository=None, x_tenant_key=None, x_admin_key="admin-secret"))
    ids = {item["id"] for item in result["apis"]}
    assert "github.repair.apply" in ids
    assert "operations.jobs.recovery" in ids



def test_api_catalog_paths_match_registered_fastapi_routes():
    from app.main import app

    registered = set()
    for path, operations in app.openapi()["paths"].items():
        for method in operations:
            registered.add((method.upper(), path))
    missing = [
        (item["method"], item["path"])
        for item in list_apis()
        if (item["method"], item["path"]) not in registered
    ]
    assert not missing, f"API catalog contains unregistered routes: {missing}"



def test_runtime_version_matches_agent_manifest():
    from app.main import app
    from app.agent_registry import PLATFORM_VERSION

    assert app.version == PLATFORM_VERSION



def test_registry_advertises_only_fixed_executable_text_agents():
    from app.agent_registry import list_agents, platform_manifest

    agents = {item["id"]: item for item in list_agents()}
    for agent_id in (
        "koroush.text-summarizer",
        "koroush.text-translator",
        "koroush.text-classifier",
        "koroush.research-brief",
    ):
        assert agents[agent_id]["status"] == "limited"
        assert agents[agent_id]["execution"] == "durable-job"
        assert agents[agent_id]["job_type"] == "agent.execute"
        assert "inference:chat" in agents[agent_id]["required_scopes"]
    assert "agent.execute" in {
        item["id"] for item in platform_manifest()["capabilities"]
    }



def test_tenant_api_catalog_requires_both_job_and_inference_scopes(monkeypatch):
    monkeypatch.setattr(routes, "authenticate_tenant_key", lambda key: {
        "team_id": "engineering", "repositories": ["org/repo"], "scopes": ["jobs:enqueue"]
    })
    result = asyncio.run(routes.api_catalog(
        repository="org/repo", x_tenant_key="kor_test", x_admin_key=None
    ))
    assert "jobs.enqueue" not in {item["id"] for item in result["apis"]}


def test_platform_manifest_exposes_contract_only_source_connectors():
    from app.agent_registry import platform_manifest

    manifest = platform_manifest()
    connectors = manifest["source_connectors"]
    assert connectors
    assert all(item["status"] == "contract-only" for item in connectors)
    assert all(item["outbound_fetch_enabled"] is False for item in connectors)
    assert any(item["protocol"] == "youtube-data-api" for item in connectors)


def test_extension_discovery_api_requires_registry_read_scope(monkeypatch):
    monkeypatch.setattr(routes, "authenticate_tenant_key", lambda key: {
        "team_id": "engineering", "repositories": ["org/repo"], "scopes": ["inference:chat"]
    })
    result = asyncio.run(routes.api_catalog(
        repository="org/repo", x_tenant_key="kor_test", x_admin_key=None
    ))
    assert "extensions.discover" not in {item["id"] for item in result["apis"]}

    monkeypatch.setattr(routes, "authenticate_tenant_key", lambda key: {
        "team_id": "engineering", "repositories": ["org/repo"], "scopes": ["registry:read"]
    })
    result = asyncio.run(routes.api_catalog(
        repository="org/repo", x_tenant_key="kor_test", x_admin_key=None
    ))
    assert "extensions.discover" in {item["id"] for item in result["apis"]}
