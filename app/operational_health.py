"""Operational readiness checks that never expose secrets or filesystem paths."""
from __future__ import annotations

import os
import sqlite3
from pathlib import Path

from fastapi import APIRouter, HTTPException
from .quota_guard import _db_path

router = APIRouter()


def _mounted_at_data() -> bool:
    """Return true only when /data is an actual mount point in this runtime."""
    try:
        with open("/proc/mounts", "r", encoding="utf-8") as mounts:
            return any(len(parts) > 1 and parts[1] == "/data" for parts in
                       (line.split() for line in mounts))
    except OSError:
        return False


def _database_probe() -> dict:
    path = _db_path()
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        connection = sqlite3.connect(str(path), timeout=3, isolation_level=None)
        try:
            connection.execute("PRAGMA busy_timeout=3000")
            check = connection.execute("PRAGMA quick_check").fetchone()
            if not check or check[0] != "ok":
                return {"status": "error", "reason": "integrity_check_failed"}
            connection.execute("BEGIN IMMEDIATE")
            connection.execute("CREATE TEMP TABLE IF NOT EXISTS readiness_probe (value INTEGER)")
            connection.execute("INSERT INTO readiness_probe(value) VALUES (1)")
            connection.execute("DELETE FROM readiness_probe")
            connection.rollback()
        finally:
            connection.close()
        durable = _mounted_at_data() and (path == Path("/data") or Path("/data") in path.parents)
        return {
            "status": "ok",
            "write_probe": "ok",
            "persistence": "mounted_volume_detected" if durable else "not_verified",
        }
    except (OSError, sqlite3.Error):
        return {"status": "error", "reason": "database_unavailable_or_not_writable"}


@router.get("/readyz")
async def readiness():
    """Report operational readiness without returning secrets or internal paths."""
    database = _database_probe()
    allowlist_configured = bool(os.getenv("ALLOWED_REPOS", "").strip())
    tenant_auth_configured = len(os.getenv("TENANT_AUTH_PEPPER", "")) >= 32
    llm_provider = os.getenv("LLM_PROVIDER", "legacy").strip().lower()
    inference_configured = (
        allowlist_configured
        and llm_provider == "avalai"
        and bool(os.getenv("AVALAI_API_KEY", "").strip())
    )
    payload = {
        "status": "ready" if database["status"] == "ok" else "not_ready",
        "components": {
            "database": database,
            "operator_allowlist": "configured" if allowlist_configured else "missing_inference_blocked",
            "tenant_auth": "configured" if tenant_auth_configured else "disabled_missing_pepper",
            "inference": "configuration_present" if inference_configured else "blocked_or_not_configured",
        },
        "notes": [
            "A writable database does not prove persistence across container replacement.",
            "mounted_volume_detected is reported only when /data is an actual mount point.",
            "Provider price evidence and live upstream availability are not checked by this endpoint.",
        ],
    }
    if database["status"] != "ok":
        raise HTTPException(status_code=503, detail=payload)
    return payload
