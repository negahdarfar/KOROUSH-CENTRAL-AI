from app.agent_registry import platform_manifest
from app.integration_profiles import get_integration_profile, list_integration_profiles


def test_four_downstream_profiles_are_published_as_non_executable_contracts():
    profiles = list_integration_profiles()
    assert {item["id"] for item in profiles} == {
        "koroush.forex",
        "koroush.youtube",
        "koroush.ptc",
        "koroush.nft",
    }
    for profile in profiles:
        assert profile["status"] == "contract-only"
        assert profile["contract_version"] == 1
        assert profile["execution"] == "not-enabled"
        assert "jobs:enqueue" in profile["required_scopes"]
        assert profile["blocked_operations"]


def test_profiles_do_not_claim_domain_agents_are_implemented():
    profiles = {item["id"]: item for item in list_integration_profiles()}
    assert "live-order-execution" in profiles["koroush.forex"]["blocked_operations"]
    assert "public-video-publishing" in profiles["koroush.youtube"]["blocked_operations"]
    assert "automated-clicking" in profiles["koroush.ptc"]["blocked_operations"]
    assert "wallet-signing" in profiles["koroush.nft"]["blocked_operations"]
    assert all(
        "koroush.research-brief" in profile["shared_agents"]
        for profile in profiles.values()
    )


def test_profiles_are_in_public_manifest_without_secrets_or_mutable_registry_access():
    manifest = platform_manifest()
    integrations = {item["id"]: item for item in manifest["integrations"]}
    assert len(integrations) == 4
    assert integrations["koroush.youtube"]["execution"] == "not-enabled"
    assert "api_key" not in str(manifest).lower()
    profile = get_integration_profile("koroush.forex")
    profile["blocked_operations"].clear()
    assert get_integration_profile("koroush.forex")["blocked_operations"]
