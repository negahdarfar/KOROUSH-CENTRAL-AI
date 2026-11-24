from app.config import Settings


def test_avalai_provider_uses_avalai_credentials_and_endpoint():
    config = Settings(
        llm_provider="avalai",
        avalai_api_key="avalai-test-key",
        avalai_model="model-from-catalog",
    )
    assert config.active_llm == {
        "provider": "avalai",
        "base_url": "https://api.avalai.ir/v1",
        "api_key": "avalai-test-key",
        "model": "model-from-catalog",
    }


def test_legacy_provider_remains_default_and_unchanged():
    config = Settings(
        llm_base_url="https://legacy.example/v1",
        llm_api_key="legacy-test-key",
        llm_model="legacy-model",
    )
    assert config.active_llm == {
        "provider": "legacy",
        "base_url": "https://legacy.example/v1",
        "api_key": "legacy-test-key",
        "model": "legacy-model",
    }


def test_unknown_provider_fails_closed():
    config = Settings(llm_provider="unknown")
    assert config.active_llm == {
        "provider": "unknown",
        "base_url": "",
        "api_key": "",
        "model": "",
    }
