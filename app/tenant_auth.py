"""Hashed, team-scoped API keys for tenant inference access.

Keys are shown once at creation. Only HMAC-SHA256 digests are persisted.
This module deliberately does not replace the operator ALLOWED_REPOS boundary.
"""
from __future__ import annotations

import hashlib
import hmac
import json
import os
import secrets
import sqlite3
import uuid
from pathlib import Path
from typing import Any

from .quota_guard import _db_path


class TenantAuthError(ValueError):
    pass


def _pepper() -> bytes:
    value = os.getenv("TENANT_AUTH_PEPPER", "")
    if len(value) < 32:
        raise RuntimeError("TENANT_AUTH_PEPPER must contain at least 32 characters; tenant authentication is disabled")
    return value.encode("utf-8")


def _connect() -> sqlite3.Connection:
    path = _db_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(path), timeout=10)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA busy_timeout=10000")
    conn.execute("""
        CREATE TABLE IF NOT EXISTS tenant_repositories (
            repository TEXT PRIMARY KEY,
            team_id TEXT NOT NULL,
            created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
        )
    """)
    conn.execute("""
        CREATE TABLE IF NOT EXISTS tenant_api_keys (
            key_id TEXT PRIMARY KEY,
            key_hash TEXT NOT NULL UNIQUE,
            key_prefix TEXT NOT NULL,
            user_id TEXT NOT NULL,
            team_id TEXT NOT NULL,
            repositories_json TEXT NOT NULL,
            scopes_json TEXT NOT NULL,
            created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
            revoked_at TEXT
        )
    """)
    conn.execute("CREATE INDEX IF NOT EXISTS ix_tenant_keys_team ON tenant_api_keys(team_id)")
    conn.commit()
    return conn


def _digest(raw_key: str) -> str:
    return hmac.new(_pepper(), raw_key.encode("utf-8"), hashlib.sha256).hexdigest()


def create_tenant_key(*, user_id: str, team_id: str, repositories: list[str],
                      scopes: list[str] | None = None) -> dict[str, Any]:
    user = user_id.strip()
    team = team_id.strip().lower()
    repos = sorted({item.strip().lower() for item in repositories if isinstance(item, str) and item.strip()})
    allowed_scopes = sorted(set(scopes or ["inference:chat"]))
    if not user or len(user) > 128 or not team or len(team) > 128:
        raise TenantAuthError("user_id and team_id are required and must be at most 128 characters")
    if not repos:
        raise TenantAuthError("At least one approved repository is required")
    for repo in repos:
        parts = repo.split("/")
        if len(parts) != 2 or any(not part or part in {".", ".."} for part in parts):
            raise TenantAuthError("Repositories must use exact owner/repository identities")
    supported = {"inference:chat"}
    if not allowed_scopes or not set(allowed_scopes).issubset(supported):
        raise TenantAuthError("Unsupported or empty tenant scope")
    pepper = _pepper()
    del pepper  # validate configuration before creating any credential
    raw_key = "kor_" + secrets.token_urlsafe(32)
    key_id = str(uuid.uuid4())
    conn = _connect()
    try:
        conn.execute("BEGIN IMMEDIATE")
        for repo in repos:
            row = conn.execute("SELECT team_id FROM tenant_repositories WHERE repository=?", (repo,)).fetchone()
            if row and row["team_id"] != team:
                raise TenantAuthError(f"Repository {repo} is already assigned to another team")
            conn.execute("INSERT OR IGNORE INTO tenant_repositories(repository,team_id) VALUES(?,?)", (repo, team))
        conn.execute(
            """INSERT INTO tenant_api_keys
            (key_id,key_hash,key_prefix,user_id,team_id,repositories_json,scopes_json)
            VALUES(?,?,?,?,?,?,?)""",
            (key_id, _digest(raw_key), raw_key[:12], user, team,
             json.dumps(repos), json.dumps(allowed_scopes)),
        )
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()
    return {
        "key_id": key_id,
        "api_key": raw_key,
        "key_prefix": raw_key[:12],
        "user_id": user,
        "team_id": team,
        "repositories": repos,
        "scopes": allowed_scopes,
        "warning": "This secret is shown once. Store it securely; it cannot be retrieved later.",
    }


def authenticate_tenant_key(raw_key: str | None) -> dict[str, Any] | None:
    if not isinstance(raw_key, str) or not raw_key.startswith("kor_") or len(raw_key) > 256:
        return None
    digest = _digest(raw_key)
    conn = _connect()
    try:
        row = conn.execute(
            "SELECT * FROM tenant_api_keys WHERE key_hash=? AND revoked_at IS NULL",
            (digest,),
        ).fetchone()
        if not row or not hmac.compare_digest(row["key_hash"], digest):
            return None
        return {
            "key_id": row["key_id"],
            "user_id": row["user_id"],
            "team_id": row["team_id"],
            "repositories": json.loads(row["repositories_json"]),
            "scopes": json.loads(row["scopes_json"]),
        }
    finally:
        conn.close()


def revoke_tenant_key(key_id: str) -> bool:
    conn = _connect()
    try:
        cursor = conn.execute(
            "UPDATE tenant_api_keys SET revoked_at=CURRENT_TIMESTAMP WHERE key_id=? AND revoked_at IS NULL",
            (key_id,),
        )
        conn.commit()
        return cursor.rowcount == 1
    finally:
        conn.close()


def list_tenant_keys(team_id: str | None = None) -> list[dict[str, Any]]:
    conn = _connect()
    try:
        if team_id:
            rows = conn.execute(
                "SELECT key_id,key_prefix,user_id,team_id,repositories_json,scopes_json,created_at,revoked_at "
                "FROM tenant_api_keys WHERE team_id=? ORDER BY created_at DESC",
                (team_id.strip().lower(),),
            ).fetchall()
        else:
            rows = conn.execute(
                "SELECT key_id,key_prefix,user_id,team_id,repositories_json,scopes_json,created_at,revoked_at "
                "FROM tenant_api_keys ORDER BY created_at DESC"
            ).fetchall()
        return [{
            "key_id": row["key_id"], "key_prefix": row["key_prefix"],
            "user_id": row["user_id"], "team_id": row["team_id"],
            "repositories": json.loads(row["repositories_json"]),
            "scopes": json.loads(row["scopes_json"]),
            "created_at": row["created_at"], "revoked": bool(row["revoked_at"]),
        } for row in rows]
    finally:
        conn.close()


def authorize_tenant_inference(raw_key: str | None, repository: str | None) -> dict[str, Any]:
    identity = authenticate_tenant_key(raw_key)
    if not identity:
        raise TenantAuthError("Invalid or revoked tenant API key")
    if "inference:chat" not in identity["scopes"]:
        raise TenantAuthError("Tenant API key does not have inference:chat scope")
    repo = (repository or "").strip().lower()
    if not repo or repo not in identity["repositories"]:
        raise TenantAuthError("Repository is not assigned to this user/team API key")
    return identity
