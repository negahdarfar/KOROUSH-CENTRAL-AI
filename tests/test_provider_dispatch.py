import asyncio

import httpx
import pytest

from app.provider_dispatch import dispatch_chat_completion, verified_candidates


def _config(provider, model):
    return {"provider": provider, "model": model, "base_url": f"https://{provider}.example/v1", "api_key": "test-secret"}


def test_verified_candidates_require_exact_provider_and_model_evidence():
    configs = [_config("avalai", "free-a"), _config("openrouter", "free-b")]
    result = verified_candidates(configs, {"avalai": {"free-a"}})
    assert [(item["provider"], item["model"]) for item in result] == [("avalai", "free-a")]


def test_requested_model_cannot_select_unverified_provider_model():
    configs = [_config("openrouter", "model-x")]
    assert verified_candidates(configs, {"avalai": {"model-x"}}, requested_model="model-x") == []


class FakeResponse:
    def __init__(self, status_code, body=None):
        self.status_code = status_code
        self._body = body or {}
        self.headers = {"x-request-id": "req-test"}

    def raise_for_status(self):
        if self.status_code >= 400:
            request = httpx.Request("POST", "https://provider.example/v1/chat/completions")
            response = httpx.Response(self.status_code, request=request)
            raise httpx.HTTPStatusError("upstream error", request=request, response=response)

    def json(self):
        return self._body


class FakeClient:
    responses = []
    calls = []

    def __init__(self, timeout):
        self.timeout = timeout

    async def __aenter__(self):
        return self

    async def __aexit__(self, *args):
        return False

    async def post(self, url, headers, json):
        self.calls.append((url, headers, json))
        return self.responses.pop(0)


def test_dispatch_fails_over_only_after_retryable_status(monkeypatch):
    FakeClient.responses = [
        FakeResponse(503),
        FakeResponse(200, {"choices": [{"message": {"content": "ok"}}], "usage": {}}),
    ]
    FakeClient.calls = []
    monkeypatch.setattr("app.provider_dispatch.httpx.AsyncClient", FakeClient)
    candidates = [_config("avalai", "free-a"), _config("openrouter", "free-b")]
    result = asyncio.run(dispatch_chat_completion(candidates, {"messages": []}))
    assert result[2:] == ("openrouter", "free-b")
    assert len(FakeClient.calls) == 2
    assert FakeClient.calls[1][2]["model"] == "free-b"


def test_dispatch_does_not_retry_non_retryable_client_errors(monkeypatch):
    FakeClient.responses = [FakeResponse(400)]
    FakeClient.calls = []
    monkeypatch.setattr("app.provider_dispatch.httpx.AsyncClient", FakeClient)
    candidates = [_config("avalai", "free-a"), _config("openrouter", "free-b")]
    with pytest.raises(httpx.HTTPStatusError):
        asyncio.run(dispatch_chat_completion(candidates, {"messages": []}))
    assert len(FakeClient.calls) == 1


def test_dispatch_fails_closed_without_verified_candidates():
    with pytest.raises(RuntimeError, match="trusted exact zero-price evidence"):
        asyncio.run(dispatch_chat_completion([], {"messages": []}))
