import asyncio

import pytest
from fastapi import HTTPException

from app import main


def test_avalai_models_uses_lightweight_catalog_only(monkeypatch):
    async def lightweight_catalog():
        return [{"id": "chat-model", "owned_by": "provider", "mode": None}]

    async def heavy_enrichment_must_not_run():
        raise AssertionError("per-model metadata fan-out must not run")

    monkeypatch.setattr(main.settings, "admin_api_key", "test-secret")
    monkeypatch.setattr(main, "list_avalai_model_catalog", lightweight_catalog)
    monkeypatch.setattr(main, "list_avalai_models", heavy_enrichment_must_not_run)

    result = asyncio.run(main.avalai_models("test-secret"))

    assert result == {
        "provider": "avalai",
        "count": 1,
        "models": [{"id": "chat-model", "owned_by": "provider", "mode": None}],
    }


def test_avalai_models_returns_gateway_timeout(monkeypatch):
    async def timed_out_catalog():
        raise asyncio.TimeoutError

    monkeypatch.setattr(main.settings, "admin_api_key", "test-secret")
    monkeypatch.setattr(main, "list_avalai_model_catalog", timed_out_catalog)

    with pytest.raises(HTTPException) as exc:
        asyncio.run(main.avalai_models("test-secret"))

    assert exc.value.status_code == 504
