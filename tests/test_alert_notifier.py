import asyncio

import pytest

from app.quota_guard import reserve_inference, cancel_reservation, list_usage_alerts
from app.alert_notifier import dispatch_usage_alerts


def test_alert_dispatch_is_disabled_without_delivery_configuration(tmp_path, monkeypatch):
    monkeypatch.setenv("USAGE_DB_PATH", str(tmp_path / "alerts.sqlite3"))
    for name in ("TELEGRAM_BOT_TOKEN", "TELEGRAM_CHAT_ID", "SMTP_HOST", "SMTP_FROM", "SMTP_TO"):
        monkeypatch.delenv(name, raising=False)
    result = asyncio.run(dispatch_usage_alerts())
    assert result["sent"] == 0
    assert result["configured_channels"] == []


def test_telegram_delivery_is_idempotent(tmp_path, monkeypatch):
    monkeypatch.setenv("USAGE_DB_PATH", str(tmp_path / "alerts.sqlite3"))
    monkeypatch.setenv("KOROUSH_REPO_QUOTAS", '{"org/repo":{"requests_per_day":1,"requests_per_month":10,"tokens_per_day":1000,"tokens_per_month":10000}}')
    monkeypatch.setenv("TELEGRAM_BOT_TOKEN", "test-token")
    monkeypatch.setenv("TELEGRAM_CHAT_ID", "123")
    reservation = reserve_inference("org/repo", {"input": "x"})
    cancel_reservation(reservation)
    alerts = list_usage_alerts()
    assert alerts
    calls = []

    async def fake_send(message):
        calls.append(message)

    monkeypatch.setattr("app.alert_notifier._send_telegram", fake_send)
    first = asyncio.run(dispatch_usage_alerts())
    second = asyncio.run(dispatch_usage_alerts())
    assert first["sent"] >= 1
    assert second["sent"] == 0
    assert calls


def test_failed_notification_can_be_retried(tmp_path, monkeypatch):
    monkeypatch.setenv("USAGE_DB_PATH", str(tmp_path / "alerts.sqlite3"))
    monkeypatch.setenv("KOROUSH_REPO_QUOTAS", '{"org/repo":{"requests_per_day":1,"requests_per_month":10,"tokens_per_day":1000,"tokens_per_month":10000}}')
    monkeypatch.setenv("TELEGRAM_BOT_TOKEN", "test-token")
    monkeypatch.setenv("TELEGRAM_CHAT_ID", "123")
    reservation = reserve_inference("org/repo", {"input": "x"})
    cancel_reservation(reservation)
    attempts = {"count": 0}

    async def fake_send(message):
        attempts["count"] += 1
        if attempts["count"] == 1:
            raise RuntimeError("temporary failure")

    monkeypatch.setattr("app.alert_notifier._send_telegram", fake_send)
    first = asyncio.run(dispatch_usage_alerts())
    second = asyncio.run(dispatch_usage_alerts())
    assert first["failed"] >= 1
    assert second["sent"] >= 1
