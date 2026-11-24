from datetime import datetime, timezone
import asyncio
import httpx
import pytest

from app.discovery_engine import (
    DiscoveryQuery, IntelligentDiscoveryEngine, ResourceCandidate,
    assess_candidate, github_query, search_github_repositories,
)

NOW = datetime(2026, 11, 24, tzinfo=timezone.utc)


def candidate(**overrides):
    data = dict(
        source_id="owner/project", name="Project", url="https://github.com/owner/project",
        kind="repository", description="AI agent framework", stars=150, forks=20,
        pushed_at="2026-11-01T00:00:00Z", license_spdx="MIT",
        evidence=({"type": "official_free_tier", "url": "https://vendor.example/pricing"},),
    )
    data.update(overrides)
    return ResourceCandidate(**data)


def test_query_is_bounded_and_rejects_query_injection():
    assert '"multi agent" archived:false pushed:>=' in github_query(
        DiscoveryQuery("repository", ("multi agent",)), NOW
    )
    with pytest.raises(ValueError):
        DiscoveryQuery("unknown", ("agent",))
    with pytest.raises(ValueError):
        DiscoveryQuery("repository", ("agent",), limit=1000)
    with pytest.raises(ValueError):
        DiscoveryQuery("repository", ('agent" archived:true',))
    with pytest.raises(ValueError):
        DiscoveryQuery("repository", ("agent\\repo",))
    with pytest.raises(ValueError):
        DiscoveryQuery("repository", ("agent\nrepo",))


def test_metadata_and_submitted_urls_never_prove_free_pricing():
    result = assess_candidate(candidate(), now=NOW)
    assert result.status == "candidate_for_review"
    assert result.free_status == "unverified"
    assert "official_publisher_domain_verification" in result.missing_evidence


def test_archived_and_unsafe_urls_are_rejected():
    assert assess_candidate(candidate(archived=True), now=NOW).status == "rejected"
    assert assess_candidate(candidate(url="http://github.com/x/y"), now=NOW).status == "rejected"
    assert assess_candidate(candidate(url="https://user:pass@github.com/x/y"), now=NOW).status == "rejected"
    assert assess_candidate(candidate(url="https://127.0.0.1/private"), now=NOW).status == "rejected"
    assert assess_candidate(candidate(url="https://-invalid.example/project"), now=NOW).status == "rejected"
    assert assess_candidate(candidate(url="https://github.com/x/y#fragment"), now=NOW).status == "rejected"


def test_invalid_metadata_is_rejected_without_type_errors():
    assert assess_candidate(candidate(stars=True), now=NOW).status == "rejected"
    assert assess_candidate(candidate(stars=-1), now=NOW).status == "rejected"
    assert assess_candidate(candidate(name="x" * 501), now=NOW).status == "rejected"


def test_stale_project_loses_freshness_credit():
    result = assess_candidate(candidate(pushed_at="2020-01-01T00:00:00Z"), now=NOW)
    assert "activity date missing, invalid, or stale" in result.reasons


def test_engine_bounds_generator_consumption():
    class Backend:
        def __init__(self):
            self.consumed = 0
        def search(self, query):
            for i in range(1000):
                self.consumed += 1
                yield candidate(source_id=f"owner/project-{i}")
    backend = Backend()
    results = IntelligentDiscoveryEngine(backend).discover(
        DiscoveryQuery("repository", ("agents",), limit=3), NOW
    )
    assert len(results) == 3
    assert backend.consumed == 3


def test_github_search_uses_fixed_host_and_bounded_response():
    class FakeClient:
        def __init__(self):
            self.request = None
        async def get(self, url, **kwargs):
            self.request = (url, kwargs)
            return httpx.Response(200, request=httpx.Request("GET", url), json={"items": [{
                "full_name": "owner/repo", "name": "repo",
                "html_url": "https://github.com/owner/repo",
                "description": "AI tool", "stargazers_count": 10,
                "forks_count": 2, "archived": False,
                "pushed_at": "2026-11-01T00:00:00Z",
                "license": {"spdx_id": "MIT"},
            }]})
    fake = FakeClient()
    results = asyncio.run(search_github_repositories(
        DiscoveryQuery("repository", ("agent",), limit=5), client=fake
    ))
    assert len(results) == 1
    assert results[0].source_id == "owner/repo"
    url, kwargs = fake.request
    assert url == "https://api.github.com/search/repositories"
    assert kwargs["params"]["per_page"] == "5"
    assert kwargs["headers"]["Accept"] == "application/vnd.github+json"
    assert "Authorization" not in kwargs["headers"]
