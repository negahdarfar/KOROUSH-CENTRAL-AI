import asyncio

import pytest

from app.agent_workflows import (
    AgentWorkflowInputError,
    execute_domain_workflow,
    validate_domain_workflow_input,
)


def _evidence():
    return [{
        "source_id": "source-1",
        "publisher": "Example publisher",
        "source_url": "https://example.com/report",
        "observed_at": "2026-11-25T00:00:00Z",
        "text": "Evidence text for a bounded research workflow.",
    }]


def test_workflow_validation_rejects_unknown_domains_and_extra_fields():
    with pytest.raises(AgentWorkflowInputError):
        validate_domain_workflow_input({"domain": "unknown", "evidence": _evidence()})
    with pytest.raises(AgentWorkflowInputError):
        validate_domain_workflow_input({"domain": "forex", "evidence": _evidence(), "steps": []})


def test_domain_workflow_runs_fixed_research_classification_and_synthesis_steps():
    calls = []

    async def fake_agent(job):
        payload = job["payload"]
        agent_id = payload["agent_id"]
        calls.append(agent_id)
        text = {
            "koroush.research-brief": "Research based on source-1.",
            "koroush.text-classifier": "Label: watchlist.",
            "koroush.text-summarizer": "Final domain report.",
        }[agent_id]
        return {"output": {"choices": [{"message": {"content": text}}]}}

    result = asyncio.run(execute_domain_workflow({
        "repository": "owner/repo",
        "payload": {"domain": "forex", "evidence": _evidence()},
    }, fake_agent))

    assert calls == [
        "koroush.research-brief",
        "koroush.text-classifier",
        "koroush.text-summarizer",
    ]
    assert result["step_count"] == 3
    assert result["source_ids"] == ["source-1"]
    assert result["report"] == "Final domain report."


def test_domain_workflow_optional_translation_is_bounded_fourth_step():
    calls = []

    async def fake_agent(job):
        agent_id = job["payload"]["agent_id"]
        calls.append(agent_id)
        text = "Translated report." if agent_id == "koroush.text-translator" else "Stage result."
        return {"output": {"choices": [{"message": {"content": text}}]}}

    result = asyncio.run(execute_domain_workflow({
        "repository": "owner/repo",
        "payload": {"domain": "youtube", "evidence": _evidence(), "target_language": "Persian"},
    }, fake_agent))

    assert result["step_count"] == 4
    assert calls[-1] == "koroush.text-translator"
    assert result["report"] == "Translated report."


def test_workflow_rejects_invalid_agent_output_without_claiming_success():
    async def fake_agent(job):
        return {"output": {"choices": []}}

    with pytest.raises(RuntimeError, match="invalid completion envelope"):
        asyncio.run(execute_domain_workflow({
            "repository": "owner/repo",
            "payload": {"domain": "nft", "evidence": _evidence()},
        }, fake_agent))
