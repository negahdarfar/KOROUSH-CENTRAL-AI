from app.operational_health import _database_probe, readiness


def test_database_probe_is_writable_but_does_not_claim_persistence(tmp_path, monkeypatch):
    monkeypatch.setenv("USAGE_DB_PATH", str(tmp_path / "readiness.sqlite3"))
    monkeypatch.setattr("app.operational_health._mounted_at_data", lambda: False)
    result = _database_probe()
    assert result["status"] == "ok"
    assert result["write_probe"] == "ok"
    assert result["persistence"] == "not_verified"
    assert str(tmp_path) not in str(result)


def test_readiness_reports_missing_inference_configuration_without_secrets(tmp_path, monkeypatch):
    monkeypatch.setenv("USAGE_DB_PATH", str(tmp_path / "readiness.sqlite3"))
    monkeypatch.delenv("ALLOWED_REPOS", raising=False)
    monkeypatch.delenv("TENANT_AUTH_PEPPER", raising=False)
    monkeypatch.setenv("LLM_PROVIDER", "legacy")
    result = __import__("asyncio").run(readiness())
    assert result["status"] == "ready"
    assert result["components"]["operator_allowlist"] == "missing_inference_blocked"
    assert result["components"]["tenant_auth"] == "disabled_missing_pepper"
    assert result["components"]["inference"] == "blocked_or_not_configured"
    assert "TENANT_AUTH_PEPPER" not in str(result)
    assert str(tmp_path) not in str(result)
