from datetime import datetime, timezone
import pytest
from app.discovery_engine import (
    DiscoveryQuery, IntelligentDiscoveryEngine, ResourceCandidate,
    assess_candidate, github_query,
)

NOW = datetime(2026, 11, 24, tzinfo=timezone.utc)

def candidate(**overrides):
    data = dict(source_id="owner/project", name="Project", url="https://github.com/owner/project",
                kind="repository", description="AI agent framework", stars=150, forks=20,
                pushed_at="2026-11-01T00:00:00Z", license_spdx="MIT",
                evidence=({"type":"official_free_tier","url":"https://vendor.example/pricing"},))
    data.update(overrides)
    return ResourceCandidate(**data)

def test_query_is_bounded_and_rejects_unknown_kind():
    assert '"multi agent" archived:false' in github_query(DiscoveryQuery("repository", ("multi agent",)))
    with pytest.raises(ValueError): DiscoveryQuery("unknown", ("agent",))
    with pytest.raises(ValueError): DiscoveryQuery("repository", ("x",), limit=1000)
    with pytest.raises(ValueError): DiscoveryQuery("repository", ('agent" archived:true',))
    with pytest.raises(ValueError): DiscoveryQuery("repository", ("agent\\\\repo",))
    with pytest.raises(ValueError): DiscoveryQuery("repository", ("agent\nrepo",))

def test_official_evidence_needed_for_free_label():
    result = assess_candidate(candidate(evidence=()), now=NOW)
    assert result.free_status == "unverified"
    assert "official_free_tier" in result.missing_evidence

def test_repository_metadata_never_proves_free_by_itself():
    result = assess_candidate(candidate(evidence=()), now=NOW)
    assert result.status == "candidate_for_review"
    assert result.free_status == "unverified"

def test_archived_and_non_https_sources_rejected():
    assert assess_candidate(candidate(archived=True), now=NOW).status == "rejected"
    assert assess_candidate(candidate(url="http://github.com/x/y"), now=NOW).status == "rejected"
    assert assess_candidate(candidate(url="https://user:pass@github.com/x/y"), now=NOW).status == "rejected"
    assert assess_candidate(candidate(url="https://127.0.0.1/private"), now=NOW).status == "rejected"
    assert assess_candidate(candidate(url="https://-invalid.example/project"), now=NOW).status == "rejected"
    assert assess_candidate(candidate(url="https://github.com/x/y#fragment"), now=NOW).status == "rejected"

def test_stale_project_loses_freshness_credit():
    result = assess_candidate(candidate(pushed_at="2020-01-01T00:00:00Z"), now=NOW)
    assert "activity date missing, invalid, or stale" in result.reasons

def test_engine_ranks_candidates_and_caps_results():
    class Backend:
        def search(self, query):
            return [candidate(source_id="a", stars=0), candidate(source_id="b", archived=True)]
    results = IntelligentDiscoveryEngine(Backend()).discover(DiscoveryQuery("repository", ("agents",)), NOW)
    assert [r.source_id for r in results] == ["a", "b"]
    assert results[1].status == "rejected"
