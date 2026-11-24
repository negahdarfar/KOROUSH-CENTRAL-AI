"""Tenant-isolated metadata-only evidence provenance registry."""
from __future__ import annotations

import json
import sqlite3
from datetime import datetime, timezone
from urllib.parse import urlsplit

from .evidence_quality import EvidenceMetadataError, assess_evidence_item
from .quota_guard import _db_path


class EvidenceStoreError(ValueError):
    pass


class EvidenceConflict(EvidenceStoreError):
    pass


def _connect():
    path = _db_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(path), timeout=10, isolation_level=None)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA busy_timeout=10000")
    conn.execute("""
        CREATE TABLE IF NOT EXISTS evidence_registry (
            evidence_id TEXT PRIMARY KEY,
            tenant_key_id TEXT NOT NULL,
            team_id TEXT NOT NULL,
            user_id TEXT NOT NULL,
            repository TEXT NOT NULL,
            domain TEXT NOT NULL,
            source_id TEXT NOT NULL,
            content_sha256 TEXT NOT NULL,
            content_chars INTEGER NOT NULL,
            publisher TEXT,
            source_host TEXT,
            observed_at TEXT,
            freshness TEXT NOT NULL,
            created_at TEXT NOT NULL,
            UNIQUE(tenant_key_id, repository, domain, source_id)
        )
    """)
    conn.execute("CREATE INDEX IF NOT EXISTS ix_evidence_tenant_domain ON evidence_registry(tenant_key_id, repository, domain, created_at)")
    return conn


def register_evidence(*, identity: dict, repository: str, domain: str, item: dict) -> dict:
    if domain not in {"forex", "youtube", "ptc", "nft"}:
        raise EvidenceStoreError("unsupported evidence domain")
    try:
        assessed = assess_evidence_item(item)
    except EvidenceMetadataError as exc:
        raise EvidenceStoreError(str(exc)) from exc
    source_url = item.get("source_url")
    host = urlsplit(source_url).hostname.lower() if source_url else None
    evidence_id = __import__("uuid").uuid4().hex
    created_at = datetime.now(timezone.utc).isoformat()
    conn = _connect()
    try:
        conn.execute("BEGIN IMMEDIATE")
        existing = conn.execute(
            """SELECT * FROM evidence_registry
               WHERE tenant_key_id=? AND repository=? AND domain=? AND source_id=?""",
            (identity["key_id"], repository, domain, assessed["source_id"]),
        ).fetchone()
        if existing:
            if existing["content_sha256"] != assessed["sha256"]:
                raise EvidenceConflict("source_id already exists with different content")
            conn.execute("COMMIT")
            return {**dict(existing), "idempotent_replay": True}
        conn.execute(
            """INSERT INTO evidence_registry
            (evidence_id,tenant_key_id,team_id,user_id,repository,domain,source_id,
             content_sha256,content_chars,publisher,source_host,observed_at,freshness,created_at)
            VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
            (evidence_id, identity["key_id"], identity["team_id"], identity["user_id"],
             repository, domain, assessed["source_id"], assessed["sha256"],
             len(item["text"]), assessed["publisher"], host, assessed["observed_at"],
             assessed["freshness"], created_at),
        )
        conn.execute("COMMIT")
        row = conn.execute("SELECT * FROM evidence_registry WHERE evidence_id=?", (evidence_id,)).fetchone()
        return {**dict(row), "idempotent_replay": False}
    except Exception:
        if conn.in_transaction:
            conn.execute("ROLLBACK")
        raise
    finally:
        conn.close()


def list_evidence(*, identity: dict, repository: str, domain: str | None = None, limit: int = 50) -> list[dict]:
    conn = _connect()
    try:
        query = """SELECT evidence_id,repository,domain,source_id,content_sha256,content_chars,
                   publisher,source_host,observed_at,freshness,created_at
                   FROM evidence_registry WHERE tenant_key_id=? AND repository=?"""
        params: list = [identity["key_id"], repository]
        if domain:
            query += " AND domain=?"
            params.append(domain)
        query += " ORDER BY created_at DESC LIMIT ?"
        params.append(limit)
        return [dict(row) for row in conn.execute(query, params).fetchall()]
    finally:
        conn.close()
