"""Encrypted-at-rest storage for bounded durable-job payloads.

The encryption key is supplied only through JOB_PAYLOAD_ENCRYPTION_KEY
(Fernet URL-safe base64 key). Ciphertext is stored in the existing SQLite DB;
plaintext is never persisted by this module.
"""
from __future__ import annotations

import json
import os
import re
import sqlite3
import uuid
from datetime import datetime, timedelta, timezone
from typing import Any

from cryptography.fernet import Fernet, InvalidToken

from .quota_guard import _db_path


MAX_PAYLOAD_BYTES = 64 * 1024
DEFAULT_TTL_SECONDS = 24 * 60 * 60


class JobPayloadError(RuntimeError):
    pass


def _cipher() -> Fernet:
    raw = os.getenv("JOB_PAYLOAD_ENCRYPTION_KEY", "").strip()
    if not raw:
        raise JobPayloadError("JOB_PAYLOAD_ENCRYPTION_KEY is not configured; payload storage is disabled")
    try:
        return Fernet(raw.encode("ascii"))
    except (ValueError, UnicodeEncodeError) as exc:
        raise JobPayloadError("JOB_PAYLOAD_ENCRYPTION_KEY must be a valid Fernet key") from exc


def _connect() -> sqlite3.Connection:
    path = _db_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(path), timeout=10, isolation_level=None)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA busy_timeout=10000")
    conn.execute("""
        CREATE TABLE IF NOT EXISTS encrypted_job_payloads (
            payload_id TEXT PRIMARY KEY,
            ciphertext BLOB NOT NULL,
            created_at TEXT NOT NULL,
            expires_at TEXT NOT NULL
        )
    """)
    conn.execute("CREATE INDEX IF NOT EXISTS ix_job_payload_expiry ON encrypted_job_payloads(expires_at)")
    return conn


def put_payload(payload: Any, *, ttl_seconds: int = DEFAULT_TTL_SECONDS) -> str:
    """Encrypt JSON payload and return an opaque vault reference."""
    if isinstance(ttl_seconds, bool) or not isinstance(ttl_seconds, int) or not 60 <= ttl_seconds <= 7 * 24 * 60 * 60:
        raise JobPayloadError("ttl_seconds must be between 60 seconds and 7 days")
    try:
        plaintext = json.dumps(payload, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
    except (TypeError, ValueError) as exc:
        raise JobPayloadError("payload must be JSON serializable") from exc
    if not plaintext or len(plaintext) > MAX_PAYLOAD_BYTES:
        raise JobPayloadError(f"payload must be between 1 and {MAX_PAYLOAD_BYTES} bytes")
    ciphertext = _cipher().encrypt(plaintext)
    payload_id = str(uuid.uuid4())
    now = datetime.now(timezone.utc)
    conn = _connect()
    try:
        conn.execute(
            "INSERT INTO encrypted_job_payloads(payload_id,ciphertext,created_at,expires_at) VALUES(?,?,?,?)",
            (payload_id, ciphertext, now.isoformat(), (now + timedelta(seconds=ttl_seconds)).isoformat()),
        )
    finally:
        conn.close()
    return "vault:" + payload_id


def get_payload(reference: str) -> Any:
    """Resolve and decrypt a non-expired payload; never return ciphertext metadata."""
    if not isinstance(reference, str) or not re.fullmatch(r"vault:[0-9a-f-]{36}", reference):
        raise JobPayloadError("payload reference is invalid")
    cipher = _cipher()
    payload_id = reference[6:]
    conn = _connect()
    try:
        row = conn.execute(
            "SELECT ciphertext,expires_at FROM encrypted_job_payloads WHERE payload_id=?",
            (payload_id,),
        ).fetchone()
    finally:
        conn.close()
    if row is None:
        raise JobPayloadError("payload was not found or has expired")
    if datetime.fromisoformat(row["expires_at"]) <= datetime.now(timezone.utc):
        delete_payload(reference)
        raise JobPayloadError("payload was not found or has expired")
    try:
        plaintext = cipher.decrypt(bytes(row["ciphertext"]))
        return json.loads(plaintext.decode("utf-8"))
    except (InvalidToken, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise JobPayloadError("payload could not be authenticated or decoded") from exc


def delete_payload(reference: str) -> bool:
    if not isinstance(reference, str) or not re.fullmatch(r"vault:[0-9a-f-]{36}", reference):
        return False
    conn = _connect()
    try:
        cursor = conn.execute("DELETE FROM encrypted_job_payloads WHERE payload_id=?", (reference[6:],))
        return cursor.rowcount == 1
    finally:
        conn.close()


def prune_expired_payloads(*, limit: int = 500) -> int:
    if isinstance(limit, bool) or not isinstance(limit, int) or not 1 <= limit <= 5000:
        raise JobPayloadError("limit must be between 1 and 5000")
    conn = _connect()
    try:
        conn.execute("BEGIN IMMEDIATE")
        rows = conn.execute(
            "SELECT payload_id FROM encrypted_job_payloads WHERE expires_at<=? ORDER BY expires_at LIMIT ?",
            (datetime.now(timezone.utc).isoformat(), limit),
        ).fetchall()
        if rows:
            conn.executemany("DELETE FROM encrypted_job_payloads WHERE payload_id=?",
                             [(row["payload_id"],) for row in rows])
        conn.execute("COMMIT")
        return len(rows)
    except Exception:
        if conn.in_transaction:
            conn.execute("ROLLBACK")
        raise
    finally:
        conn.close()
