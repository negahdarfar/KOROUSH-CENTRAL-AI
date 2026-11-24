import asyncio

from app import main


def test_inspection_endpoint_classifies_metadata_and_requires_admin(monkeypatch):
    async def fake_inspect(model_ids):
        return [{
            "id": model_ids[0],
            "mode": "chat",
            "supports_vision": True,
            "details_available": True,
            "status": "ok",
            "pricing": {"input": 0, "output": 0},
        }]

    monkeypatch.setattr(main.settings, "admin_api_key", "test-secret")
    monkeypatch.setattr(main, "inspect_avalai_models", fake_inspect)
    request = main.AvalAIModelInspectRequest(model_ids=["verified-model"])

    result = asyncio.run(main.avalai_models_inspect(request, "test-secret"))

    assert result["requested"] == 1
    assert result["inspected"] == 1
    assert result["models"][0]["categories"] == ["text_chat", "vision"]
    assert result["models"][0]["pricing_status"] == "free_pricing_reported"


def test_inspection_endpoint_rejects_missing_admin_key(monkeypatch):
    monkeypatch.setattr(main.settings, "admin_api_key", "test-secret")
    request = main.AvalAIModelInspectRequest(model_ids=["model"])
    try:
        asyncio.run(main.avalai_models_inspect(request, None))
    except Exception as exc:
        assert getattr(exc, "status_code", None) == 401
    else:
        raise AssertionError("missing admin key must be rejected")
