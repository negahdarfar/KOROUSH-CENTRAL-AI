import pytest

from app.agent_contracts import (
    AGENT_CONTRACTS,
    AgentContractError,
    validate_agent_input,
    validate_agent_output,
)


def test_every_executable_agent_exposes_a_versioned_bounded_contract():
    assert set(AGENT_CONTRACTS) == {
        "koroush.text-summarizer",
        "koroush.text-translator",
        "koroush.text-classifier",
    }
    for contract in AGENT_CONTRACTS.values():
        assert contract["version"] == 1
        assert contract["max_source_chars"] == 12000
        assert contract["input_fields"]
        assert contract["output_fields"] == ["agent_id", "output"]


def test_summarizer_defaults_to_v1_and_normalizes_contract():
    agent_id, payload = validate_agent_input({
        "agent_id": "koroush.text-summarizer",
        "text": "  source  ",
    })
    assert agent_id == "koroush.text-summarizer"
    assert payload == {
        "agent_id": agent_id,
        "schema_version": 1,
        "text": "  source  ",
    }


@pytest.mark.parametrize("payload", [
    {"agent_id": "koroush.text-summarizer", "schema_version": 2, "text": "hello"},
    {"agent_id": "koroush.text-summarizer", "text": "hello", "tool": "shell"},
    {"agent_id": "tenant.custom-agent", "text": "hello"},
    {"agent_id": "koroush.text-summarizer", "text": "x" * 12001},
    {"agent_id": "koroush.text-summarizer", "text": "hello", "schema_version": True},
])
def test_invalid_version_unknown_fields_unknown_agents_and_oversize_inputs_fail(payload):
    with pytest.raises(AgentContractError):
        validate_agent_input(payload)


def test_translator_and_classifier_contracts_normalize_domain_fields():
    _, translated = validate_agent_input({
        "agent_id": "koroush.text-translator",
        "text": "hello",
        "target_language": "  Persian  ",
    })
    assert translated["target_language"] == "Persian"

    _, classified = validate_agent_input({
        "agent_id": "koroush.text-classifier",
        "text": "hello",
        "labels": [" positive ", "negative"],
    })
    assert classified["labels"] == ["positive", "negative"]


def test_output_envelope_is_validated():
    agent_id = "koroush.text-summarizer"
    assert validate_agent_output(agent_id, {
        "agent_id": agent_id,
        "output": {"choices": []},
    }) == {"agent_id": agent_id, "output": {"choices": []}}
    with pytest.raises(AgentContractError):
        validate_agent_output(agent_id, {"agent_id": "wrong", "output": []})
