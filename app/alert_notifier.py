"""Automatic Telegram/email delivery for deduplicated quota alerts.

Delivery is best-effort with a SQLite idempotency ledger. Credentials are read
only from environment variables and are never returned by API endpoints.
"""
from __future__ import annotations

import asyncio
import logging
import os
import smtplib
import sqlite3
from email.message import EmailMessage
from typing import Any

import httpx

from .quota_guard import _db_path, list_usage_alerts

logger = logging.getLogger(__name__)


def _connect() -> sqlite3.Connection:
    path = _db_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(path), timeout=10)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA busy_timeout=10000")
    conn.execute("""
        CREATE TABLE IF NOT EXISTS usage_alert_deliveries (
            alert_id INTEGER NOT NULL,
            channel TEXT NOT NULL,
            status TEXT NOT NULL,
            attempts INTEGER NOT NULL DEFAULT 0,
            updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
            last_error TEXT,
            PRIMARY KEY(alert_id, channel)
        )
    """)
    conn.commit()
    return conn


def _smtp_settings() -> dict[str, Any] | None:
    """Return validated SMTP settings; never send authenticated SMTP in cleartext."""
    required = ("SMTP_HOST", "SMTP_FROM", "SMTP_TO")
    if not all(os.getenv(name, "").strip() for name in required):
        return None
    try:
        port = int(os.getenv("SMTP_PORT", "587"))
    except ValueError:
        return None
    if not 1 <= port <= 65535:
        return None
    username = os.getenv("SMTP_USERNAME", "")
    password = os.getenv("SMTP_PASSWORD", "")
    use_tls = os.getenv("SMTP_USE_TLS", "true").strip().lower() not in {"0", "false", "no"}
    if username and (not password or not use_tls):
        return None
    if password and not username:
        return None
    return {
        "host": os.environ["SMTP_HOST"].strip(),
        "port": port,
        "sender": os.environ["SMTP_FROM"].strip(),
        "recipient": os.environ["SMTP_TO"].strip(),
        "username": username,
        "password": password,
        "use_tls": use_tls,
    }


def _configured_channels() -> list[str]:
    channels = []
    if os.getenv("TELEGRAM_BOT_TOKEN") and os.getenv("TELEGRAM_CHAT_ID"):
        channels.append("telegram")
    if _smtp_settings() is not None:
        channels.append("email")
    return channels


def _claim(alert_id: int, channel: str) -> bool:
    conn = _connect()
    try:
        conn.execute("BEGIN IMMEDIATE")
        row = conn.execute(
            "SELECT status,updated_at FROM usage_alert_deliveries WHERE alert_id=? AND channel=?",
            (alert_id, channel),
        ).fetchone()
        if row and row["status"] == "sent":
            conn.commit()
            return False
        if row and row["status"] == "sending":
            age = conn.execute(
                "SELECT (julianday('now')-julianday(?))*86400 AS seconds",
                (row["updated_at"],),
            ).fetchone()["seconds"]
            if age is not None and age < 600:
                conn.commit()
                return False
        conn.execute(
            """INSERT INTO usage_alert_deliveries(alert_id,channel,status,attempts,updated_at,last_error)
               VALUES(?,?, 'sending',1,CURRENT_TIMESTAMP,NULL)
               ON CONFLICT(alert_id,channel) DO UPDATE SET
               status='sending', attempts=attempts+1, updated_at=CURRENT_TIMESTAMP,last_error=NULL""",
            (alert_id, channel),
        )
        conn.commit()
        return True
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def _finish(alert_id: int, channel: str, *, success: bool) -> None:
    conn = _connect()
    try:
        conn.execute(
            "UPDATE usage_alert_deliveries SET status=?,updated_at=CURRENT_TIMESTAMP,last_error=? WHERE alert_id=? AND channel=?",
            ("sent" if success else "failed", None if success else "delivery_failed", alert_id, channel),
        )
        conn.commit()
    finally:
        conn.close()


def _message(alert: dict[str, Any]) -> str:
    return (
        "KOROUSH CENTRAL AI — Usage alert\\n"
        f"Repository: {alert['repository']}\\n"
        f"Metric: {alert['metric']}\\n"
        f"Threshold: {alert['threshold']}%\\n"
        f"Usage: {alert['used']} / {alert['quota']}\\n"
        f"Period: {alert['period']}\\n"
        f"Created: {alert['created_at']}"
    )


async def _send_telegram(message: str) -> None:
    token = os.environ["TELEGRAM_BOT_TOKEN"]
    chat_id = os.environ["TELEGRAM_CHAT_ID"]
    url = f"https://api.telegram.org/bot{token}/sendMessage"
    async with httpx.AsyncClient(timeout=httpx.Timeout(12.0, connect=5.0)) as client:
        response = await client.post(url, json={"chat_id": chat_id, "text": message, "disable_web_page_preview": True})
        response.raise_for_status()
        body = response.json()
        if not body.get("ok"):
            raise RuntimeError("Telegram rejected the notification")


def _send_email_sync(subject: str, body: str) -> None:
    config = _smtp_settings()
    if config is None:
        raise RuntimeError("SMTP settings are incomplete or unsafe; authenticated SMTP requires STARTTLS")
    message = EmailMessage()
    message["Subject"] = subject
    message["From"] = config["sender"]
    message["To"] = config["recipient"]
    message.set_content(body)
    with smtplib.SMTP(config["host"], config["port"], timeout=15) as server:
        if config["use_tls"]:
            server.starttls()
        if config["username"]:
            server.login(config["username"], config["password"])
        server.send_message(message)


async def dispatch_usage_alerts(limit: int = 100) -> dict[str, Any]:
    channels = _configured_channels()
    if not channels:
        return {"configured_channels": [], "sent": 0, "failed": 0, "skipped": "No safe Telegram or SMTP delivery settings are configured"}
    alerts = list_usage_alerts(limit=limit)
    sent = failed = skipped = 0
    for alert in reversed(alerts):
        for channel in channels:
            if not _claim(int(alert["id"]), channel):
                skipped += 1
                continue
            try:
                body = _message(alert)
                if channel == "telegram":
                    await _send_telegram(body)
                else:
                    await asyncio.to_thread(_send_email_sync, "KOROUSH CENTRAL AI usage alert", body)
                _finish(int(alert["id"]), channel, success=True)
                sent += 1
            except Exception:
                logger.warning("Quota alert delivery failed for channel %s and alert %s", channel, alert["id"])
                _finish(int(alert["id"]), channel, success=False)
                failed += 1
    return {"configured_channels": channels, "sent": sent, "failed": failed, "skipped": skipped}


async def run_alert_worker() -> None:
    """Poll the durable alert table; failures are retried on a later cycle."""
    try:
        interval = max(15, min(int(os.getenv("ALERT_POLL_SECONDS", "60")), 3600))
    except ValueError:
        interval = 60
    while True:
        try:
            if _configured_channels():
                await dispatch_usage_alerts(limit=100)
        except asyncio.CancelledError:
            raise
        except Exception:
            logger.exception("Quota alert worker cycle failed")
        await asyncio.sleep(interval)
