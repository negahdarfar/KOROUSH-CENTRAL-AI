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


class IdempotencyConflict(JobQueueError):
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
    for name, declaration in (("tenant_key_id", "TEXT"), ("team_id", "TEXT"), ("user_id", "TEXT"), ("result_ref", "TEXT"), ("payload_hash", "TEXT"), ("manual_requeues", "INTEGER NOT NULL DEFAULT 0")):
        if name not in columns:
            conn.execute(f"ALTER TABLE durable_jobs ADD COLUMN {name} {declaration}")
    conn.execute("CREATE INDEX IF NOT EXISTS ix_jobs_repo_created ON durable_jobs(repository, created_at)")
    conn.execute("CREATE INDEX IF NOT EXISTS ix_jobs_tenant_status ON durable_jobs(tenant_key_id, status, created_at)")
    conn.execute("""CREATE TABLE IF NOT EXISTS job_admin_events (
        event_id TEXT PRIMARY KEY,
        job_id TEXT NOT NULL,
        repository TEXT NOT NULL,
        action TEXT NOT NULL,
        event_at TEXT NOT NULL,
        manual_requeues INTEGER NOT NULL
    )""")
    conn.execute("CREATE INDEX IF NOT EXISTS ix_job_admin_events_repo_time ON job_admin_events(repository, event_at)")
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
                       *, tenant_identity: dict, max_attempts: int = 5, payload_hash: str | None = None) -> dict:
    """Atomically enqueue and bind a job to the authenticated key/team/user."""
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
    if payload_hash is not None and not re.fullmatch(r"[a-f0-9]{64}", payload_hash):
        raise JobQueueError("payload_hash must be a SHA-256 hex digest")
    if repo not in [str(item).lower() for item in tenant_identity.get("repositories", [])]:
        raise JobQueueError("repository is not assigned to authenticated tenant")
    if "jobs:enqueue" not in tenant_identity.get("scopes", []):
        raise JobQueueError("tenant key does not have jobs:enqueue scope")

    now = _now().isoformat()
    conn = _connect()
    try:
        conn.execute("BEGIN IMMEDIATE")
        existing = conn.execute(
            "SELECT * FROM durable_jobs WHERE repository=? AND idempotency_key=?", (repo, idem)
        ).fetchone()
        replay = existing is not None
        if existing:
            if existing["tenant_key_id"] != key_id or existing["team_id"] != team_id or existing["user_id"] != user_id:
                raise JobQueueError("idempotency key is already bound to another tenant identity")
            if existing["job_type"] != kind:
                raise IdempotencyConflict("idempotency key was already used for a different job type")
            if payload_hash is not None and (not existing["payload_hash"] or existing["payload_hash"] != payload_hash):
                raise IdempotencyConflict("idempotency key was already used with a different or unverifiable payload")
            row = existing
        else:
            job_id = str(uuid.uuid4())
            conn.execute("""INSERT INTO durable_jobs
                (id,repository,job_type,payload_ref,idempotency_key,status,max_attempts,available_at,
                 created_at,updated_at,tenant_key_id,team_id,user_id,payload_hash)
                VALUES(?,?,?,?,?,'queued',?,?,?,?,?,?,?,?)""",
                (job_id, repo, kind, ref, idem, max_attempts, now, now, now, key_id, team_id, user_id, payload_hash))
            row = conn.execute("SELECT * FROM durable_jobs WHERE id=?", (job_id,)).fetchone()
        conn.execute("COMMIT")
        result = dict(row)
        result.pop("payload_ref", None)
        result.pop("idempotency_key", None)
        result["idempotent_replay"] = replay
        return result
    except Exception:
        if conn.in_transaction:
            conn.execute("ROLLBACK")
        raise
    finally:
        conn.close()


def tenant_job_status(job_id: str, *, repository: str, tenant_identity: dict) -> dict | None:
    """Return status only to the exact creating tenant key/user."""
    if not isinstance(tenant_identity, dict):
        return None
    repo = str(repository or "").strip().lower()
    if repo not in [str(item).lower() for item in tenant_identity.get("repositories", [])]:
        return None
    if "jobs:read" not in tenant_identity.get("scopes", []):
        return None
    conn = _connect()
    try:
        row = conn.execute(
            """SELECT id,repository,job_type,status,attempts,max_attempts,available_at,
                      lease_until,last_error_code,created_at,updated_at,result_ref
               FROM durable_jobs
               WHERE id=? AND repository=? AND tenant_key_id=? AND team_id=? AND user_id=?""",
            (job_id, repo, tenant_identity.get("key_id"), tenant_identity.get("team_id"),
             tenant_identity.get("user_id")),
        ).fetchone()
        return dict(row) if row else None
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


def finish_job(job_id: str, worker_id: str, *, result_ref: str | None = None) -> bool:
    if result_ref is not None:
        result_ref = _validate_text(result_ref, "result_ref", 512, r"[A-Za-z0-9][A-Za-z0-9._:/-]{0,511}")
    return _finish(job_id, worker_id, status="succeeded", result_ref=result_ref)


