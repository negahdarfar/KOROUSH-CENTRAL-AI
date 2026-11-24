import asyncio

from app.durable_jobs import enqueue_tenant_job
from app.job_worker import run_once
from app.job_payload_store import put_payload
from cryptography.fernet import Fernet


def _identity():
    return {
        "key_id": "12345678-1234-1234-1234-123456789abc",
        "team_id": "team-a",
        "user_id": "user-a",
        "repositories": ["org/repo"],
        "scopes": ["jobs:enqueue"],
    }


def test_tenant_job_is_bound_to_identity_and_worker_revalidates(tmp_path, monkeypatch):
    monkeypatch.setenv("USAGE_DB_PATH", str(tmp_path / "jobs.sqlite3"))
    monkeypatch.setenv("JOB_PAYLOAD_ENCRYPTION_KEY", Fernet.generate_key().decode())
    payload_ref = put_payload({"instruction": "safe test payload"})
    job = enqueue_tenant_job("org/repo", "audit.run", payload_ref, "tenant-req-1",
                             tenant_identity=_identity())
    assert job["team_id"] == "team-a"
    called = []

    async def handler(claimed):
        called.append((claimed["id"], claimed["payload"]))

    result = asyncio.run(run_once("worker-a", {"audit.run": handler},
                                  policy_check=lambda key, repo, team: (
                                      key == _identity()["key_id"] and repo == "org/repo" and team == "team-a"
                                  )))
    assert result == "succeeded"
    assert called == [(job["id"], {"instruction": "safe test payload"})]


def test_worker_rejects_revoked_or_unassigned_tenant_before_handler(tmp_path, monkeypatch):
    monkeypatch.setenv("USAGE_DB_PATH", str(tmp_path / "jobs.sqlite3"))
    monkeypatch.setenv("JOB_PAYLOAD_ENCRYPTION_KEY", Fernet.generate_key().decode())
    payload_ref = put_payload({"instruction": "must not run"})
    job = enqueue_tenant_job("org/repo", "audit.run", payload_ref, "tenant-req-2",
                             tenant_identity=_identity())
    called = []

    async def handler(claimed):
        called.append(claimed["id"])

    result = asyncio.run(run_once("worker-a", {"audit.run": handler},
                                  policy_check=lambda *_: False))
    assert result == "rejected"
    assert called == []
