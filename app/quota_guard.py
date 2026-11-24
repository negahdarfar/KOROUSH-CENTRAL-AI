"""Preflight, repository-scoped internal quotas for zero-dollar inference.

Limits are project safety limits, NOT provider-published free-tier quotas.
Configure KOROUSH_REPO_QUOTAS as JSON mapping repository names (or "*") to
requests_per_day, requests_per_month, tokens_per_day, tokens_per_month.
"""
from __future__ import annotations

import json
import os
import sqlite3
import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

DEFAULT_LIMITS = {
    "requests_per_day": 20,
    "requests_per_month": 400,
    "tokens_per_day": 20000,
    "tokens_per_month": 200000,
}
ALERT_THRESHOLDS = (70, 85, 100)


class QuotaExceeded(RuntimeError):
    """Raised before provider inference when an internal repository quota is exhausted."""


def _db_path() -> Path:
    return Path(os.getenv("USAGE_DB_PATH", "/data/koroush_usage.sqlite3"))


def _connect() -> sqlite3.Connection:
    path = _db_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(path), timeout=10, isolation_level=None)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA busy_timeout=10000")
    conn.execute("""
        CREATE TABLE IF NOT EXISTS quota_reservations (
            id TEXT PRIMARY KEY,
            repository TEXT NOT NULL,
            created_at TEXT NOT NULL,
            expires_at TEXT NOT NULL,
            estimated_tokens INTEGER NOT NULL,
            actual_tokens INTEGER NOT NULL DEFAULT 0,
            status TEXT NOT NULL
        )
    """)
    conn.execute("CREATE INDEX IF NOT EXISTS ix_quota_repo_time ON quota_reservations(repository, created_at)")
    conn.execute("""
        CREATE TABLE IF NOT EXISTS usage_alerts (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            repository TEXT NOT NULL,
            period TEXT NOT NULL,
            metric TEXT NOT NULL,
            threshold INTEGER NOT NULL,
            used INTEGER NOT NULL,
            quota INTEGER NOT NULL,
            created_at TEXT NOT NULL,
            UNIQUE(repository, period, metric, threshold)
        )
    """)
    return conn


def _limits(repository: str) -> dict[str, int]:
    raw = os.getenv("KOROUSH_REPO_QUOTAS", "")
    config: dict[str, Any] = {}
    if raw:
        try:
            parsed = json.loads(raw)
            if not isinstance(parsed, dict):
                raise ValueError("quota config must be an object")
            config = parsed
        except (TypeError, json.JSONDecodeError) as exc:
            raise QuotaExceeded("Repository quota configuration is invalid; inference is fail-closed") from exc
    selected = config.get(repository, config.get("*", {}))
    if not isinstance(selected, dict):
        raise QuotaExceeded("Repository quota configuration is invalid; inference is fail-closed")
    limits = dict(DEFAULT_LIMITS)
    for key in limits:
        if key in selected:
            value = selected[key]
            if isinstance(value, bool) or not isinstance(value, int) or value < 1:
                raise QuotaExceeded(f"Invalid internal quota value for {key}; inference is fail-closed")
            limits[key] = value
    return limits


