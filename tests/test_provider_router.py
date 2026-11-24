import pytest

from app.provider_router import configured_chat_providers, verified_free_chat_providers


def test_cost_class_free_environment_variable_is_not_pricing_evidence(monkeypatch):
    monkeypatch.setenv("OPENROUTER_API_KEY", "secret")
    monkeypatch.setenv("OPENROUTER_MODEL", "claimed-free")
    monkeypatch.setenv("OPENROUTER_COST_CLASS", "free")
    active = {"provider": "avalai", "base_url": "https://avalai.test/v1",
              "api_key": "avalai-secret", "model": "avalai-free"}
    providers = verified_free_chat_providers(
        active, provider_order=["openrouter", "avalai"],
        verified_free_models={"avalai": {"avalai-free"}},
    )
    assert [p["provider"] for p in providers] == ["avalai"]


def test_non_avalai_provider_requires_exact_verified_model_evidence(monkeypatch):
    monkeypatch.setenv("OPENROUTER_API_KEY", "secret")
    monkeypatch.setenv("OPENROUTER_MODEL", "verified-model")
    monkeypatch.setenv("OPENROUTER_COST_CLASS", "free")
    active = {"provider": "avalai", "base_url": "https://avalai.test/v1",
              "api_key": "avalai-secret", "model": "avalai-free"}
    without_evidence = verified_free_chat_providers(
        active, provider_order=["openrouter"],
        verified_free_models={"avalai": {"avalai-free"}},
    )
    with_evidence = verified_free_chat_providers(
        active, provider_order=["openrouter"],
        verified_free_models={"openrouter": {"verified-model"}},
    )
    assert without_evidence == []
    assert [p["model"] for p in with_evidence] == ["verified-model"]


def test_provider_adapter_configuration_does_not_expose_secret_in_metadata(monkeypatch):
    monkeypatch.setenv("GEMINI_API_KEY", "do-not-leak")
    monkeypatch.setenv("GEMINI_MODEL", "gemini-model")
    providers = configured_chat_providers(
        {"provider": "avalai", "base_url": "https://avalai.test/v1",
         "api_key": "avalai-secret", "model": "avalai-model"},
        ["gemini"],
    )
    assert providers[0]["provider"] == "gemini"
    assert providers[0]["api_key"] == "do-not-leak"  # used internally for requests only
