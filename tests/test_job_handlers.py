import asyncio

import pytest

from app import job_handlers


class FakeResponse:
    headers = {}


def test_chat_job_validates_and_uses_central_guard(monkeypatch):
    seen = {}

    async def fake_dispatch(llm, payload, *, task, repository, requested_model, timeout):
        seen.update({"payload": payload, "task": task, "repository": repository, "model": requested_model})
        return ({"choices": [{"message": {"role": "assistant", "content": "done"}}],
                 "usage": {"total_tokens": 9}, "id": "req-1"}, FakeResponse(), "verified-model")

    monkeypatch.setattr(job_handlers, "_chat_completion_with_free_failover", fake_dispatch)
    result = asyncio.run(job_handlers.chat_completion_job({
        "repository": "org/repo",
        "payload": {
            "task": "coding",
            "model": "verified-model",
            "messages": [{"role": "user", "content": "Please review this function"}],
            "max_tokens": 300,
        },
    }))
    assert result["model"] == "verified-model"
    assert result["choices"][0]["message"]["content"] == "done"
    assert seen["repository"] == "org/repo"
    assert seen["task"] == "coding"
    assert seen["payload"]["max_tokens"] == 300


def test_chat_job_rejects_unbounded_or_unsupported_input():
    with pytest.raises(job_handlers.JobInputError):
        asyncio.run(job_handlers.chat_completion_job({
            "repository": "org/repo",
            "payload": {"messages": [{"role": "developer", "content": "bad"}]},
        }))
    with pytest.raises(job_handlers.JobInputError):
        asyncio.run(job_handlers.chat_completion_job({
            "repository": "org/repo",
            "payload": {"messages": [{"role": "user", "content": "x" * 12001}]},
        }))


def test_research_brief_uses_only_supplied_evidence_and_central_zero_cost_dispatch(monkeypatch):
    seen = {}

    async def fake_dispatch(llm, payload, *, task, repository, requested_model, timeout):
        seen["payload"] = payload
        seen["task"] = task
        seen["repository"] = repository
        return ({"choices": [{"message": {"role": "assistant", "content": "Findings cite report-1; evidence gaps remain."}}],
                 "usage": {"total_tokens": 20}, "id": "research-1"}, FakeResponse(), "verified-model")

    monkeypatch.setattr(job_handlers, "_chat_completion_with_free_failover", fake_dispatch)
    result = asyncio.run(job_handlers.agent_execute_job({
        "repository": "org/forex-repo",
        "payload": {
            "agent_id": "koroush.research-brief",
            "schema_version": 1,
            "domain": "forex",
            "evidence": [{"source_id": "report-1", "text": "A supplied source states volatility increased."}],
        },
    }))
    assert result["agent_id"] == "koroush.research-brief"
    assert seen["repository"] == "org/forex-repo"
    assert seen["task"] == "general"
    assert "report-1" in seen["payload"]["messages"][1]["content"]
    assert "Do not browse" in seen["payload"]["messages"][0]["content"]


def test_research_brief_rejects_invalid_contract_before_provider_call(monkeypatch):
    async def forbidden_dispatch(*args, **kwargs):
        raise AssertionError("provider must not be called for invalid input")

    monkeypatch.setattr(job_handlers, "_chat_completion_with_free_failover", forbidden_dispatch)
    with pytest.raises(job_handlers.JobInputError):
        asyncio.run(job_handlers.agent_execute_job({
            "repository": "org/repo",
            "payload": {"agent_id": "koroush.research-brief", "domain": "unknown", "evidence": []},
        }))