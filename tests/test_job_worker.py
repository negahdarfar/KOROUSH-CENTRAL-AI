import asyncio

from app.durable_jobs import enqueue_tenant_job
from app.job_worker import run_once


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
    job = enqueue_tenant_job("org/repo", "audit.run", "vault:payload-1", "tenant-req-1",
                             tenant_identity=_identity())
    assert job["team_id"] == "team-a"
    called = []

    async def handler(claimed):
        called.append(claimed["id"])

    result = asyncio.run(run_once("worker-a", {"audit.run": handler},
                                  policy_check=lambda key, repo, team: (
                                      key == _identity()["key_id"] and repo == "org/repo" and team == "team-a"
                                  )))
    assert result == "succeeded"
    assert called == [job["id"]]


def test_worker_rejects_revoked_or_unassigned_tenant_before_handler(tmp_path, monkeypatch):
    monkeypatch.setenv("USAGE_DB_PATH", str(tmp_path / "jobs.sqlite3"))
    job = enqueue_tenant_job("org/repo", "audit.run", "vault:payload-2", "tenant-req-2",
                             tenant_identity=_identity())
    called = []

    async def handler(claimed):
        called.append(claimed["id"])

    result = asyncio.run(run_once("worker-a", {"audit.run": handler},
                                  policy_check=lambda *_: False))
    assert result == "rejected"
    assert called == []
