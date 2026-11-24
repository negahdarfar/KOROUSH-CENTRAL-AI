import asyncio

import pytest

from app.quota_guard import reserve_inference, cancel_reservation, list_usage_alerts
from app.alert_notifier import dispatch_usage_alerts, _smtp_settings


def setup_smtp(monkeypatch):
    monkeypatch.setenv("SMTP_HOST", "smtp.example.test")
    monkeypatch.setenv("SMTP_FROM", "alerts@example.test")
    monkeypatch.setenv("SMTP_TO", "ops@example.test")
    monkeypatch.setenv("SMTP_USERNAME", "mailer")
    monkeypatch.setenv("SMTP_PASSWORD", "test-password")


def test_alert_dispatch_is_disabled_without_delivery_configuration(tmp_path, monkeypatch):
    monkeypatch.setenv("USAGE_DB_PATH", str(tmp_path / "alerts.sqlite3"))
    for name in ("TELEGRAM_BOT_TOKEN", "TELEGRAM_CHAT_ID", "SMTP_HOST", "SMTP_FROM", "SMTP_TO", "SMTP_USERNAME", "SMTP_PASSWORD"):
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
    assert "\\n" in calls[0]


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


def test_smtp_rejects_authenticated_cleartext_transport(monkeypatch):
    setup_smtp(monkeypatch)
    monkeypatch.setenv("SMTP_USE_TLS", "false")
    assert _smtp_settings() is None
    assert "email" not in __import__("app.alert_notifier", fromlist=["_configured_channels"])._configured_channels()


def test_smtp_accepts_authenticated_starttls(monkeypatch):
    setup_smtp(monkeypatch)
    monkeypatch.setenv("SMTP_USE_TLS", "true")
    config = _smtp_settings()
    assert config is not None
    assert config["use_tls"] is True
    assert config["username"] == "mailer"


@pytest.mark.parametrize("port", ["0", "65536", "not-a-port"])
def test_smtp_rejects_invalid_port(monkeypatch, port):
    setup_smtp(monkeypatch)
    monkeypatch.setenv("SMTP_PORT", port)
    assert _smtp_settings() is None


def test_smtp_rejects_username_without_password(monkeypatch):
    setup_smtp(monkeypatch)
    monkeypatch.delenv("SMTP_PASSWORD", raising=False)
    assert _smtp_settings() is None
