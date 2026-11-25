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
