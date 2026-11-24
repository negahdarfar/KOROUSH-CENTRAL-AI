"""Persistent metadata-only job queue with atomic leases and idempotent enqueue.

Payload bytes and credentials must live in a separately protected store. This
queue persists only an opaque payload reference, never prompts or API secrets.
"""
from __future__ import annotations

import json
import os
import re
import sqlite3
import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

from .quota_guard import _db_path


class JobQueueError(RuntimeError):
    pass


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _connect() -> sqlite3.Connection:
    path = _db_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(path), timeout=10, isolation_level=None)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA busy_timeout=10000")
    conn.execute("""
        CREATE TABLE IF NOT EXISTS durable_jobs (
            id TEXT PRIMARY KEY,
            repository TEXT NOT NULL,
            job_type TEXT NOT NULL,
            payload_ref TEXT NOT NULL,
            idempotency_key TEXT NOT NULL,
            status TEXT NOT NULL CHECK(status IN ('queued','running','succeeded','failed','dead_letter')),
            attempts INTEGER NOT NULL DEFAULT 0,
            max_attempts INTEGER NOT NULL,
            available_at TEXT NOT NULL,
            lease_owner TEXT,
            lease_until TEXT,
            last_error_code TEXT,
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL,
            UNIQUE(repository, idempotency_key)
        )
    """)
    conn.execute("CREATE INDEX IF NOT EXISTS ix_jobs_claim ON durable_jobs(status, available_at, lease_until)")
    columns = {row["name"] for row in conn.execute("PRAGMA table_info(durable_jobs)").fetchall()}
    for name, declaration in (("tenant_key_id", "TEXT"), ("team_id", "TEXT"), ("user_id", "TEXT")):
        if name not in columns:
            conn.execute(f"ALTER TABLE durable_jobs ADD COLUMN {name} {declaration}")
    conn.execute("CREATE INDEX IF NOT EXISTS ix_jobs_repo_created ON durable_jobs(repository, created_at)")
    conn.execute("CREATE INDEX IF NOT EXISTS ix_jobs_tenant_status ON durable_jobs(tenant_key_id, status, created_at)")
    return conn


def _validate_text(value: Any, name: str, limit: int, pattern: str) -> str:
    if not isinstance(value, str):
        raise JobQueueError(f"{name} must be text")
    value = value.strip()
    if not value or len(value) > limit or not re.fullmatch(pattern, value):
        raise JobQueueError(f"{name} has an invalid format")
    return value


def enqueue_job(repository: str, job_type: str, payload_ref: str, idempotency_key: str,
                *, max_attempts: int = 5) -> dict:
    repo = _validate_text(repository.lower(), "repository", 201,
                          r"[a-z0-9][a-z0-9._-]{0,99}/[a-z0-9][a-z0-9._-]{0,99}")
    kind = _validate_text(job_type, "job_type", 80, r"[a-z][a-z0-9_.-]{1,79}")
    ref = _validate_text(payload_ref, "payload_ref", 512, r"[A-Za-z0-9][A-Za-z0-9._:/-]{0,511}")
    key = _validate_text(idempotency_key, "idempotency_key", 128, r"[A-Za-z0-9][A-Za-z0-9._:-]{0,127}")
    if isinstance(max_attempts, bool) or not isinstance(max_attempts, int) or not 1 <= max_attempts <= 20:
        raise JobQueueError("max_attempts must be an integer from 1 to 20")
    now = _now().isoformat()
    job_id = str(uuid.uuid4())
    conn = _connect()
    try:
        conn.execute("BEGIN IMMEDIATE")
        conn.execute("""INSERT OR IGNORE INTO durable_jobs
            (id,repository,job_type,payload_ref,idempotency_key,status,max_attempts,available_at,created_at,updated_at)
            VALUES(?,?,?,?,?,'queued',?,?,?,?)""",
            (job_id, repo, kind, ref, key, max_attempts, now, now, now))
        row = conn.execute("SELECT * FROM durable_jobs WHERE repository=? AND idempotency_key=?",
                           (repo, key)).fetchone()
        if row["job_type"] != kind or row["payload_ref"] != ref:
            raise JobQueueError("idempotency key was already used with a different job type or payload reference")
        conn.execute("COMMIT")
        result = dict(row)
        result.pop("payload_ref", None)
        result.pop("idempotency_key", None)
        return result
    except Exception:
        if conn.in_transaction:
            conn.execute("ROLLBACK")
        raise
    finally:
        conn.close()



