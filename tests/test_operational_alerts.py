import asyncio
from app.operational_alerts import dispatch_operational_alerts

def test_worker_alerts_are_deduplicated_per_channel(tmp_path, monkeypatch):
    monkeypatch.setenv("USAGE_DB_PATH", str(tmp_path / "ops.sqlite3"))
    monkeypatch.setattr("app.operational_alerts._configured_channels", lambda: ["telegram"])
    calls = []
    async def fake_send(message): calls.append(message)
    monkeypatch.setattr("app.operational_alerts._send_telegram", fake_send)
    snapshot = {"status": "stale", "heartbeat_age_seconds": 90}
    first = asyncio.run(dispatch_operational_alerts(snapshot))
    second = asyncio.run(dispatch_operational_alerts(snapshot))
    assert first["sent"] == 1
    assert second["sent"] == 0
    assert len(calls) == 1
    assert "stale" in calls[0]

def test_healthy_worker_does_not_send_alert(tmp_path, monkeypatch):
    monkeypatch.setenv("USAGE_DB_PATH", str(tmp_path / "ops.sqlite3"))
    monkeypatch.setattr("app.operational_alerts._configured_channels", lambda: ["telegram"])
    calls = []
    async def fake_send(message): calls.append(message)
    monkeypatch.setattr("app.operational_alerts._send_telegram", fake_send)
    result = asyncio.run(dispatch_operational_alerts({"status": "running", "heartbeat_age_seconds": 2}))
    assert result["sent"] == 0 and calls == []

def test_failed_worker_alert_can_retry(tmp_path, monkeypatch):
    monkeypatch.setenv("USAGE_DB_PATH", str(tmp_path / "ops.sqlite3"))
    monkeypatch.setattr("app.operational_alerts._configured_channels", lambda: ["telegram"])
    attempts = {"n": 0}
    async def fake_send(message):
        attempts["n"] += 1
        if attempts["n"] == 1: raise RuntimeError("temporary")
    monkeypatch.setattr("app.operational_alerts._send_telegram", fake_send)
    snapshot = {"status": "stopped", "heartbeat_age_seconds": 120}
    first = asyncio.run(dispatch_operational_alerts(snapshot))
    second = asyncio.run(dispatch_operational_alerts(snapshot))
    assert first["failed"] == 1 and second["sent"] == 1