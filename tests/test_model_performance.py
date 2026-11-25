from app import model_performance


def test_runtime_metrics_track_ewma_reliability_and_rate_limits(monkeypatch, tmp_path):
    database = tmp_path / "metrics.sqlite3"
    monkeypatch.setattr(model_performance, "_db_path", lambda: database)

    model_performance.record_model_attempt("avalai", "free-model", latency_ms=100, success=True, status_code=200)
    model_performance.record_model_attempt("avalai", "free-model", latency_ms=200, success=False, status_code=429)

    metrics = model_performance.get_model_metrics("avalai")["avalai:free-model"]
    assert metrics["attempts"] == 2
    assert metrics["success_rate"] == 0.5
    assert metrics["rate_limit_rate"] == 0.5
    assert metrics["latency_ewma_ms"] == 130
