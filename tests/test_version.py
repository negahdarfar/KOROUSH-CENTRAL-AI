from app.version import runtime_version


def test_runtime_version_reads_railway_commit_metadata(monkeypatch):
    monkeypatch.setenv("RAILWAY_GIT_COMMIT_SHA", "a" * 40)
    monkeypatch.setenv("RAILWAY_DEPLOYMENT_ID", "deployment-123")
    monkeypatch.setenv("RAILWAY_SERVICE_NAME", "koroush-central-ai")
    monkeypatch.setenv("RAILWAY_ENVIRONMENT_NAME", "production")
    monkeypatch.setenv("RAILWAY_GIT_BRANCH", "main")

    result = runtime_version()

    assert result["status"] == "identified"
    assert result["commit_sha"] == "a" * 40
    assert result["commit_short"] == "a" * 12
    assert result["deployment_id"] == "deployment-123"
    assert result["environment"] == "production"
    assert result["branch"] == "main"


def test_runtime_version_reports_unknown_without_platform_sha(monkeypatch):
    for name in ("RAILWAY_GIT_COMMIT_SHA", "GIT_COMMIT_SHA", "RAILWAY_DEPLOYMENT_ID",
                 "RAILWAY_SERVICE_NAME", "RAILWAY_ENVIRONMENT_NAME", "RAILWAY_GIT_BRANCH"):
        monkeypatch.delenv(name, raising=False)

    result = runtime_version()

    assert result["status"] == "unknown"
    assert result["commit_sha"] is None
    assert result["source"] == "platform_metadata_unavailable"
