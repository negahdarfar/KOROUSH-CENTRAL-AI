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
        "koroush.research-brief",
    }
    for contract in AGENT_CONTRACTS.values():
        assert contract["version"] == 1
        assert contract["input_fields"]
        assert contract.get("max_source_chars", contract.get("max_evidence_chars")) in {12000, 20000}
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


def test_classifier_rejects_duplicates_after_whitespace_normalization():
    with pytest.raises(AgentContractError):
        validate_agent_input({
            "agent_id": "koroush.text-classifier",
            "text": "hello",
            "labels": [" positive ", "positive"],
        })


def test_classifier_enforces_label_length_after_normalization():
    with pytest.raises(AgentContractError):
        validate_agent_input({
            "agent_id": "koroush.text-classifier",
            "text": "hello",
            "labels": ["x" * 81, "other"],
        })


def test_agent_output_must_be_json_serializable_and_bounded():
    agent_id = "koroush.text-summarizer"
    with pytest.raises(AgentContractError):
        validate_agent_output(agent_id, {
            "agent_id": agent_id,
            "output": {"not_json": object()},
        })
    with pytest.raises(AgentContractError):
        validate_agent_output(agent_id, {
            "agent_id": agent_id,
            "output": {"large": "x" * 65537},
        })


def test_research_brief_accepts_only_bounded_evidence_for_known_domains():
    agent_id, payload = validate_agent_input({
        "agent_id": "koroush.research-brief",
        "domain": "forex",
        "evidence": [
            {"source_id": "report-a", "text": "EUR/USD moved higher in the cited session."},
            {"source_id": "report-b", "text": "The source reports elevated volatility."},
        ],
    })
    assert agent_id == "koroush.research-brief"
    assert payload["schema_version"] == 1
    assert payload["domain"] == "forex"
    assert payload["evidence"][0]["source_id"] == "report-a"


@pytest.mark.parametrize("payload", [
    {"agent_id": "koroush.research-brief", "domain": "stocks", "evidence": [{"source_id": "a", "text": "x"}]},
    {"agent_id": "koroush.research-brief", "domain": "nft", "evidence": []},
    {"agent_id": "koroush.research-brief", "domain": "ptc", "evidence": [{"source_id": "a", "text": "x", "url": "https://example.com"}]},
    {"agent_id": "koroush.research-brief", "domain": "youtube", "evidence": [{"source_id": "a", "text": "x"}, {"source_id": "A", "text": "y"}]},
    {"agent_id": "koroush.research-brief", "domain": "forex", "evidence": [{"source_id": "a", "text": "x" * 5001}]},
]) 
def test_research_brief_rejects_invalid_or_unbounded_evidence(payload):
    with pytest.raises(AgentContractError):
        validate_agent_input(payload)


def test_research_brief_rejects_combined_evidence_over_limit():
    with pytest.raises(AgentContractError):
        validate_agent_input({
            "agent_id": "koroush.research-brief",
            "domain": "nft",
            "evidence": [
                {"source_id": f"source-{i}", "text": "x" * 5000}
                for i in range(5)
            ],
        })

def test_research_brief_rejects_utf8_payloads_over_byte_limit():
    with pytest.raises(AgentContractError):
        validate_agent_input({
            "agent_id": "koroush.research-brief",
            "domain": "forex",
            "evidence": [
                {"source_id": f"unicode-{i}", "text": "😀" * 4000}
                for i in range(4)
            ],
        })

def test_research_brief_normalizes_provenance_metadata_and_content_fingerprint():
    _, payload = validate_agent_input({
        "agent_id": "koroush.research-brief",
        "domain": "youtube",
        "evidence": [{
            "source_id": "trend-report",
            "text": "A supplied trend excerpt.",
            "publisher": "Example Publisher",
            "source_url": "https://example.org/trends",
            "observed_at": "2026-11-24T10:00:00Z",
        }],
    })
    item = payload["evidence"][0]
    assert item["publisher"] == "Example Publisher"
    assert item["freshness"] in {"fresh", "recent", "stale"}
    assert item["credibility"] == "unverified"
    assert len(item["sha256"]) == 64


def test_research_brief_rejects_invalid_provenance_metadata():
    with pytest.raises(AgentContractError):
        validate_agent_input({
            "agent_id": "koroush.research-brief",
            "domain": "forex",
            "evidence": [{
                "source_id": "bad-url", "text": "Excerpt",
                "source_url": "http://example.org/insecure",
            }],
        })
    with pytest.raises(AgentContractError):
        validate_agent_input({
            "agent_id": "koroush.research-brief",
            "domain": "nft",
            "evidence": [{
                "source_id": "bad-time", "text": "Excerpt",
                "observed_at": "2026-11-24T10:00:00",
            }],
        })