import pytest

from app.model_router import select_avalai_model


def test_router_selects_preferred_model_only_when_present_in_account_catalog():
    catalog = [
        {"id": "gpt-6.1-sol", "mode": "chat"},
        {"id": "claude-opus-5-5", "mode": "chat"},
    ]
    assert select_avalai_model(catalog) == "gpt-6.1-sol"


def test_router_falls_back_to_available_chat_model_not_hardcoded_catalog():
    catalog = [
        {"id": "provider-custom-reasoner", "mode": "reasoning"},
        {"id": "provider-image-gen", "mode": "image"},
    ]
    assert select_avalai_model(catalog) == "provider-custom-reasoner"


def test_router_excludes_non_chat_media_models():
    with pytest.raises(RuntimeError, match="No chat-capable models"):
        select_avalai_model([
            {"id": "image-model", "mode": "image"},
            {"id": "audio-tts", "mode": "audio"},
        ])


def test_coding_route_prefers_coding_model_when_account_has_it():
    catalog = [
        {"id": "general-chat", "mode": "chat"},
        {"id": "gpt-5.3-codex", "mode": "chat"},
    ]
    assert select_avalai_model(catalog, task="coding") == "gpt-5.3-codex"



def test_fast_route_prefers_fast_model_when_account_has_it():
    catalog = [
        {"id": "gpt-6.1-sol", "mode": "chat"},
        {"id": "gpt-6-luna", "mode": "chat"},
        {"id": "claude-haiku-5-5", "mode": "chat"},
    ]
    assert select_avalai_model(catalog, task="fast") == "gpt-6-luna"


def test_observed_runtime_metrics_improve_ranking_within_the_same_cost_class():
    catalog = [
        {"id": "gpt-6.1-sol", "mode": "chat", "pricing": {"input": 0, "output": 0}},
        {"id": "gpt-6-astra", "mode": "chat", "pricing": {"input": 0, "output": 0}},
    ]
    metrics = {
        "avalai:gpt-6.1-sol": {
            "attempts": 5, "success_rate": 0.4, "rate_limit_rate": 0.4, "latency_ewma_ms": 12000,
        },
        "avalai:gpt-6-astra": {
            "attempts": 5, "success_rate": 1.0, "rate_limit_rate": 0.0, "latency_ewma_ms": 250,
        },
    }
    from app.model_router import rank_avalai_models
    ranked = rank_avalai_models(catalog, task="general", free_only=True, performance_metrics=metrics)
    assert ranked[0]["id"] == "gpt-6-astra"
    assert ranked[0]["routing"]["runtime_samples"] == 5
    assert ranked[0]["routing"]["quality_evidence"] == "not_measured"


def test_model_quality_is_only_used_with_explicit_verified_benchmark_evidence():
    from app.model_router import rank_avalai_models
    catalog = [
        {"id": "model-a", "mode": "chat", "pricing": {"input": 0}, "quality_score": 99},
        {"id": "model-b", "mode": "chat", "pricing": {"input": 0}, "quality_score": 50,
         "quality_evidence": "verified_benchmark"},
    ]
    ranked = rank_avalai_models(catalog, free_only=True)
    by_id = {item["id"]: item["routing"] for item in ranked}
    assert by_id["model-a"]["quality_score"] is None
    assert by_id["model-b"]["quality_score"] == 50.0