def enqueue_tenant_job(repository: str, job_type: str, payload_ref: str, idempotency_key: str,
                       *, tenant_identity: dict, max_attempts: int = 5) -> dict:
    """Atomically enqueue and bind a job to an authenticated tenant identity."""
    if not isinstance(tenant_identity, dict):
        raise JobQueueError("authenticated tenant identity is required")
    key_id = _validate_text(tenant_identity.get("key_id"), "tenant_key_id", 64, r"[A-Fa-f0-9-]{36}")
    team_id = _validate_text(tenant_identity.get("team_id"), "team_id", 128, r"[A-Za-z0-9][A-Za-z0-9._:-]{0,127}")
    user_id = _validate_text(tenant_identity.get("user_id"), "user_id", 128, r"[A-Za-z0-9][A-Za-z0-9._:@+-]{0,127}")
    repo = _validate_text(repository.lower(), "repository", 201, r"[a-z0-9][a-z0-9._-]{0,99}/[a-z0-9][a-z0-9._-]{0,99}")
    kind = _validate_text(job_type, "job_type", 80, r"[a-z][a-z0-9_.-]{1,79}")
    ref = _validate_text(payload_ref, "payload_ref", 512, r"[A-Za-z0-9][A-Za-z0-9._:/-]{0,511}")
    idem = _validate_text(idempotency_key, "idempotency_key", 128, r"[A-Za-z0-9][A-Za-z0-9._:-]{0,127}")
    if isinstance(max_attempts, bool) or not isinstance(max_attempts, int) or not 1 <= max_attempts <= 20:
        raise JobQueueError("max_attempts must be an integer from 1 to 20")
    if repo not in [str(item).lower() for item in tenant_identity.get("repositories", [])]:
        raise JobQueueError("repository is not assigned to authenticated tenant")
    if "jobs:enqueue" not in tenant_identity.get("scopes", []):
        raise JobQueueError("tenant key does not have jobs:enqueue scope")

    now = _now().isoformat()
    conn = _connect()
    try:
        conn.execute("BEGIN IMMEDIATE")
        job_id = str(uuid.uuid4())
        conn.execute("""INSERT OR IGNORE INTO durable_jobs
            (id,repository,job_type,payload_ref,idempotency_key,status,max_attempts,available_at,
             created_at,updated_at,tenant_key_id,team_id,user_id)
            VALUES(?,?,?,?,?,'queued',?,?,?,?,?,?,?)""",
            (job_id, repo, kind, ref, idem, max_attempts, now, now, now, key_id, team_id, user_id))
        row = conn.execute("SELECT * FROM durable_jobs WHERE repository=? AND idempotency_key=?",
                           (repo, idem)).fetchone()
        if row["job_type"] != kind or row["payload_ref"] != ref:
            raise JobQueueError("idempotency key was already used with a different job type or payload reference")
        if row["tenant_key_id"] != key_id or row["team_id"] != team_id or row["user_id"] != user_id:
            raise JobQueueError("idempotency key is already bound to another tenant identity")
        conn.execute("COMMIT")
        result = dict(row)
        result.pop("payload_ref", None)
        result.pop("idempotency_key", None)
        return result
    except Exception:
        if conn.in_transaction:
            conn.execute("ROLLBACK")
        raise
    finally:
        conn.close()


