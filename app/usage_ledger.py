"""SQLite-backed, repository-scoped inference usage ledger.

For durable Railway storage, mount a Railway Volume at /data and keep
USAGE_DB_PATH=/data/koroush_usage.sqlite3. Without a mounted volume, the
ledger is best-effort and may be lost when the container is replaced.
"""
from __future__ import annotations

import os
import sqlite3
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


def _db_path() -> Path:
    return Path(os.getenv("USAGE_DB_PATH", "/data/koroush_usage.sqlite3"))


def _connect() -> sqlite3.Connection:
    path = _db_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    connection = sqlite3.connect(str(path), timeout=10)
    connection.row_factory = sqlite3.Row
    connection.execute("PRAGMA busy_timeout=10000")
    connection.execute("PRAGMA journal_mode=WAL")
    connection.execute("""
        CREATE TABLE IF NOT EXISTS inference_usage (
            id TEXT PRIMARY KEY,
            created_at TEXT NOT NULL,
            repository TEXT NOT NULL,
            provider TEXT NOT NULL,
            model TEXT NOT NULL,
            surface TEXT NOT NULL,
            provider_request_id TEXT,
            prompt_tokens INTEGER NOT NULL DEFAULT 0,
            completion_tokens INTEGER NOT NULL DEFAULT 0,
            total_tokens INTEGER NOT NULL DEFAULT 0,
            estimated_cost_usd REAL NOT NULL DEFAULT 0.0,
            pricing_evidence TEXT NOT NULL DEFAULT 'catalog_confirmed_free'
        )
    """)
    connection.execute("""
        CREATE UNIQUE INDEX IF NOT EXISTS uq_usage_provider_request
        ON inference_usage(provider, provider_request_id)
        WHERE provider_request_id IS NOT NULL
    """)
    connection.execute("CREATE INDEX IF NOT EXISTS ix_usage_repo_time ON inference_usage(repository, created_at)")
    connection.commit()
    return connection


def _nonnegative_int(value: Any) -> int:
    try:
        return max(0, int(value))
    except (TypeError, ValueError, OverflowError):
        return 0


def normalize_usage(usage: Any) -> tuple[int, int, int]:
    """Normalize common OpenAI-compatible usage field names."""
    if not isinstance(usage, dict):
        return 0, 0, 0
    prompt = _nonnegative_int(usage.get("prompt_tokens", usage.get("input_tokens", 0)))
    completion = _nonnegative_int(usage.get("completion_tokens", usage.get("output_tokens", 0)))
    total = _nonnegative_int(usage.get("total_tokens", prompt + completion))
    if total == 0 and (prompt or completion):
        total = prompt + completion
    return prompt, completion, total


def record_usage(
    *,
    repository: str | None,
    provider: str,
    model: str,
    surface: str,
    usage: Any,
    provider_request_id: str | None = None,
) -> bool:
    """Persist one successful inference; return False for a duplicate provider request ID."""
    prompt, completion, total = normalize_usage(usage)
    repo = (repository or "__unassigned__").strip().lower()[:255] or "__unassigned__"
    request_id = provider_request_id.strip()[:255] if isinstance(provider_request_id, str) and provider_request_id.strip() else None
    connection = _connect()
    try:
        cursor = connection.execute(
            """INSERT OR IGNORE INTO inference_usage
            (id, created_at, repository, provider, model, surface, provider_request_id,
             prompt_tokens, completion_tokens, total_tokens, estimated_cost_usd, pricing_evidence)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 0.0, 'catalog_confirmed_free')""",
            (str(uuid.uuid4()), datetime.now(timezone.utc).isoformat(), repo,
             str(provider)[:80], str(model)[:200], str(surface)[:80], request_id,
             prompt, completion, total),
        )
        connection.commit()
        return cursor.rowcount == 1
    finally:
        connection.close()


def usage_summary(repository: str | None = None) -> dict:
    """Return all-time, daily and monthly token totals without exposing request payloads."""
    connection = _connect()
    try:
        where = " WHERE repository = ?" if repository else ""
        params = (repository.strip().lower(),) if repository else ()
        totals = connection.execute(
            f"""SELECT repository, COUNT(*) AS requests, SUM(prompt_tokens) AS prompt_tokens,
            SUM(completion_tokens) AS completion_tokens, SUM(total_tokens) AS total_tokens,
            SUM(estimated_cost_usd) AS estimated_cost_usd
            FROM inference_usage{where} GROUP BY repository ORDER BY repository""", params
        ).fetchall()
        daily = connection.execute(
            f"""SELECT repository, substr(created_at,1,10) AS period, COUNT(*) AS requests,
            SUM(total_tokens) AS total_tokens FROM inference_usage{where}
            GROUP BY repository, period ORDER BY period DESC, repository""", params
        ).fetchall()
        monthly = connection.execute(
            f"""SELECT repository, substr(created_at,1,7) AS period, COUNT(*) AS requests,
            SUM(total_tokens) AS total_tokens FROM inference_usage{where}
            GROUP BY repository, period ORDER BY period DESC, repository""", params
        ).fetchall()
        return {
            "storage_path": str(_db_path()),
            "durability": "requires_railway_volume_mounted_at_parent_path",
            "repositories": [dict(row) for row in totals],
            "daily": [dict(row) for row in daily],
            "monthly": [dict(row) for row in monthly],
            "notes": [
                "Only successful inference responses are recorded.",
                "Token totals are zero when the provider omits usage metadata; they are not estimated.",
                "Estimated cost is recorded as USD 0.00 only after the global catalog-confirmed-free model gate.",
                "Without a mounted persistent volume, records may be lost on container replacement.",
                "Requests without a repository are isolated under __unassigned__."
            ],
        }
    finally:
        connection.close()
