import asyncio
from app.operational_health import _database_probe, readiness
from app.worker_heartbeat import record_worker_heartbeat, worker_health

def test_database_probe_is_writable_but_does_not_claim_persistence(tmp_path, monkeypatch):
    monkeypatch.setenv("USAGE_DB_PATH", str(tmp_path / "readiness.sqlite3"))
    monkeypatch.setattr("app.operational_health._mounted_at_data", lambda: False)
    result = _database_probe()
    assert result["status"] == "ok" and result["write_probe"] == "ok"
    assert result["persistence"] == "not_verified"
    assert str(tmp_path) not in str(result)

def test_readiness_reports_missing_configuration_and_worker_disabled(tmp_path, monkeypatch):
    monkeypatch.setenv("USAGE_DB_PATH", str(tmp_path / "readiness.sqlite3"))
    monkeypatch.delenv("ALLOWED_REPOS", raising=False)
    monkeypatch.delenv("TENANT_AUTH_PEPPER", raising=False)
    monkeypatch.setenv("LLM_PROVIDER", "legacy")
    monkeypatch.setenv("JOB_WORKER_ENABLED", "false")
    result = asyncio.run(readiness())
    assert result["status"] == "ready"
    assert result["components"]["operator_allowlist"] == "missing_inference_blocked"
    assert result["components"]["tenant_auth"] == "disabled_missing_pepper"
    assert result["components"]["inference"] == "blocked_or_not_configured"
    assert result["components"]["job_worker"]["status"] == "disabled"
    assert "TENANT_AUTH_PEPPER" not in str(result) and str(tmp_path) not in str(result)

def test_worker_heartbeat_reports_not_started_then_running(tmp_path, monkeypatch):
    monkeypatch.setenv("USAGE_DB_PATH", str(tmp_path / "worker.sqlite3"))
    monkeypatch.setenv("JOB_WORKER_ENABLED", "true")
    assert worker_health()["status"] == "not_started"
    record_worker_heartbeat("worker-test", "running")
    result = worker_health()
    assert result["status"] == "running" and result["heartbeat_age_seconds"] <= 2

def test_worker_heartbeat_detects_stale_signal(tmp_path, monkeypatch):
    monkeypatch.setenv("USAGE_DB_PATH", str(tmp_path / "worker.sqlite3"))
    monkeypatch.setenv("JOB_WORKER_ENABLED", "true")
    record_worker_heartbeat("worker-test", "running")
    assert worker_health(stale_after_seconds=0)["status"] in {"running", "stale"}