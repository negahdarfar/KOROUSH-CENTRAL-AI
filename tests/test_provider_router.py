import httpx
import pytest

from app.provider_router import (
    _eligible,
    _is_transient_error,
    chat_completion,
    configured_chat_providers,
)


def test_configured_providers_are_ordered_and_credentials_are_not_exposed(monkeypatch):
    monkeypatch.setenv("OPENROUTER_API_KEY", "test-secret")
    monkeypatch.setenv("OPENROUTER_MODEL", "free-model")
    monkeypatch.setenv("OPENROUTER_COST_CLASS", "free")
    active = {
        "provider": "avalai",
        "base_url": "https://api.avalai.ir/v1",
        "api_key": "avalai-secret",
        "model": "catalog-model",
    }
    providers = configured_chat_providers(active, ["openrouter", "avalai"])
    assert [item["provider"] for item in providers] == ["openrouter", "avalai"]
    assert providers[0]["cost_class"] == "free"
    assert providers[1]["model"] == "catalog-model"
    assert all("api_key" in item for item in providers)


def test_unknown_cost_fallback_requires_explicit_opt_in(monkeypatch):
    provider = {"provider": "gemini", "cost_class": "unknown"}
    policy = {
        "provider_order": ["gemini"],
        "allow_unknown_cost": True,
        "allow_paid": False,
        "free_only": False,
    }
    monkeypatch.delenv("KOROUSH_ALLOW_UNKNOWN_PROVIDER_FALLBACK", raising=False)
    assert not _eligible(provider, policy, is_primary=False)
    monkeypatch.setenv("KOROUSH_ALLOW_UNKNOWN_PROVIDER_FALLBACK", "true")
    assert _eligible(provider, policy, is_primary=False)


def test_paid_fallback_requires_workflow_paid_permission():
    provider = {"provider": "openrouter", "cost_class": "paid"}
    policy = {
        "provider_order": ["openrouter"],
        "allow_unknown_cost": True,
        "allow_paid": False,
        "free_only": False,
    }
    assert not _eligible(provider, policy, is_primary=False)
    policy["allow_paid"] = True
    assert _eligible(provider, policy, is_primary=False)


def test_free_only_accepts_only_explicitly_free_provider():
    policy = {
        "provider_order": ["openrouter"],
        "allow_unknown_cost": True,
        "allow_paid": True,
        "free_only": True,
    }
    assert _eligible({"provider": "openrouter", "cost_class": "free"}, policy, is_primary=False)
    assert not _eligible({"provider": "openrouter", "cost_class": "unknown"}, policy, is_primary=False)


def test_failover_is_limited_to_transient_errors():
    request = httpx.Request("POST", "https://provider.example/v1/chat/completions")
    response = httpx.Response(429, request=request)
    rate_limited = httpx.HTTPStatusError("rate limited", request=request, response=response)
    assert _is_transient_error(rate_limited)
    assert _is_transient_error(httpx.ReadTimeout("timeout"))
    bad_request_response = httpx.Response(400, request=request)
    bad_request = httpx.HTTPStatusError("bad request", request=request, response=bad_request_response)
    assert not _is_transient_error(bad_request)


@pytest.mark.asyncio
async def test_chat_completion_falls_back_after_transient_error(monkeypatch):
    monkeypatch.setenv("OPENROUTER_API_KEY", "router-secret")
    monkeypatch.setenv("OPENROUTER_MODEL", "confirmed-free-model")
    monkeypatch.setenv("OPENROUTER_COST_CLASS", "free")
    attempts = []

    class FakeResponse:
        def __init__(self, status):
            self.status_code = status
            self.request = httpx.Request("POST", "https://example.test")
        def raise_for_status(self):
            if self.status_code >= 400:
                raise httpx.HTTPStatusError(
                    "temporary failure", request=self.request,
                    response=httpx.Response(self.status_code, request=self.request),
                )
        def json(self):
            return {"choices": [{"message": {"content": "ok"}}]}

    class FakeClient:
        def __init__(self, timeout):
            self.timeout = timeout
        async def __aenter__(self):
            return self
        async def __aexit__(self, *args):
            return False
        async def post(self, url, **kwargs):
            attempts.append(url)
            return FakeResponse(503 if len(attempts) == 1 else 200)

    monkeypatch.setattr("app.provider_router.httpx.AsyncClient", FakeClient)
    active = {
        "provider": "avalai", "base_url": "https://avalai.test/v1",
        "api_key": "avalai-secret", "model": "catalog-model",
    }
    result, metadata = await chat_completion(
        active,
        {"messages": [{"role": "user", "content": "test"}]},
        policy={
            "provider_order": ["avalai", "openrouter"],
            "allow_unknown_cost": True,
            "allow_paid": False,
            "free_only": False,
        },
    )
    assert result["choices"][0]["message"]["content"] == "ok"
    assert metadata["provider"] == "openrouter"
    assert metadata["fallback_used"] is True
    assert len(attempts) == 2
