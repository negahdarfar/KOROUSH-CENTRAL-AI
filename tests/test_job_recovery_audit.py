import asyncio
import sqlite3

import pytest
from fastapi import HTTPException

from app.config import settings
from app.durable_jobs import JobQueueError, list_job_admin_events
from app.job_admin_routes import admin_job_recovery_audit


def test_recovery_audit_is_bounded_and_repository_scoped(tmp_path, monkeypatch):
    db = tmp_path / "audit.sqlite3"
    monkeypatch.setenv("USAGE_DB_PATH", str(db))
    # Initialize the queue schema and insert synthetic metadata-only audit events.
    from app.durable_jobs import _connect
    conn = _connect()
    try:
        conn.execute(
            "INSERT INTO job_admin_events VALUES(?,?,?,?,?,?)",
            ("00000000-0000-0000-0000-000000000001", "10000000-0000-0000-0000-000000000001",
             "org/repo", "dead_letter_requeued", "2026-11-24T10:00:00+00:00", 1),
        )
        conn.execute(
            "INSERT INTO job_admin_events VALUES(?,?,?,?,?,?)",
            ("00000000-0000-0000-0000-000000000002", "10000000-0000-0000-0000-000000000002",
             "org/repo", "dead_letter_requeued", "2026-11-24T10:00:00+00:00", 2),
        )
        conn.execute(
            "INSERT INTO job_admin_events VALUES(?,?,?,?,?,?)",
            ("00000000-0000-0000-0000-000000000003", "20000000-0000-0000-0000-000000000003",
             "other/repo", "dead_letter_requeued", "2026-11-24T10:00:00+00:00", 1),
        )
    finally:
        conn.close()

    first = list_job_admin_events(repository="org/repo", limit=1)
    assert len(first) == 1
    second = list_job_admin_events(
        repository="org/repo", limit=1,
        before_event_at=first[0]["event_at"], before_event_id=first[0]["event_id"],
    )
    assert len(second) == 1
    assert first[0]["event_id"] != second[0]["event_id"]
    assert all(row["repository"] == "org/repo" for row in first + second)
    assert "payload" not in first[0]


def test_recovery_audit_rejects_invalid_limits_and_cursor(tmp_path, monkeypatch):
    monkeypatch.setenv("USAGE_DB_PATH", str(tmp_path / "audit.sqlite3"))
    with pytest.raises(JobQueueError):
        list_job_admin_events(limit=101)
    with pytest.raises(JobQueueError):
        list_job_admin_events(before_event_id="00000000-0000-0000-0000-000000000001")


def test_admin_recovery_audit_requires_admin_key(monkeypatch):
    monkeypatch.setattr(settings, "admin_api_key", "admin-test-key")
    with pytest.raises(HTTPException) as denied:
        asyncio.run(admin_job_recovery_audit(x_admin_key="wrong"))
    assert denied.value.status_code == 401
