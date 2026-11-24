import asyncio

from app.durable_jobs import enqueue_tenant_job
from app.job_worker import run_once
from app.job_payload_store import put_payload, get_payload, JobPayloadError
from cryptography.fernet import Fernet


def _identity():
    return {
        "key_id": "12345678-1234-1234-1234-123456789abc",
        "team_id": "team-a",
        "user_id": "user-a",
        "repositories": ["org/repo"],
        "scopes": ["jobs:enqueue", "jobs:read"],
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
    try:
        get_payload(payload_ref)
        assert False, "successful job should release its encrypted input payload"
    except JobPayloadError:
        pass


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



def test_worker_persists_handler_result_as_encrypted_payload(tmp_path, monkeypatch):
    monkeypatch.setenv("USAGE_DB_PATH", str(tmp_path / "job-results.sqlite3"))
    monkeypatch.setenv("JOB_PAYLOAD_ENCRYPTION_KEY", Fernet.generate_key().decode())
    payload_ref = put_payload({"messages": [{"role": "user", "content": "hello"}]})
    job = enqueue_tenant_job("org/repo", "audit.run", payload_ref, "result-request",
                             tenant_identity=_identity())

    async def handler(claimed):
        return {"answer": "completed", "job": claimed["id"]}

    result = asyncio.run(run_once("worker-results", {"audit.run": handler},
                                  policy_check=lambda *_: True))
    assert result == "succeeded"
    from app.durable_jobs import tenant_job_status
    status = tenant_job_status(job["id"], repository="org/repo", tenant_identity=_identity())
    assert status["status"] == "succeeded"
    assert get_payload(status["result_ref"]) == {
        "result": {"answer": "completed", "job": job["id"]}
    }
