import asyncio

import pytest
from fastapi import HTTPException

from app.config import settings
from app.job_admin_routes import admin_job_summary
from app.durable_jobs import job_queue_summary


def test_queue_summary_returns_zeroed_aggregate_without_identifiers(tmp_path, monkeypatch):
    monkeypatch.setenv("USAGE_DB_PATH", str(tmp_path / "queue-summary.sqlite3"))
    result = job_queue_summary()
    assert result["total"] == 0
    assert result["counts"] == {
        "queued": 0, "running": 0, "succeeded": 0, "failed": 0, "dead_letter": 0
    }
    assert "job_id" not in str(result) and "tenant_id" not in str(result)


def test_admin_job_summary_requires_admin_key(monkeypatch, tmp_path):
    monkeypatch.setenv("USAGE_DB_PATH", str(tmp_path / "queue-admin.sqlite3"))
    monkeypatch.setattr(settings, "admin_api_key", "test-admin-secret")
    with pytest.raises(HTTPException) as exc:
        asyncio.run(admin_job_summary(repository=None, x_admin_key="wrong"))
    assert exc.value.status_code == 401


def test_admin_job_summary_returns_aggregate_queue_and_worker(monkeypatch, tmp_path):
    monkeypatch.setenv("USAGE_DB_PATH", str(tmp_path / "queue-admin.sqlite3"))
    monkeypatch.setenv("JOB_WORKER_ENABLED", "false")
    monkeypatch.setattr(settings, "admin_api_key", "test-admin-secret")
    result = asyncio.run(admin_job_summary(repository=None, x_admin_key="test-admin-secret"))
    assert result["queue"]["total"] == 0
    assert result["worker"]["status"] == "disabled"
    assert "filesystem paths" in " ".join(result["notes"])


def test_admin_job_summary_rejects_malformed_repository(monkeypatch):
    monkeypatch.setattr(settings, "admin_api_key", "test-admin-secret")
    with pytest.raises(HTTPException) as exc:
        asyncio.run(admin_job_summary(repository="../private/path", x_admin_key="test-admin-secret"))
    assert exc.value.status_code == 422
