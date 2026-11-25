"""Persistent, bounded model telemetry used for evidence-based routing.

Only latency and provider outcomes are recorded. This module does not claim
that latency or success rate is a benchmark of answer quality.
"""
from __future__ import annotations

import sqlite3
from datetime import datetime, timezone

from .quota_guard import _db_path


def _connect() -> sqlite3.Connection:
    path = _db_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(path), timeout=10)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA busy_timeout=10000")
    conn.execute(
        """CREATE TABLE IF NOT EXISTS model_runtime_metrics (
            provider TEXT NOT NULL,
            model TEXT NOT NULL,
            attempts INTEGER NOT NULL DEFAULT 0,
            successes INTEGER NOT NULL DEFAULT 0,
            rate_limits INTEGER NOT NULL DEFAULT 0,
            latency_ewma_ms REAL,
            last_status INTEGER,
            updated_at TEXT NOT NULL,
            PRIMARY KEY(provider, model)
        )"""
    )
    conn.commit()
    return conn


def record_model_attempt(provider: str, model: str, *, latency_ms: float,
                         success: bool, status_code: int | None = None) -> None:
    """Atomically update EWMA latency and reliability counters."""
    provider = str(provider or "").strip().lower()
    model = str(model or "").strip()
    if not provider or not model or len(provider) > 40 or len(model) > 200:
        return
    if isinstance(latency_ms, bool) or not isinstance(latency_ms, (int, float)) or latency_ms < 0:
        return
    stamp = datetime.now(timezone.utc).isoformat()
    conn = _connect()
    try:
        conn.execute("BEGIN IMMEDIATE")
        row = conn.execute(
            "SELECT attempts,latency_ewma_ms FROM model_runtime_metrics WHERE provider=? AND model=?",
            (provider, model),
        ).fetchone()
        attempts = int(row["attempts"]) if row else 0
        previous = row["latency_ewma_ms"] if row else None
        latency = float(latency_ms) if previous is None else (0.3 * float(latency_ms) + 0.7 * float(previous))
        conn.execute(
            """INSERT INTO model_runtime_metrics
               (provider,model,attempts,successes,rate_limits,latency_ewma_ms,last_status,updated_at)
               VALUES(?,?,?,?,?,?,?,?)
               ON CONFLICT(provider,model) DO UPDATE SET
                 attempts=attempts+1,
                 successes=successes+excluded.successes,
                 rate_limits=rate_limits+excluded.rate_limits,
                 latency_ewma_ms=excluded.latency_ewma_ms,
                 last_status=excluded.last_status,
                 updated_at=excluded.updated_at""",
            (provider, model, 1, int(bool(success)), int(status_code == 429),
             latency, status_code, stamp),
        )
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def get_model_metrics(provider: str | None = None) -> dict[str, dict]:
    """Return aggregated observations; callers must respect the sample count."""
    conn = _connect()
    try:
        if provider:
            rows = conn.execute(
                "SELECT * FROM model_runtime_metrics WHERE provider=?",
                (provider.strip().lower(),),
            ).fetchall()
        else:
            rows = conn.execute("SELECT * FROM model_runtime_metrics").fetchall()
        result = {}
        for row in rows:
            attempts = int(row["attempts"])
            result[f'{row["provider"]}:{row["model"]}'] = {
                "attempts": attempts,
                "success_rate": (int(row["successes"]) / attempts) if attempts else None,
                "rate_limit_rate": (int(row["rate_limits"]) / attempts) if attempts else None,
                "latency_ewma_ms": row["latency_ewma_ms"],
                "last_status": row["last_status"],
                "updated_at": row["updated_at"],
            }
        return result
    finally:
        conn.close()
