from datetime import datetime, timedelta, timezone
import sqlite3

import pytest
from cryptography.fernet import Fernet

from app.job_payload_store import (
    JobPayloadError, get_payload, put_payload, delete_payload, prune_expired_payloads,
)
from app.quota_guard import _db_path


def test_payload_round_trip_and_ciphertext_at_rest(tmp_path, monkeypatch):
    monkeypatch.setenv("USAGE_DB_PATH", str(tmp_path / "payloads.sqlite3"))
    monkeypatch.setenv("JOB_PAYLOAD_ENCRYPTION_KEY", Fernet.generate_key().decode())
    payload = {"prompt": "confidential test text", "nested": {"x": 7}}
    reference = put_payload(payload)
    assert get_payload(reference) == payload
    conn = sqlite3.connect(_db_path())
    try:
        stored = conn.execute("SELECT ciphertext FROM encrypted_job_payloads").fetchone()[0]
    finally:
        conn.close()
    assert b"confidential test text" not in stored
    assert b'"prompt"' not in stored


def test_payload_store_fails_closed_without_key(tmp_path, monkeypatch):
    monkeypatch.setenv("USAGE_DB_PATH", str(tmp_path / "payloads.sqlite3"))
    monkeypatch.delenv("JOB_PAYLOAD_ENCRYPTION_KEY", raising=False)
    with pytest.raises(JobPayloadError, match="not configured"):
        put_payload({"secret": "value"})


def test_payload_rejects_oversize_and_invalid_references(tmp_path, monkeypatch):
    monkeypatch.setenv("USAGE_DB_PATH", str(tmp_path / "payloads.sqlite3"))
    monkeypatch.setenv("JOB_PAYLOAD_ENCRYPTION_KEY", Fernet.generate_key().decode())
    with pytest.raises(JobPayloadError, match="between 1"):
        put_payload({"data": "x" * 70000})
    with pytest.raises(JobPayloadError, match="invalid"):
        get_payload("vault:../../secret")


def test_payload_expiry_and_pruning(tmp_path, monkeypatch):
    monkeypatch.setenv("USAGE_DB_PATH", str(tmp_path / "payloads.sqlite3"))
    monkeypatch.setenv("JOB_PAYLOAD_ENCRYPTION_KEY", Fernet.generate_key().decode())
    reference = put_payload({"short": True}, ttl_seconds=60)
    conn = sqlite3.connect(_db_path())
    try:
        expired = (datetime.now(timezone.utc) - timedelta(seconds=5)).isoformat()
        conn.execute("UPDATE encrypted_job_payloads SET expires_at=?", (expired,))
        conn.commit()
    finally:
        conn.close()
    with pytest.raises(JobPayloadError, match="expired"):
        get_payload(reference)
    assert prune_expired_payloads() == 0
    assert delete_payload(reference) is False