def fail_job(job_id: str, worker_id: str, error_code: str, *, retryable: bool = True) -> bool:
    code = _validate_text(error_code, "error_code", 80, r"[a-zA-Z0-9_.-]{1,80}")
    conn = _connect()
    try:
        conn.execute("BEGIN IMMEDIATE")
        now = _now().isoformat()
        row = conn.execute("SELECT attempts,max_attempts FROM durable_jobs WHERE id=? AND status='running' AND lease_owner=? AND lease_until>?",
                           (job_id, worker_id, now)).fetchone()
        if row is None:
            conn.execute("ROLLBACK")
            return False
        terminal = (not retryable) or row["attempts"] >= row["max_attempts"]
        delay = min(3600, 2 ** min(row["attempts"], 10))
        available = (_now() + timedelta(seconds=delay)).isoformat()
        cursor = conn.execute("""UPDATE durable_jobs SET status=?, available_at=?, lease_owner=NULL, lease_until=NULL,
            last_error_code=?, updated_at=? WHERE id=? AND status='running' AND lease_owner=? AND lease_until>?""",
            ("dead_letter" if terminal else "queued", available, code, now, job_id, worker_id, now))
        if cursor.rowcount != 1:
            conn.execute("ROLLBACK")
            return False
        conn.execute("COMMIT")
        return True
    except Exception:
        if conn.in_transaction:
            conn.execute("ROLLBACK")
        raise
    finally:
        conn.close()


def _finish(job_id: str, worker_id: str, *, status: str, result_ref: str | None = None) -> bool:
    conn = _connect()
    try:
        now = _now().isoformat()
        cursor = conn.execute("""UPDATE durable_jobs SET status=?, result_ref=?, lease_owner=NULL, lease_until=NULL,
            updated_at=? WHERE id=? AND status='running' AND lease_owner=? AND lease_until>?""",
            (status, result_ref, now, job_id, worker_id, now))
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


def job_queue_summary(repository: str | None = None) -> dict:
    """Return aggregate queue counts and age metrics; never return job or tenant identifiers."""
    repo = repository.strip().lower() if isinstance(repository, str) and repository.strip() else None
    conn = _connect()
    try:
        where = " WHERE repository=?" if repo else ""
        params = (repo,) if repo else ()
        rows = conn.execute(
            f"SELECT status, COUNT(*) AS count FROM durable_jobs{where} GROUP BY status",
            params,
        ).fetchall()
        counts = {name: 0 for name in ("queued", "running", "succeeded", "failed", "dead_letter")}
        counts.update({row["status"]: int(row["count"]) for row in rows if row["status"] in counts})
        oldest = conn.execute(
            f"SELECT MIN(created_at) AS oldest_queued FROM durable_jobs WHERE status='queued'"
            + (" AND repository=?" if repo else ""),
            params,
        ).fetchone()
        oldest_age = None
        if oldest and oldest["oldest_queued"]:
            try:
                stamp = datetime.fromisoformat(oldest["oldest_queued"])
                oldest_age = max(0, int((_now() - stamp).total_seconds()))
            except (TypeError, ValueError):
                oldest_age = None
        return {
            "counts": counts,
            "total": sum(counts.values()),
            "oldest_queued_age_seconds": oldest_age,
            "scope": "repository" if repo else "global",
        }
    finally:
        conn.close()



def requeue_dead_letter_job(job_id: str, repository: str, expected_updated_at: str) -> dict | None:
    """Requeue one dead-letter job with an unexpired encrypted payload and optimistic locking.

    At most three operator requeues are allowed per job. Attempts reset for the
    controlled replay, while the separate manual_requeues counter is retained.
    """
    job = _validate_text(job_id, "job_id", 36, r"[0-9a-fA-F-]{36}")
    repo = _validate_text(repository.lower(), "repository", 201,
                          r"[a-z0-9][a-z0-9._-]{0,99}/[a-z0-9][a-z0-9._-]{0,99}")
    version = _validate_text(expected_updated_at, "expected_updated_at", 64,
                             r"[0-9T:+.\-]{20,64}")
    conn = _connect()
    try:
        conn.execute("BEGIN IMMEDIATE")
        row = conn.execute(
            """SELECT payload_ref, manual_requeues FROM durable_jobs
               WHERE id=? AND repository=? AND status='dead_letter' AND updated_at=?""",
            (job, repo, version),
        ).fetchone()
        if row is None or int(row["manual_requeues"] or 0) >= 3:
            conn.execute("ROLLBACK")
            return None
        ref = row["payload_ref"]
        if not isinstance(ref, str) or not re.fullmatch(r"vault:[0-9a-f-]{36}", ref):
            conn.execute("ROLLBACK")
            return None
        payload = conn.execute(
            "SELECT 1 FROM encrypted_job_payloads WHERE payload_id=? AND expires_at>?",
            (ref[6:], _now().isoformat()),
        ).fetchone()
        if payload is None:
            conn.execute("ROLLBACK")
            return None
        now = _now().isoformat()
        cursor = conn.execute(
            """UPDATE durable_jobs SET status='queued', attempts=0, available_at=?,
               lease_owner=NULL, lease_until=NULL, last_error_code=NULL,
               manual_requeues=manual_requeues+1, updated_at=?
               WHERE id=? AND repository=? AND status='dead_letter' AND updated_at=?
                 AND manual_requeues<3""",
            (now, now, job, repo, version),
        )
        if cursor.rowcount != 1:
            conn.execute("ROLLBACK")
            return None
        updated = conn.execute(
            """SELECT id,repository,status,attempts,max_attempts,manual_requeues,
                      available_at,updated_at FROM durable_jobs WHERE id=?""", (job,)
        ).fetchone()
        conn.execute(
            """INSERT INTO job_admin_events(event_id,job_id,repository,action,event_at,manual_requeues)
               VALUES(?,?,?,?,?,?)""",
            (str(uuid.uuid4()), job, repo, "dead_letter_requeued", now, int(updated["manual_requeues"])),
        )
        conn.execute("COMMIT")
        return dict(updated)
    except Exception:
        if conn.in_transaction:
            conn.execute("ROLLBACK")
        raise
    finally:
        conn.close()
