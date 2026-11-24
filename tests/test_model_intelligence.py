import pytest

from app.model_intelligence import classify_model


def test_provider_metadata_is_marked_as_verified():
    result = classify_model({
        "id": "provider-model",
        "mode": "chat",
        "supports_vision": True,
        "supports_function_calling": True,
        "details_available": True,
        "pricing": {"input": 0, "output": 0},
        "min_tier": 0,
        "context_length": 128000,
    })
    assert result["categories"] == ["text_chat", "vision", "tool_calling"]
    assert result["evidence"]["vision"] == "provider_metadata"
    assert result["pricing_status"] == "free_pricing_reported"
    assert result["classification_status"] == "provider_metadata_available"


def test_name_hints_are_not_reported_as_verified_capabilities():
    result = classify_model({"id": "custom-coder-vision"})
    assert set(result["categories"]) == {"coding", "vision"}
    assert set(result["evidence"].values()) == {"model_id_hint"}
    assert result["classification_status"] == "partially_inferred"
    assert result["pricing_status"] == "unknown"


def test_nonzero_pricing_is_reported_as_paid_not_free():
    result = classify_model({
        "id": "paid-chat",
        "mode": "chat",
        "details_available": True,
        "pricing": {"prompt": "0.000002", "completion": "0.00001"},
    })
    assert result["pricing_status"] == "paid_pricing_reported"


def test_missing_pricing_and_capabilities_remain_unknown():
    result = classify_model({"id": "opaque-model"})
    assert result["categories"] == []
    assert result["pricing_status"] == "unknown"