def claim_job(worker_id: str, *, lease_seconds: int = 60) -> dict | None:
    worker = _validate_text(worker_id, "worker_id", 100, r"[A-Za-z0-9][A-Za-z0-9._:-]{0,99}")
    if isinstance(lease_seconds, bool) or not isinstance(lease_seconds, int) or not 10 <= lease_seconds <= 3600:
        raise JobQueueError("lease_seconds must be from 10 to 3600")
    now = _now()
    stamp = now.isoformat()
    lease_until = (now + timedelta(seconds=lease_seconds)).isoformat()
    conn = _connect()
    try:
        conn.execute("BEGIN IMMEDIATE")
        conn.execute("""UPDATE durable_jobs SET status='dead_letter', lease_owner=NULL, lease_until=NULL,
            updated_at=? WHERE status='running' AND lease_until<=? AND attempts>=max_attempts""", (stamp, stamp))
        row = conn.execute("""SELECT * FROM durable_jobs
            WHERE (status='queued' AND available_at<=?)
               OR (status='running' AND lease_until<=? AND attempts<max_attempts)
            ORDER BY available_at, created_at LIMIT 1""", (stamp, stamp)).fetchone()
        if row is None:
            conn.execute("COMMIT")
            return None
        conn.execute("""UPDATE durable_jobs SET status='running', attempts=attempts+1,
            lease_owner=?, lease_until=?, updated_at=? WHERE id=?""",
            (worker, lease_until, stamp, row["id"]))
        claimed = conn.execute("SELECT * FROM durable_jobs WHERE id=?", (row["id"],)).fetchone()
        conn.execute("COMMIT")
        result = dict(claimed)
        result.pop("idempotency_key", None)
        return result
    except Exception:
        if conn.in_transaction:
            conn.execute("ROLLBACK")
        raise
    finally:
        conn.close()


def finish_job(job_id: str, worker_id: str) -> bool:
    return _finish(job_id, worker_id, status="succeeded")


def fail_job(job_id: str, worker_id: str, error_code: str, *, retryable: bool = True) -> bool:
    code = _validate_text(error_code, "error_code", 80, r"[a-zA-Z0-9_.-]{1,80}")
    conn = _connect()
    try:
        conn.execute("BEGIN IMMEDIATE")
        row = conn.execute("SELECT attempts,max_attempts FROM durable_jobs WHERE id=? AND status='running' AND lease_owner=?",
                           (job_id, worker_id)).fetchone()
        if row is None:
            conn.execute("ROLLBACK")
            return False
        terminal = (not retryable) or row["attempts"] >= row["max_attempts"]
        delay = min(3600, 2 ** min(row["attempts"], 10))
        available = (_now() + timedelta(seconds=delay)).isoformat()
        conn.execute("""UPDATE durable_jobs SET status=?, available_at=?, lease_owner=NULL, lease_until=NULL,
            last_error_code=?, updated_at=? WHERE id=?""",
            ("dead_letter" if terminal else "queued", available, code, _now().isoformat(), job_id))
        conn.execute("COMMIT")
        return True
    except Exception:
        if conn.in_transaction:
            conn.execute("ROLLBACK")
        raise
    finally:
        conn.close()


def _finish(job_id: str, worker_id: str, *, status: str) -> bool:
    conn = _connect()
    try:
        cursor = conn.execute("""UPDATE durable_jobs SET status=?, lease_owner=NULL, lease_until=NULL,
            updated_at=? WHERE id=? AND status='running' AND lease_owner=?""",
            (status, _now().isoformat(), job_id, worker_id))
        return cursor.rowcount == 1
    finally:
        conn.close()


def job_status(job_id: str, repository: str) -> dict | None:
    conn = _connect()
    try:
        row = conn.execute("""SELECT id,repository,job_type,status,attempts,max_attempts,
            available_at,lease_until,last_error_code,created_at,updated_at
            FROM durable_jobs WHERE id=? AND repository=?""", (job_id, repository.strip().lower())).fetchone()
        return dict(row) if row else None
    finally:
        conn.close()
