import time

import pytest

from app.durable_jobs import (
    JobQueueError, claim_job, enqueue_job, fail_job, finish_job, job_status,
)


def configure_db(tmp_path, monkeypatch):
    monkeypatch.setenv("USAGE_DB_PATH", str(tmp_path / "jobs.sqlite3"))


def test_enqueue_is_idempotent_and_does_not_return_payload_reference(tmp_path, monkeypatch):
    configure_db(tmp_path, monkeypatch)
    first = enqueue_job("Org/Repo", "audit.run", "vault:payload-123", "request-1")
    second = enqueue_job("org/repo", "audit.run", "vault:payload-456", "request-1")
    assert first["id"] == second["id"]
    assert first["status"] == "queued"
    assert "payload_ref" not in first
    assert "idempotency_key" not in first


def test_claim_lease_and_fenced_completion(tmp_path, monkeypatch):
    configure_db(tmp_path, monkeypatch)
    job = enqueue_job("org/repo", "audit.run", "vault:payload-1", "req-2")
    claimed = claim_job("worker-a", lease_seconds=10)
    assert claimed["id"] == job["id"]
    assert claimed["attempts"] == 1
    assert finish_job(job["id"], "worker-b") is False
    assert finish_job(job["id"], "worker-a") is True
    assert job_status(job["id"], "org/repo")["status"] == "succeeded"


def test_failed_job_retries_then_dead_letters(tmp_path, monkeypatch):
    configure_db(tmp_path, monkeypatch)
    job = enqueue_job("org/repo", "audit.run", "vault:payload-2", "req-3", max_attempts=1)
    claimed = claim_job("worker-a")
    assert fail_job(job["id"], "worker-a", "provider_timeout", retryable=True)
    assert job_status(job["id"], "org/repo")["status"] == "dead_letter"


def test_non_retryable_failure_dead_letters(tmp_path, monkeypatch):
    configure_db(tmp_path, monkeypatch)
    job = enqueue_job("org/repo", "audit.run", "vault:payload-3", "req-4")
    claim_job("worker-a")
    assert fail_job(job["id"], "worker-a", "invalid_payload", retryable=False)
    assert job_status(job["id"], "org/repo")["status"] == "dead_letter"


@pytest.mark.parametrize("value", ["", "../secret", "contains space", "x" * 600])
def test_payload_reference_validation_rejects_unsafe_values(tmp_path, monkeypatch, value):
    configure_db(tmp_path, monkeypatch)
    with pytest.raises(JobQueueError):
        enqueue_job("org/repo", "audit.run", value, "req-5")


def test_expired_lease_can_be_reclaimed(tmp_path, monkeypatch):
    configure_db(tmp_path, monkeypatch)
    job = enqueue_job("org/repo", "audit.run", "vault:payload-4", "req-6", max_attempts=2)
    first = claim_job("worker-a", lease_seconds=10)
    from app import durable_jobs
    from datetime import timedelta
    real_now = durable_jobs._now
    monkeypatch.setattr(durable_jobs, "_now", lambda: real_now() + timedelta(seconds=11))
    second = claim_job("worker-b", lease_seconds=10)
    assert second["id"] == first["id"]
    assert second["attempts"] == 2
    assert finish_job(job["id"], "worker-a") is False
