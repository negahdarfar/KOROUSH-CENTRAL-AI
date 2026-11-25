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
