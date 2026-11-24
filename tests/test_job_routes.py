import asyncio
import sqlite3

from cryptography.fernet import Fernet

from app.job_routes import JobSubmitRequest, get_job_status, submit_job
from app.job_payload_store import _connect as payload_connect
from app.quota_guard import _db_path
from app.tenant_auth import create_tenant_key


def _key(monkeypatch, tmp_path, user="user-a"):
    monkeypatch.setenv("USAGE_DB_PATH", str(tmp_path / "tenant-job-api.sqlite3"))
    monkeypatch.setenv("TENANT_AUTH_PEPPER", "test-pepper-value-with-at-least-32-chars")
    monkeypatch.setenv("JOB_PAYLOAD_ENCRYPTION_KEY", Fernet.generate_key().decode())
    monkeypatch.setenv("JOB_WORKER_ENABLED", "true")
    return create_tenant_key(
        user_id=user, team_id="team-a", repositories=["org/repo"], scopes=["jobs:enqueue", "jobs:read"]
    )["api_key"]


def test_submit_encrypts_and_returns_tenant_scoped_job_status(monkeypatch, tmp_path):
    key = _key(monkeypatch, tmp_path)
    request = JobSubmitRequest(
        repository="org/repo", job_type="chat.completion", idempotency_key="request-001",
        payload={"task": "inspect repository", "private": "payload text"},
    )
    submitted = asyncio.run(submit_job(request, x_tenant_key=key))
    assert submitted["status"] == "queued"
    assert submitted["idempotent_replay"] is False

    status = asyncio.run(get_job_status(submitted["job_id"], "org/repo", x_tenant_key=key))
    assert status["id"] == submitted["job_id"]
    assert status["status"] == "queued"
    assert "payload_ref" not in status
    assert "tenant_key_id" not in status

    conn = sqlite3.connect(_db_path())
    try:
        ciphertext = conn.execute("SELECT ciphertext FROM encrypted_job_payloads").fetchone()[0]
        assert b"payload text" not in ciphertext
    finally:
        conn.close()


def test_idempotent_retry_returns_original_job_and_does_not_leak_payload(monkeypatch, tmp_path):
    key = _key(monkeypatch, tmp_path)
    def submit(payload):
        return asyncio.run(submit_job(JobSubmitRequest(
            repository="org/repo", job_type="chat.completion", idempotency_key="same-request",
            payload=payload,
        ), x_tenant_key=key))
    first = submit({"task": "first"})
    second = submit({"task": "first"})
    assert second["job_id"] == first["job_id"]
    assert second["idempotent_replay"] is True
    conn = sqlite3.connect(_db_path())
    try:
        assert conn.execute("SELECT COUNT(*) FROM encrypted_job_payloads").fetchone()[0] == 1
    finally:
        conn.close()


def test_changed_payload_with_same_idempotency_key_is_rejected(monkeypatch, tmp_path):
    key = _key(monkeypatch, tmp_path)
    from fastapi import HTTPException
    asyncio.run(submit_job(JobSubmitRequest(repository="org/repo", job_type="chat.completion", idempotency_key="same-key", payload={"task": "first"}), x_tenant_key=key))
    try:
        asyncio.run(submit_job(JobSubmitRequest(repository="org/repo", job_type="chat.completion", idempotency_key="same-key", payload={"task": "changed"}), x_tenant_key=key))
        assert False, "expected idempotency conflict"
    except HTTPException as exc:
        assert exc.status_code == 409


def test_job_status_is_hidden_from_another_tenant_key(monkeypatch, tmp_path):
    key = _key(monkeypatch, tmp_path, user="user-a")
    other = create_tenant_key(
        user_id="user-b", team_id="team-a", repositories=["org/repo"], scopes=["jobs:enqueue", "jobs:read"]
    )["api_key"]
    submitted = asyncio.run(submit_job(JobSubmitRequest(
        repository="org/repo", job_type="chat.completion", idempotency_key="owner-only",
        payload={"task": "private"},
    ), x_tenant_key=key))
    from fastapi import HTTPException
    try:
        asyncio.run(get_job_status(submitted["job_id"], "org/repo", x_tenant_key=other))
        assert False, "expected tenant isolation"
    except HTTPException as exc:
        assert exc.status_code == 404



def test_job_status_requires_explicit_jobs_read_scope(monkeypatch, tmp_path):
    owner_key = _key(monkeypatch, tmp_path, user="owner")
    readless_key = create_tenant_key(
        user_id="reader", team_id="team-a", repositories=["org/repo"], scopes=["jobs:enqueue"]
    )["api_key"]
    submitted = asyncio.run(submit_job(JobSubmitRequest(
        repository="org/repo", job_type="chat.completion", idempotency_key="read-scope",
        payload={"task": "private"},
    ), x_tenant_key=owner_key))
    from fastapi import HTTPException
    try:
        asyncio.run(get_job_status(submitted["job_id"], "org/repo", x_tenant_key=readless_key))
        assert False, "expected missing jobs:read scope"
    except HTTPException as exc:
        assert exc.status_code == 404


def test_job_submission_requires_jobs_scope(monkeypatch, tmp_path):
    monkeypatch.setenv("USAGE_DB_PATH", str(tmp_path / "tenant-job-api.sqlite3"))
    monkeypatch.setenv("TENANT_AUTH_PEPPER", "test-pepper-value-with-at-least-32-chars")
    monkeypatch.setenv("JOB_PAYLOAD_ENCRYPTION_KEY", Fernet.generate_key().decode())
    key = create_tenant_key(
        user_id="user-a", team_id="team-a", repositories=["org/repo"], scopes=["inference:chat"]
    )["api_key"]
    from fastapi import HTTPException
    try:
        asyncio.run(submit_job(JobSubmitRequest(
            repository="org/repo", job_type="chat.completion", idempotency_key="no-scope",
            payload={"task": "must be rejected"},
        ), x_tenant_key=key))
        assert False, "expected scope rejection"
    except HTTPException as exc:
        assert exc.status_code == 403



def test_submission_is_blocked_when_worker_is_disabled(monkeypatch, tmp_path):
    key = _key(monkeypatch, tmp_path)
    monkeypatch.setenv("JOB_WORKER_ENABLED", "false")
    from fastapi import HTTPException
    try:
        asyncio.run(submit_job(JobSubmitRequest(
            repository="org/repo", job_type="chat.completion", idempotency_key="disabled",
            payload={"messages": [{"role": "user", "content": "hello"}]},
        ), x_tenant_key=key))
        assert False, "expected worker-disabled response"
    except HTTPException as exc:
        assert exc.status_code == 503
