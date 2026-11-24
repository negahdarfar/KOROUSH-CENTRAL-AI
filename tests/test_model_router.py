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
