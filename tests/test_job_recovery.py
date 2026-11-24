import asyncio
import sqlite3

import pytest
from fastapi import HTTPException

from app.config import settings
from app.job_admin_routes import admin_requeue_dead_letter
from app.durable_jobs import (
    enqueue_job, claim_job, fail_job, job_status, requeue_dead_letter_job,
)
from app.job_payload_store import put_payload


def configure_db(tmp_path, monkeypatch):
    monkeypatch.setenv("USAGE_DB_PATH", str(tmp_path / "jobs-recovery.sqlite3"))
    from cryptography.fernet import Fernet
    monkeypatch.setenv("JOB_PAYLOAD_ENCRYPTION_KEY", Fernet.generate_key().decode())


def make_dead_letter(tmp_path, monkeypatch):
    configure_db(tmp_path, monkeypatch)
    payload_ref = put_payload({"safe": "test"})
    job = enqueue_job("org/repo", "audit.run", payload_ref, "recovery-test", max_attempts=1)
    claim_job("worker-test")
    assert fail_job(job["id"], "worker-test", "provider_failed", retryable=True)
    return job["id"], job_status(job["id"], "org/repo")


def test_requeue_dead_letter_requires_matching_version_and_live_payload(tmp_path, monkeypatch):
    job_id, dead = make_dead_letter(tmp_path, monkeypatch)
    assert dead["status"] == "dead_letter"
    assert requeue_dead_letter_job(job_id, "org/repo", "2000-01-01T00:00:00+00:00") is None
    result = requeue_dead_letter_job(job_id, "org/repo", dead["updated_at"])
    assert result["status"] == "queued"
    assert result["attempts"] == 0
    assert result["manual_requeues"] == 1
    conn = sqlite3.connect(str(tmp_path / "jobs-recovery.sqlite3"))
    try:
        event = conn.execute("SELECT job_id,repository,action,manual_requeues FROM job_admin_events").fetchone()
        assert event == (job_id, "org/repo", "dead_letter_requeued", 1)
    finally:
        conn.close()


def test_dead_letter_requeue_is_bounded_to_three(tmp_path, monkeypatch):
    job_id, dead = make_dead_letter(tmp_path, monkeypatch)
    current = dead
    for expected_count in range(1, 4):
        result = requeue_dead_letter_job(job_id, "org/repo", current["updated_at"])
        assert result["manual_requeues"] == expected_count
        claim_job(f"worker-{expected_count}")
        assert fail_job(job_id, f"worker-{expected_count}", "again", retryable=True)
        current = job_status(job_id, "org/repo")
    assert requeue_dead_letter_job(job_id, "org/repo", current["updated_at"]) is None


def test_admin_requeue_requires_confirmation_and_admin_key(tmp_path, monkeypatch):
    job_id, dead = make_dead_letter(tmp_path, monkeypatch)
    monkeypatch.setattr(settings, "admin_api_key", "admin-test-key")
    with pytest.raises(HTTPException) as denied:
        asyncio.run(admin_requeue_dead_letter(
            job_id,
            type("Request", (), {"confirm": True, "repository": "org/repo", "expected_updated_at": dead["updated_at"]})(),
            x_admin_key="wrong",
        ))
    assert denied.value.status_code == 401


def test_admin_requeue_requires_explicit_confirmation(tmp_path, monkeypatch):
    job_id, dead = make_dead_letter(tmp_path, monkeypatch)
    monkeypatch.setattr(settings, "admin_api_key", "admin-test-key")
    from app.job_admin_routes import DeadLetterRequeueRequest
    request = DeadLetterRequeueRequest(
        confirm=False, repository="org/repo", expected_updated_at=dead["updated_at"]
    )
    with pytest.raises(HTTPException) as denied:
        asyncio.run(admin_requeue_dead_letter(job_id, request, x_admin_key="admin-test-key"))
    assert denied.value.status_code == 400
