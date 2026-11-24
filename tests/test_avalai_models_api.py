import asyncio

import pytest
from fastapi import HTTPException

from app import main


@pytest.mark.asyncio
async def test_avalai_models_uses_lightweight_catalog_only(monkeypatch):
    async def lightweight_catalog():
        return [{"id": "chat-model", "owned_by": "provider", "mode": None}]

    async def heavy_enrichment_must_not_run():
        raise AssertionError("per-model metadata fan-out must not run")

    monkeypatch.setattr(main.settings, "admin_api_key", "test-secret")
    monkeypatch.setattr(main, "list_avalai_model_catalog", lightweight_catalog)
    monkeypatch.setattr(main, "list_avalai_models", heavy_enrichment_must_not_run)

    result = await main.avalai_models("test-secret")

    assert result == {
        "provider": "avalai",
        "count": 1,
        "models": [{"id": "chat-model", "owned_by": "provider", "mode": None}],
    }


@pytest.mark.asyncio
async def test_avalai_models_returns_gateway_timeout(monkeypatch):
    async def slow_catalog():
        await asyncio.sleep(0.05)
        return []

    monkeypatch.setattr(main.settings, "admin_api_key", "test-secret")
    monkeypatch.setattr(main, "list_avalai_model_catalog", slow_catalog)

    monkeypatch.setattr(main.asyncio, "wait_for", lambda awaitable, timeout: _raise_timeout(awaitable))

    with pytest.raises(HTTPException) as exc:
        await main.avalai_models("test-secret")

    assert exc.value.status_code == 504


async def _raise_timeout(awaitable):
    if hasattr(awaitable, "close"):
        awaitable.close()
    raise asyncio.TimeoutError
