"""Tenant-scoped durable event delivery with encrypted payload references.

The event index stores metadata only. Payload content is encrypted by the existing
job payload vault; delivery is at-least-once and consumers must be idempotent.
"""
from __future__ import annotations

import re
import sqlite3
import uuid
from datetime import datetime, timedelta, timezone

from .quota_guard import _db_path


class EventBusError(ValueError):
    pass


def _now():
    return datetime.now(timezone.utc)


def _connect():
    path = _db_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(path), timeout=10, isolation_level=None)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA busy_timeout=10000")
    conn.execute("""CREATE TABLE IF NOT EXISTS platform_events (
        event_id TEXT PRIMARY KEY, tenant_key_id TEXT NOT NULL, team_id TEXT NOT NULL,
        repository TEXT NOT NULL, event_type TEXT NOT NULL, schema_version INTEGER NOT NULL,
        producer TEXT NOT NULL, consumer TEXT NOT NULL, correlation_id TEXT,
        causation_id TEXT, idempotency_key TEXT NOT NULL, payload_ref TEXT NOT NULL,
        status TEXT NOT NULL CHECK(status IN ('queued','leased','delivered','dead_letter')),
        attempts INTEGER NOT NULL DEFAULT 0, max_attempts INTEGER NOT NULL, payload_hash TEXT,
        available_at TEXT NOT NULL, lease_owner TEXT, lease_until TEXT,
        created_at TEXT NOT NULL, updated_at TEXT NOT NULL,
        UNIQUE(tenant_key_id, repository, consumer, idempotency_key)
    )""")
    conn.execute("CREATE INDEX IF NOT EXISTS ix_platform_events_claim ON platform_events(status,consumer,available_at,lease_until)")
    conn.execute("CREATE INDEX IF NOT EXISTS ix_platform_events_tenant ON platform_events(tenant_key_id,repository,created_at)")
    columns = {row["name"] for row in conn.execute("PRAGMA table_info(platform_events)").fetchall()}
    if "payload_hash" not in columns:
        conn.execute("ALTER TABLE platform_events ADD COLUMN payload_hash TEXT")
    return conn


def _text(value, field, limit, pattern):
    if not isinstance(value, str):
        raise EventBusError(f"{field} must be text")
    value = value.strip()
    if not value or len(value) > limit or not re.fullmatch(pattern, value):
        raise EventBusError(f"{field} has an invalid format")
    return value


def _identity(identity, repository, scope):
    if not isinstance(identity, dict):
        raise EventBusError("authenticated tenant identity is required")
    repo = _text(repository.lower(), "repository", 201, r"[a-z0-9][a-z0-9._-]{0,99}/[a-z0-9][a-z0-9._-]{0,99}")
    if repo not in [str(x).lower() for x in identity.get("repositories", [])]:
        raise EventBusError("repository is not assigned to authenticated tenant")
    if scope not in identity.get("scopes", []):
        raise EventBusError(f"tenant key lacks {scope} scope")
    return repo


def publish_event(*, identity, repository, event_type, schema_version, producer,
                  consumer, idempotency_key, payload_ref, payload_hash, correlation_id=None,
                  causation_id=None, max_attempts=5):
    repo = _identity(identity, repository, "events:publish")
    kind = _text(event_type, "event_type", 120, r"[a-z][a-z0-9_.-]{1,119}")
    source = _text(producer, "producer", 120, r"[a-zA-Z0-9][a-zA-Z0-9._:/-]{0,119}")
    target = _text(consumer, "consumer", 120, r"[a-zA-Z0-9][a-zA-Z0-9._:/-]{0,119}")
    idem = _text(idempotency_key, "idempotency_key", 128, r"[A-Za-z0-9][A-Za-z0-9._:-]{0,127}")
    ref = _text(payload_ref, "payload_ref", 64, r"vault:[0-9a-f-]{36}")
    digest = _text(payload_hash, "payload_hash", 64, r"[a-f0-9]{64}")
    if isinstance(schema_version, bool) or not isinstance(schema_version, int) or not 1 <= schema_version <= 1000:
        raise EventBusError("schema_version must be an integer from 1 to 1000")
    if isinstance(max_attempts, bool) or not isinstance(max_attempts, int) or not 1 <= max_attempts <= 20:
        raise EventBusError("max_attempts must be an integer from 1 to 20")
    correlation = _text(correlation_id, "correlation_id", 64, r"[A-Za-z0-9][A-Za-z0-9._:-]{0,63}") if correlation_id else None
    causation = _text(causation_id, "causation_id", 64, r"[A-Za-z0-9][A-Za-z0-9._:-]{0,63}") if causation_id else None
    now = _now().isoformat()
    conn = _connect()
    try:
        conn.execute("BEGIN IMMEDIATE")
        row = conn.execute("""SELECT * FROM platform_events
            WHERE tenant_key_id=? AND repository=? AND consumer=? AND idempotency_key=?""",
            (identity["key_id"], repo, target, idem)).fetchone()
        replay = row is not None
        if row:
            if row["event_type"] != kind or row["payload_hash"] != digest or row["producer"] != source:
                raise EventBusError("idempotency key conflicts with an existing event")
        else:
            event_id = str(uuid.uuid4())
            conn.execute("""INSERT INTO platform_events
              (event_id,tenant_key_id,team_id,repository,event_type,schema_version,producer,consumer,
               correlation_id,causation_id,idempotency_key,payload_ref,status,attempts,max_attempts,payload_hash,
               available_at,created_at,updated_at)
              VALUES(?,?,?,?,?,?,?,?,?,?,?,?,'queued',0,?,?,?,?,?)""",
              (event_id, identity["key_id"], identity["team_id"], repo, kind, schema_version,
               source, target, correlation, causation, idem, ref, max_attempts, digest, now, now, now))
            row = conn.execute("SELECT * FROM platform_events WHERE event_id=?", (event_id,)).fetchone()
        conn.execute("COMMIT")
        return {"event_id": row["event_id"], "status": row["status"], "idempotent_replay": replay,
                "repository": repo, "event_type": row["event_type"], "consumer": target,
                "created_at": row["created_at"]}
    except Exception:
        if conn.in_transaction:
            conn.execute("ROLLBACK")
        raise
    finally:
        conn.close()


