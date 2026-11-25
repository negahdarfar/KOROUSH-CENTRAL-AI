import pytest

from app.agent_workflows import AgentWorkflowInputError, validate_domain_workflow_input
from app.integration_profiles import get_integration_profile


@pytest.mark.parametrize("domain", ["forex", "youtube", "ptc", "nft"])
def test_all_downstream_domains_have_enabled_durable_workflow_profiles(domain):
    profile = get_integration_profile(f"koroush.{domain}")
    assert profile is not None
    assert profile["execution"] == "durable-job"
    assert profile["api"] == f"POST /api/integrations/{domain}/research"


def test_domain_workflow_input_requires_at_least_one_attributed_source():
    with pytest.raises(AgentWorkflowInputError):
        validate_domain_workflow_input({"domain": "ptc", "evidence": []})


def test_domain_research_route_authenticates_and_enqueues_shared_workflow(monkeypatch):
    import asyncio
    from app import integration_routes as routes

    captured = {}
    monkeypatch.setattr(routes, "authenticate_tenant_key", lambda key: {
        "key_id": "00000000-0000-0000-0000-000000000001",
        "team_id": "team-a",
        "user_id": "user-a",
        "repositories": ["org/forex"],
        "scopes": ["jobs:enqueue", "inference:chat", "jobs:read"],
    })
    monkeypatch.setattr(routes, "worker_ready", lambda: True)
    monkeypatch.setattr(routes, "put_payload", lambda payload: "payload-ref-1")
    monkeypatch.setattr(routes, "delete_payload", lambda ref: None)

    def enqueue(repository, job_type, payload_ref, idempotency_key, **kwargs):
        captured.update({
            "repository": repository, "job_type": job_type,
            "payload_ref": payload_ref, "payload_hash": kwargs["payload_hash"],
        })
        return {
            "id": "job-1", "repository": repository, "job_type": job_type,
            "status": "queued", "idempotent_replay": False, "created_at": "2026-11-25T00:00:00Z",
        }

    monkeypatch.setattr(routes, "enqueue_tenant_job", enqueue)
    request = routes.DomainResearchRequest(
        repository="org/forex",
        idempotency_key="fx-research-1",
        evidence=[{
            "source_id": "source-1",
            "publisher": "Central bank",
            "source_url": "https://example.com/report",
            "observed_at": "2026-11-25T00:00:00Z",
            "text": "A supplied macroeconomic report.",
        }],
    )
    result = asyncio.run(routes.submit_domain_research("forex", request, x_tenant_key="kor_test"))
    assert result["job_id"] == "job-1"
    assert captured["job_type"] == "agent.workflow"
    assert captured["repository"] == "org/forex"
    assert len(captured["payload_hash"]) == 64

 

def test_future_registered_connector_uses_generic_workflow_without_new_domain_code(monkeypatch):
    import asyncio
    from app import integration_routes as routes

    captured = {}
    monkeypatch.setattr(routes, "authenticate_tenant_key", lambda key: {
        "key_id": "00000000-0000-0000-0000-000000000002",
        "team_id": "team-future",
        "user_id": "user-future",
        "repositories": ["org/future-project"],
        "scopes": ["jobs:enqueue", "inference:chat", "jobs:read"],
    })
    monkeypatch.setattr(routes, "list_extensions", lambda **kwargs: [
        {
            "extension_id": "acme.future-project",
            "version": version,
            "kind": "connector",
            "status": "active",
            "domains": ["general"],
            "capabilities": ["research.workflow.v1"],
            "repositories": ["org/future-project"],
        }
        for version in ("1.0.0", "1.2.0")
    ])
    monkeypatch.setattr(routes, "worker_ready", lambda: True)
    monkeypatch.setattr(routes, "put_payload", lambda payload: captured.update({"payload": payload}) or "payload-future")
    monkeypatch.setattr(routes, "delete_payload", lambda ref: None)

    def enqueue(repository, job_type, payload_ref, idempotency_key, **kwargs):
        captured.update({"repository": repository, "job_type": job_type, "payload_ref": payload_ref})
        return {
            "id": "future-job", "repository": repository, "job_type": job_type,
            "status": "queued", "idempotent_replay": False, "created_at": "2026-11-25T00:00:00Z",
        }

    monkeypatch.setattr(routes, "enqueue_tenant_job", enqueue)
    request = routes.DomainResearchRequest(
        repository="org/future-project",
        idempotency_key="future-research-1",
        evidence=[{
            "source_id": "future-source-1",
            "publisher": "Future project",
            "source_url": "https://example.org/evidence",
            "observed_at": "2026-11-25T00:00:00Z",
            "text": "A future repository supplied a bounded evidence excerpt.",
        }],
    )
    result = asyncio.run(routes.submit_domain_research(
        "acme.future-project", request, x_tenant_key="kor_test"
    ))
    assert result["job_id"] == "future-job"
    assert result["integration_id"] == "acme.future-project"
    assert result["workflow_id"] == "acme.future-project@1.2.0.research.v1"
    assert captured["payload"]["domain"] == "general"
    assert captured["job_type"] == "agent.workflow"


def test_unregistered_future_connector_is_rejected(monkeypatch):
    import asyncio
    from fastapi import HTTPException
    from app import integration_routes as routes

    monkeypatch.setattr(routes, "authenticate_tenant_key", lambda key: {
        "repositories": ["org/unknown"], "scopes": ["jobs:enqueue", "inference:chat"],
    })
    monkeypatch.setattr(routes, "list_extensions", lambda **kwargs: [])
    request = routes.DomainResearchRequest(
        repository="org/unknown", idempotency_key="unknown-1",
        evidence=[{"source_id": "s1", "text": "bounded evidence"}],
    )
    try:
        asyncio.run(routes.submit_domain_research("unknown.future", request, x_tenant_key="kor_test"))
    except HTTPException as exc:
        assert exc.status_code == 404
    else:
        raise AssertionError("unregistered integration must be rejected")
