import asyncio

import httpx
import pytest

from app import agent


class FakeAsyncClient:
    responses = []
    calls = []

    def __init__(self, timeout=None):
        self.timeout = timeout

    async def __aenter__(self):
        return self

    async def __aexit__(self, *args):
        return False

    async def post(self, url, headers=None, json=None):
        self.calls.append({"url": url, "model": json["model"]})
        return self.responses.pop(0)


def _response(status, payload=None):
    return httpx.Response(
        status,
        json=payload or {},
        request=httpx.Request("POST", "https://api.avalai.ir/v1/chat/completions"),
    )


def test_transient_failure_falls_back_only_to_catalog_confirmed_free_models(monkeypatch, tmp_path):
    monkeypatch.setenv("USAGE_DB_PATH", str(tmp_path / "usage.sqlite3"))
    monkeypatch.setattr(agent.settings, "allowed_repos", "org/repo")
    FakeAsyncClient.calls = []
    FakeAsyncClient.responses = [
        _response(503),
        _response(200, {"id": "req-ok", "usage": {"total_tokens": 12},
                        "choices": [{"message": {"content": "ok"}}]}),
    ]
    monkeypatch.setattr(agent.httpx, "AsyncClient", FakeAsyncClient)
    monkeypatch.setattr(agent, "list_avalai_models", lambda: _async_value([
        {"id": "first-free", "mode": "chat", "pricing": {"prompt": 0, "completion": 0}},
        {"id": "second-free", "mode": "chat", "pricing": {"prompt": 0, "completion": 0}},
        {"id": "paid-model", "mode": "chat", "pricing": {"prompt": 1, "completion": 1}},
        {"id": "unknown-model", "mode": "chat"},
    ]))
    monkeypatch.setattr(agent, "resolve_workflow_policy", lambda repository=None: {
        "task": "general", "free_only": True, "allow_unknown_cost": False,
        "allow_paid": False, "max_retries": 1,
    })
    recorded = []
    monkeypatch.setattr(agent, "_record_chat_usage",
                        lambda repo, provider, model, data, response, surface: recorded.append((provider, model)))

    data, response, model = asyncio.run(agent._chat_completion_with_free_failover(
        {"provider": "avalai", "api_key": "test", "base_url": "https://api.avalai.ir/v1", "model": ""},
        {"messages": []}, task="general", repository="org/repo",
    ))
    assert [call["model"] for call in FakeAsyncClient.calls] == ["first-free", "second-free"]
    assert model == "second-free"
    assert data["choices"][0]["message"]["content"] == "ok"
    assert recorded == [("avalai", "second-free")]


async def _async_value(value):
    return value


def test_explicit_model_does_not_silently_switch_to_another_model(monkeypatch, tmp_path):
    monkeypatch.setenv("USAGE_DB_PATH", str(tmp_path / "usage.sqlite3"))
    monkeypatch.setattr(agent.settings, "allowed_repos", "org/repo")
    FakeAsyncClient.calls = []
    FakeAsyncClient.responses = [_response(503)]
    monkeypatch.setattr(agent.httpx, "AsyncClient", FakeAsyncClient)
    monkeypatch.setattr(agent, "list_avalai_models", lambda: _async_value([
        {"id": "chosen-free", "mode": "chat", "pricing": {"prompt": 0, "completion": 0}},
        {"id": "backup-free", "mode": "chat", "pricing": {"prompt": 0, "completion": 0}},
    ]))
    monkeypatch.setattr(agent, "resolve_workflow_policy", lambda repository=None: {
        "task": "general", "free_only": True, "allow_unknown_cost": False,
        "allow_paid": False, "max_retries": 3,
    })
    with pytest.raises(RuntimeError, match="No paid or unknown-price fallback"):
        asyncio.run(agent._chat_completion_with_free_failover(
            {"provider": "avalai", "api_key": "test", "base_url": "https://api.avalai.ir/v1", "model": ""},
            {"messages": []}, task="general", repository="org/repo",
            requested_model="chosen-free",
        ))
    assert [call["model"] for call in FakeAsyncClient.calls] == ["chosen-free"]


def test_non_retryable_auth_error_does_not_trigger_failover(monkeypatch, tmp_path):
    monkeypatch.setenv("USAGE_DB_PATH", str(tmp_path / "usage.sqlite3"))
    monkeypatch.setattr(agent.settings, "allowed_repos", "org/repo")
    FakeAsyncClient.calls = []
    FakeAsyncClient.responses = [_response(401)]
    monkeypatch.setattr(agent.httpx, "AsyncClient", FakeAsyncClient)
    monkeypatch.setattr(agent, "list_avalai_models", lambda: _async_value([
        {"id": "first-free", "mode": "chat", "pricing": {"prompt": 0, "completion": 0}},
        {"id": "second-free", "mode": "chat", "pricing": {"prompt": 0, "completion": 0}},
    ]))
    monkeypatch.setattr(agent, "resolve_workflow_policy", lambda repository=None: {
        "task": "general", "free_only": True, "allow_unknown_cost": False,
        "allow_paid": False, "max_retries": 1,
    })
    with pytest.raises(httpx.HTTPStatusError):
        asyncio.run(agent._chat_completion_with_free_failover(
            {"provider": "avalai", "api_key": "test", "base_url": "https://api.avalai.ir/v1", "model": ""},
            {"messages": []}, task="general", repository="org/repo",
        ))
    assert [call["model"] for call in FakeAsyncClient.calls] == ["first-free"]



def test_agent_inference_rejects_repository_outside_operator_allowlist(monkeypatch, tmp_path):
    monkeypatch.setenv("USAGE_DB_PATH", str(tmp_path / "usage.sqlite3"))
    monkeypatch.setattr(agent.settings, "allowed_repos", "org/approved")
    async def unexpected_catalog_call():
        raise AssertionError("catalog must not be queried for an unapproved repository")
    monkeypatch.setattr(agent, "list_avalai_models", unexpected_catalog_call)

    with pytest.raises(ValueError, match="not explicitly approved"):
        asyncio.run(agent._chat_completion_with_free_failover(
            {"provider": "avalai", "api_key": "test", "base_url": "https://api.avalai.ir/v1", "model": ""},
            {"messages": []}, task="general", repository="org/unapproved",
        ))
