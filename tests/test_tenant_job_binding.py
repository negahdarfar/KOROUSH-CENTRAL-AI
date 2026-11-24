import pytest

from app.durable_jobs import JobQueueError, enqueue_tenant_job


def identity(key_id="12345678-1234-1234-1234-123456789abc", user="user-a"):
    return {
        "key_id": key_id,
        "team_id": "team-a",
        "user_id": user,
        "repositories": ["org/repo"],
        "scopes": ["jobs:enqueue"],
    }


def test_tenant_enqueue_atomically_binds_identity(tmp_path, monkeypatch):
    monkeypatch.setenv("USAGE_DB_PATH", str(tmp_path / "tenant-jobs.sqlite3"))
    result = enqueue_tenant_job("org/repo", "audit.run", "vault:payload-1", "tenant-key-1",
                                tenant_identity=identity())
    assert result["team_id"] == "team-a"
    assert result["user_id"] == "user-a"
    assert "payload_ref" not in result
    assert "idempotency_key" not in result


def test_idempotency_reuse_with_another_tenant_is_rejected(tmp_path, monkeypatch):
    monkeypatch.setenv("USAGE_DB_PATH", str(tmp_path / "tenant-jobs.sqlite3"))
    enqueue_tenant_job("org/repo", "audit.run", "vault:payload-1", "same-key",
                       tenant_identity=identity())
    with pytest.raises(JobQueueError, match="another tenant identity"):
        enqueue_tenant_job("org/repo", "audit.run", "vault:payload-1", "same-key",
                           tenant_identity=identity(key_id="aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa"))


def test_tenant_enqueue_requires_scope_and_repository(tmp_path, monkeypatch):
    monkeypatch.setenv("USAGE_DB_PATH", str(tmp_path / "tenant-jobs.sqlite3"))
    with pytest.raises(JobQueueError, match="not assigned"):
        enqueue_tenant_job("org/other", "audit.run", "vault:payload-1", "req-a",
                           tenant_identity=identity())
    no_scope = identity()
    no_scope["scopes"] = ["inference:chat"]
    with pytest.raises(JobQueueError, match="does not have jobs:enqueue"):
        enqueue_tenant_job("org/repo", "audit.run", "vault:payload-1", "req-b",
                           tenant_identity=no_scope)
