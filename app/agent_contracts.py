"""Versioned, bounded input/output contracts for executable central agents.

Contracts are deliberately local and allow-listed: tenant payloads never choose
a Python module, URL, tool, provider adapter, or arbitrary execution target.
"""
from __future__ import annotations

from typing import Any


CONTRACT_VERSION = 1
MAX_SOURCE_CHARS = 12_000
MAX_TARGET_LANGUAGE_CHARS = 80
MAX_LABELS = 20
MAX_LABEL_CHARS = 80

AGENT_CONTRACTS: dict[str, dict[str, Any]] = {
    "koroush.text-summarizer": {
        "version": CONTRACT_VERSION,
        "input_fields": ["agent_id", "schema_version", "text"],
        "output_fields": ["agent_id", "output"],
        "required_fields": ["text"],
        "max_source_chars": MAX_SOURCE_CHARS,
    },
    "koroush.text-translator": {
        "version": CONTRACT_VERSION,
        "input_fields": ["agent_id", "schema_version", "text", "target_language"],
        "output_fields": ["agent_id", "output"],
        "required_fields": ["text", "target_language"],
        "max_source_chars": MAX_SOURCE_CHARS,
    },
    "koroush.text-classifier": {
        "version": CONTRACT_VERSION,
        "input_fields": ["agent_id", "schema_version", "text", "labels"],
        "output_fields": ["agent_id", "output"],
        "required_fields": ["text", "labels"],
        "max_source_chars": MAX_SOURCE_CHARS,
    },
}


class AgentContractError(ValueError):
    """A request does not satisfy a registered agent's public contract."""


def validate_agent_input(payload: Any) -> tuple[str, dict[str, Any]]:
    """Validate and normalize one v1 input, rejecting unknown fields."""
    if not isinstance(payload, dict):
        raise AgentContractError("agent payload must be an object")
    agent_id = payload.get("agent_id")
    contract = AGENT_CONTRACTS.get(agent_id) if isinstance(agent_id, str) else None
    if contract is None:
        raise AgentContractError("agent_id is not an executable registered text agent")

    version = payload.get("schema_version", CONTRACT_VERSION)
    if isinstance(version, bool) or version != contract["version"]:
        raise AgentContractError("unsupported agent input schema_version")

    allowed = set(contract["input_fields"])
    unknown = set(payload) - allowed
    if unknown:
        raise AgentContractError("agent payload contains unsupported fields")

    missing = set(contract["required_fields"]) - set(payload)
    if missing:
        raise AgentContractError("agent payload is missing required fields")

    text = payload.get("text")
    if not isinstance(text, str) or not text.strip() or len(text) > MAX_SOURCE_CHARS:
        raise AgentContractError("text must be non-empty and at most 12000 characters")

    normalized: dict[str, Any] = {
        "agent_id": agent_id,
        "schema_version": CONTRACT_VERSION,
        "text": text,
    }
    if agent_id == "koroush.text-translator":
        target = payload.get("target_language")
        if not isinstance(target, str) or not target.strip() or len(target) > MAX_TARGET_LANGUAGE_CHARS:
            raise AgentContractError("target_language is required and must be at most 80 characters")
        normalized["target_language"] = target.strip()
    elif agent_id == "koroush.text-classifier":
        labels = payload.get("labels")
        if (
            not isinstance(labels, list) or not 2 <= len(labels) <= MAX_LABELS
            or any(not isinstance(label, str) or not label.strip() or len(label) > MAX_LABEL_CHARS for label in labels)
            or len({label.casefold() for label in labels}) != len(labels)
        ):
            raise AgentContractError("labels must contain 2–20 unique non-empty strings")
        normalized["labels"] = [label.strip() for label in labels]
    return agent_id, normalized


def validate_agent_output(agent_id: str, output: Any) -> dict[str, Any]:
    """Validate the stable envelope before it is persisted as a job result."""
    if agent_id not in AGENT_CONTRACTS or not isinstance(output, dict):
        raise AgentContractError("agent output does not match a registered contract")
    if output.get("agent_id") != agent_id or not isinstance(output.get("output"), dict):
        raise AgentContractError("agent output envelope is invalid")
    return {"agent_id": agent_id, "output": output["output"]}