def claim_event(*, identity, repository, consumer, worker_id, lease_seconds=60):
    repo = _identity(identity, repository, "events:consume")
    target = _text(consumer, "consumer", 120, r"[a-zA-Z0-9][a-zA-Z0-9._:/-]{0,119}")
    worker = _text(worker_id, "worker_id", 100, r"[A-Za-z0-9][A-Za-z0-9._:-]{0,99}")
    if isinstance(lease_seconds, bool) or not isinstance(lease_seconds, int) or not 10 <= lease_seconds <= 3600:
        raise EventBusError("lease_seconds must be from 10 to 3600")
    now = _now()
    conn = _connect()
    try:
        conn.execute("BEGIN IMMEDIATE")
        row = conn.execute("""SELECT * FROM platform_events
          WHERE tenant_key_id=? AND repository=? AND consumer=? AND
          ((status='queued' AND available_at<=?) OR (status='leased' AND lease_until<=?))
          ORDER BY created_at LIMIT 1""",
          (identity["key_id"], repo, target, now.isoformat(), now.isoformat())).fetchone()
        if not row:
            conn.execute("COMMIT")
            return None
        until = (now + timedelta(seconds=lease_seconds)).isoformat()
        conn.execute("""UPDATE platform_events SET status='leased',lease_owner=?,lease_until=?,
          attempts=attempts+1,updated_at=? WHERE event_id=?""",
          (worker, until, now.isoformat(), row["event_id"]))
        conn.execute("COMMIT")
        return {"event_id": row["event_id"], "event_type": row["event_type"],
                "schema_version": row["schema_version"], "producer": row["producer"],
                "correlation_id": row["correlation_id"], "causation_id": row["causation_id"],
                "payload_ref": row["payload_ref"], "attempt": row["attempts"] + 1,
                "lease_owner": worker, "lease_until": until}
    except Exception:
        if conn.in_transaction:
            conn.execute("ROLLBACK")
        raise
    finally:
        conn.close()


def settle_event(*, identity, repository, event_id, worker_id, success, retryable=True):
    repo = _identity(identity, repository, "events:consume")
    event = _text(event_id, "event_id", 36, r"[0-9a-f-]{36}")
    worker = _text(worker_id, "worker_id", 100, r"[A-Za-z0-9][A-Za-z0-9._:-]{0,99}")
    now = _now()
    conn = _connect()
    try:
        conn.execute("BEGIN IMMEDIATE")
        row = conn.execute("""SELECT * FROM platform_events WHERE event_id=? AND tenant_key_id=?
          AND repository=? AND status='leased' AND lease_owner=? AND lease_until>?""",
          (event, identity["key_id"], repo, worker, now.isoformat())).fetchone()
        if not row:
            raise EventBusError("event lease is missing, expired, or owned by another worker")
        if success:
            status, available = "delivered", now.isoformat()
        elif not retryable or row["attempts"] >= row["max_attempts"]:
            status, available = "dead_letter", now.isoformat()
        else:
            delay = min(3600, 2 ** min(row["attempts"], 10))
            status, available = "queued", (now + timedelta(seconds=delay)).isoformat()
        conn.execute("""UPDATE platform_events SET status=?,available_at=?,lease_owner=NULL,
          lease_until=NULL,updated_at=? WHERE event_id=?""",
          (status, available, now.isoformat(), event))
        conn.execute("COMMIT")
        return {"event_id": event, "status": status}
    except Exception:
        if conn.in_transaction:
            conn.execute("ROLLBACK")
        raise
    finally:
        conn.close()


def list_events(*, identity, repository, limit=50):
    repo = _identity(identity, repository, "events:read")
    if isinstance(limit, bool) or not isinstance(limit, int) or not 1 <= limit <= 100:
        raise EventBusError("limit must be from 1 to 100")
    conn = _connect()
    try:
        rows = conn.execute("""SELECT event_id,event_type,schema_version,producer,consumer,
          correlation_id,causation_id,status,attempts,max_attempts,created_at,updated_at
          FROM platform_events WHERE tenant_key_id=? AND repository=? ORDER BY created_at DESC LIMIT ?""",
          (identity["key_id"], repo, limit)).fetchall()
        return [dict(row) for row in rows]
    finally:
        conn.close()