def _estimate_tokens(payload: Any) -> int:
    try:
        serialized = json.dumps(payload, ensure_ascii=False, separators=(",", ":"))
    except (TypeError, ValueError):
        serialized = str(payload)
    requested_output = 0
    if isinstance(payload, dict):
        try:
            requested_output = max(0, int(payload.get("max_tokens", payload.get("max_completion_tokens", 0)) or 0))
        except (TypeError, ValueError, OverflowError):
            requested_output = 0
    # Conservative rough reservation; actual provider usage replaces it after success.
    return max(1, (len(serialized) + 3) // 4 + requested_output)


def reserve_inference(repository: str | None, payload: Any) -> str:
    """Atomically reserve one request and estimated tokens before calling a provider."""
    repo = (repository or "").strip().lower()
    if not repo or repo == "__unassigned__":
        raise QuotaExceeded("Inference blocked: an explicit repository identity is required for quota enforcement")
    if "/" not in repo or len(repo) > 255:
        raise QuotaExceeded("Inference blocked: repository must use owner/name format")
    limits = _limits(repo)
    estimate = _estimate_tokens(payload)
    now = datetime.now(timezone.utc)
    day_start = now.replace(hour=0, minute=0, second=0, microsecond=0).isoformat()
    month_start = now.replace(day=1, hour=0, minute=0, second=0, microsecond=0).isoformat()
    timestamp = now.isoformat()
    reservation_id = str(uuid.uuid4())
    conn = _connect()
    try:
        conn.execute("BEGIN IMMEDIATE")
        conn.execute("DELETE FROM quota_reservations WHERE status='pending' AND expires_at < ?", (timestamp,))
        rows = conn.execute(
            """SELECT created_at, estimated_tokens, actual_tokens, status FROM quota_reservations
               WHERE repository=? AND created_at>=? AND status IN ('pending','complete')""", (repo, month_start)
        ).fetchall()
        day_rows = [r for r in rows if r["created_at"] >= day_start]
        month_requests = len(rows)
        day_requests = len(day_rows)
        month_tokens = sum(r["actual_tokens"] if r["status"] == "complete" else r["estimated_tokens"] for r in rows)
        day_tokens = sum(r["actual_tokens"] if r["status"] == "complete" else r["estimated_tokens"] for r in day_rows)
        checks = (
            ("requests_per_day", day_requests, 1),
            ("requests_per_month", month_requests, 1),
            ("tokens_per_day", day_tokens, estimate),
            ("tokens_per_month", month_tokens, estimate),
        )
        for key, used, addition in checks:
            if used + addition > limits[key]:
                conn.execute("ROLLBACK")
                raise QuotaExceeded(f"Repository {repo} reached its internal {key} limit ({used}/{limits[key]} used); request stopped before inference")
        conn.execute(
            "INSERT INTO quota_reservations(id,repository,created_at,expires_at,estimated_tokens,status) VALUES(?,?,?,?,?,'pending')",
            (reservation_id, repo, timestamp, (now + timedelta(minutes=15)).isoformat(), estimate),
        )
        for period_name, period_used, period_limit, metric in (
            ("day", day_requests + 1, limits["requests_per_day"], "requests"),
            ("month", month_requests + 1, limits["requests_per_month"], "requests"),
            ("day", day_tokens + estimate, limits["tokens_per_day"], "tokens"),
            ("month", month_tokens + estimate, limits["tokens_per_month"], "tokens"),
        ):
            for threshold in ALERT_THRESHOLDS:
                if period_used * 100 >= period_limit * threshold:
                    period_key = now.strftime("%Y-%m-%d" if period_name == "day" else "%Y-%m")
                    conn.execute(
                        """INSERT OR IGNORE INTO usage_alerts(repository,period,metric,threshold,used,quota,created_at)
                           VALUES(?,?,?,?,?,?,?)""",
                        (repo, period_key, metric + "_" + period_name, threshold, period_used, period_limit, timestamp),
                    )
        conn.execute("COMMIT")
        return reservation_id
    except Exception:
        if conn.in_transaction:
            conn.execute("ROLLBACK")
        raise
    finally:
        conn.close()


def complete_reservation(reservation_id: str, actual_tokens: int) -> None:
    conn = _connect()
    try:
        conn.execute(
            """UPDATE quota_reservations SET status='complete', actual_tokens=?
               WHERE id=? AND status='pending'""",
            (max(0, int(actual_tokens)), reservation_id),
        )
    finally:
        conn.close()


def cancel_reservation(reservation_id: str) -> None:
    conn = _connect()
    try:
        conn.execute(
            "UPDATE quota_reservations SET status='cancelled', actual_tokens=0 WHERE id=? AND status='pending'",
            (reservation_id,),
        )
    finally:
        conn.close()


def list_usage_alerts(limit: int = 100) -> list[dict]:
    conn = _connect()
    try:
        rows = conn.execute(
            "SELECT repository,period,metric,threshold,used,quota,created_at FROM usage_alerts ORDER BY id DESC LIMIT ?",
            (max(1, min(int(limit), 500)),),
        ).fetchall()
        return [dict(row) for row in rows]
    finally:
        conn.close()
