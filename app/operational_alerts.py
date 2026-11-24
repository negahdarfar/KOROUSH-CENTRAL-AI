"""Deduplicated operational alerts for stale or stopped background workers."""
from __future__ import annotations
import asyncio, logging, os, sqlite3, time
from typing import Any
from .quota_guard import _db_path
from .worker_heartbeat import worker_health
from .alert_notifier import _configured_channels, _send_telegram, _send_email_sync
logger = logging.getLogger(__name__)

def _connect() -> sqlite3.Connection:
    path = _db_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(path), timeout=10)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA busy_timeout=10000")
    conn.execute("""CREATE TABLE IF NOT EXISTS operational_alert_deliveries (
        event_key TEXT NOT NULL, channel TEXT NOT NULL, status TEXT NOT NULL,
        attempts INTEGER NOT NULL DEFAULT 0, updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
        PRIMARY KEY(event_key,channel))""")
    conn.commit()
    return conn

def _claim(event_key: str, channel: str) -> bool:
    conn = _connect()
    try:
        conn.execute("BEGIN IMMEDIATE")
        row = conn.execute("SELECT status,updated_at FROM operational_alert_deliveries WHERE event_key=? AND channel=?", (event_key,channel)).fetchone()
        if row and row["status"] == "sent":
            conn.commit(); return False
        if row and row["status"] == "sending":
            age = conn.execute("SELECT (julianday('now')-julianday(?))*86400 AS seconds", (row["updated_at"],)).fetchone()["seconds"]
            if age is not None and age < 600:
                conn.commit(); return False
        conn.execute("""INSERT INTO operational_alert_deliveries(event_key,channel,status,attempts)
            VALUES(?,? ,'sending',1) ON CONFLICT(event_key,channel) DO UPDATE SET
            status='sending',attempts=attempts+1,updated_at=CURRENT_TIMESTAMP""", (event_key,channel))
        conn.commit(); return True
    except Exception:
        conn.rollback(); raise
    finally: conn.close()

def _finish(event_key: str, channel: str, success: bool) -> None:
    conn = _connect()
    try:
        conn.execute("UPDATE operational_alert_deliveries SET status=?,updated_at=CURRENT_TIMESTAMP WHERE event_key=? AND channel=?", ("sent" if success else "failed",event_key,channel))
        conn.commit()
    finally: conn.close()

def _alert_state(snapshot: dict[str, Any]) -> str | None:
    state = snapshot.get("status")
    if state in {"stale","stopped","degraded"}: return str(state)
    return None

async def dispatch_operational_alerts(snapshot: dict[str, Any] | None = None) -> dict[str, Any]:
    """Send one deduplicated alert per unhealthy-state time bucket and channel."""
    channels = _configured_channels()
    if not channels: return {"configured_channels": [], "sent": 0, "failed": 0, "skipped": "No safe delivery channel configured"}
    health = snapshot if snapshot is not None else worker_health()
    state = _alert_state(health)
    if state is None: return {"configured_channels": channels, "sent": 0, "failed": 0, "skipped": "Worker has no alertable unhealthy state"}
    bucket = int(time.time() // 1800)
    event_key = f"worker:{state}:{bucket}"
    message = "\n".join(("KOROUSH CENTRAL AI — Operational alert",
        f"Component: background job worker", f"State: {state}",
        f"Heartbeat age: {health.get('heartbeat_age_seconds')} seconds",
        "Action: inspect service logs and worker configuration."))
    sent = failed = skipped = 0
    for channel in channels:
        if not _claim(event_key, channel): skipped += 1; continue
        try:
            if channel == "telegram": await _send_telegram(message)
            elif channel == "email": await asyncio.to_thread(_send_email_sync, "KOROUSH CENTRAL AI operational alert", message)
            _finish(event_key, channel, True); sent += 1
        except Exception:
            logger.warning("Operational alert delivery failed for channel %s", channel)
            _finish(event_key, channel, False); failed += 1
    return {"configured_channels": channels, "sent": sent, "failed": failed, "skipped": skipped}

async def run_operational_alert_worker() -> None:
    try: interval = max(30, min(int(os.getenv("OPERATIONAL_ALERT_POLL_SECONDS", "60")), 3600))
    except ValueError: interval = 60
    while True:
        try: await dispatch_operational_alerts()
        except asyncio.CancelledError: raise
        except Exception: logger.exception("Operational alert monitor cycle failed")
        await asyncio.sleep(interval)