"""SQLite-backed liveness signal for the opt-in single-process worker."""
from __future__ import annotations
import os, sqlite3
from datetime import datetime, timezone
from .quota_guard import _db_path

def _connect():
    path = _db_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(path), timeout=5)
    conn.execute("PRAGMA busy_timeout=5000")
    conn.execute("""CREATE TABLE IF NOT EXISTS worker_heartbeat (singleton INTEGER PRIMARY KEY CHECK(singleton=1), worker_id TEXT NOT NULL, state TEXT NOT NULL, updated_at TEXT NOT NULL)""")
    return conn

def record_worker_heartbeat(worker_id: str, state: str) -> None:
    if state not in {"starting", "running", "degraded", "stopped"}:
        raise ValueError("invalid worker state")
    conn = _connect()
    try:
        conn.execute("""INSERT INTO worker_heartbeat(singleton,worker_id,state,updated_at) VALUES(1,?,?,?) ON CONFLICT(singleton) DO UPDATE SET worker_id=excluded.worker_id,state=excluded.state,updated_at=excluded.updated_at""", (worker_id[:100], state, datetime.now(timezone.utc).isoformat()))
        conn.commit()
    finally:
        conn.close()

def worker_health(*, stale_after_seconds: int = 60) -> dict:
    enabled = os.getenv("JOB_WORKER_ENABLED", "false").strip().lower() in {"1", "true", "yes"}
    if not enabled:
        return {"status": "disabled", "heartbeat_age_seconds": None}
    conn = _connect()
    try:
        row = conn.execute("SELECT state,updated_at FROM worker_heartbeat WHERE singleton=1").fetchone()
    finally:
        conn.close()
    if row is None:
        return {"status": "not_started", "heartbeat_age_seconds": None}
    try:
        stamp = datetime.fromisoformat(row[1])
        age = max(0, int((datetime.now(timezone.utc) - stamp).total_seconds()))
    except (TypeError, ValueError):
        return {"status": "unknown", "heartbeat_age_seconds": None}
    if row[0] == "stopped": status = "stopped"
    elif age > stale_after_seconds: status = "stale"
    else: status = row[0]
    return {"status": status, "heartbeat_age_seconds": age}