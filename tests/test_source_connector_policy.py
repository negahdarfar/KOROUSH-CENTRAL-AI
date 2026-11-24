import pytest

from app.source_connector_catalog import list_connectors
from app.source_connector_policy import (
    FetchPolicy,
    SourcePolicyError,
    validate_fetch_request,
    validate_source_url,
)


def test_exact_allowlist_accepts_https_host_and_normalizes_case():
    assert validate_source_url(
        "https://EXAMPLE.org/feed.xml",
        allowed_hosts={"example.org"},
    ) == "example.org"


@pytest.mark.parametrize("url", [
    "http://example.org/feed",
    "https://user:pass@example.org/feed",
    "https://example.org:8443/feed",
    "https://127.0.0.1/admin",
    "https://localhost/admin",
    "https://sub.example.org/feed",
    "https://example.org/feed#fragment",
    "file:///etc/passwd",
])
def test_source_url_rejects_unsafe_targets(url):
    with pytest.raises(SourcePolicyError):
        validate_source_url(url, allowed_hosts={"example.org"})


def test_fetch_contract_has_strict_timeout_size_and_no_redirects():
    contract = validate_fetch_request(
        url="https://example.org/feed",
        allowed_hosts={"example.org"},
        policy=FetchPolicy(connect_timeout_seconds=5, read_timeout_seconds=8, max_response_bytes=100_000),
    )
    assert contract["allow_redirects"] is False
    assert contract["dns_rebinding_protection_required"] is True
    assert contract["max_response_bytes"] == 100_000


@pytest.mark.parametrize("policy", [
    FetchPolicy(connect_timeout_seconds=11),
    FetchPolicy(read_timeout_seconds=16),
    FetchPolicy(max_response_bytes=1_000_001),
    FetchPolicy(allow_redirects=True),
    FetchPolicy(require_https=False),
])
def test_fetch_policy_rejects_unsafe_limits(policy):
    with pytest.raises(SourcePolicyError):
        policy.validate()


def test_connector_catalog_is_contract_only_and_domain_filtered():
    all_items = list_connectors()
    forex = list_connectors(domain="forex")
    assert len(all_items) >= 5
    assert forex
    assert all(item["outbound_fetch_enabled"] is False for item in all_items)
    assert all("forex" in item["domains"] for item in forex)
    assert all(item["status"] == "contract-only" for item in all_items)


def test_connector_catalog_rejects_unknown_domain():
    with pytest.raises(ValueError):
        list_connectors(domain="unknown")
