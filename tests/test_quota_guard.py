import pytest

from app.quota_guard import (
    QuotaExceeded,
    cancel_reservation,
    complete_reservation,
    list_usage_alerts,
    reserve_inference,
)


def configure(tmp_path, monkeypatch, limits):
    monkeypatch.setenv("USAGE_DB_PATH", str(tmp_path / "quota.sqlite3"))
    monkeypatch.setenv("KOROUSH_REPO_QUOTAS", __import__("json").dumps({"org/repo": limits}))


def test_quota_reservation_blocks_before_request_and_cancel_releases_capacity(tmp_path, monkeypatch):
    configure(tmp_path, monkeypatch, {
        "requests_per_day": 1,
        "requests_per_month": 1,
        "tokens_per_day": 1000,
        "tokens_per_month": 1000,
    })
    first = reserve_inference("Org/Repo", {"messages": [{"content": "hello"}]})
    with pytest.raises(QuotaExceeded, match="requests_per_day"):
        reserve_inference("org/repo", {"messages": [{"content": "second"}]})
    cancel_reservation(first)
    second = reserve_inference("org/repo", {"messages": [{"content": "retry"}]})
    complete_reservation(second, 12)
    with pytest.raises(QuotaExceeded, match="requests_per_day"):
        reserve_inference("org/repo", {"messages": [{"content": "third"}]})


def test_token_quota_uses_preflight_estimate_and_alerts_are_deduplicated(tmp_path, monkeypatch):
    configure(tmp_path, monkeypatch, {
        "requests_per_day": 10,
        "requests_per_month": 100,
        "tokens_per_day": 100,
        "tokens_per_month": 1000,
    })
    reservation = reserve_inference("org/repo", {"input": "x" * 300})
    alerts = list_usage_alerts()
    assert any(item["metric"] == "tokens_day" and item["threshold"] == 70 for item in alerts)
    complete_reservation(reservation, 80)
    with pytest.raises(QuotaExceeded, match="tokens_per_day"):
        reserve_inference("org/repo", {"input": "y" * 100})


def test_unassigned_repository_and_invalid_config_fail_closed(tmp_path, monkeypatch):
    monkeypatch.setenv("USAGE_DB_PATH", str(tmp_path / "quota.sqlite3"))
    with pytest.raises(QuotaExceeded, match="explicit repository"):
        reserve_inference(None, {"input": "hello"})
    monkeypatch.setenv("KOROUSH_REPO_QUOTAS", "not-json")
    with pytest.raises(QuotaExceeded, match="configuration is invalid"):
        reserve_inference("org/repo", {"input": "hello"})


def test_repo_specific_limits_override_wildcard(tmp_path, monkeypatch):
    monkeypatch.setenv("USAGE_DB_PATH", str(tmp_path / "quota.sqlite3"))
    monkeypatch.setenv(
        "KOROUSH_REPO_QUOTAS",
        '{"*":{"requests_per_day":1},"Org/Repo":{"requests_per_day":2}}',
    )
    first = reserve_inference("ORG/REPO", {"input": "one"})
    second = reserve_inference("org/repo", {"input": "two"})
    with pytest.raises(QuotaExceeded):
        reserve_inference("org/repo", {"input": "three"})
    cancel_reservation(first)
    cancel_reservation(second)



@pytest.mark.parametrize("repository", ["owner", "owner/", "/repo", "owner/../repo", "owner/repo with spaces", "owner//repo"])
def test_invalid_repository_identity_is_rejected_before_quota_reservation(tmp_path, monkeypatch, repository):
    monkeypatch.setenv("USAGE_DB_PATH", str(tmp_path / "invalid.sqlite3"))
    with pytest.raises(QuotaExceeded, match="valid owner/name"):
        reserve_inference(repository, {"input": "hello"})
