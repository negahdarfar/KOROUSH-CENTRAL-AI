"""Versioned, bounded input/output contracts for executable central agents.

Contracts are deliberately local and allow-listed: tenant payloads never choose
a Python module, URL, tool, provider adapter, or arbitrary execution target.
"""
from __future__ import annotations

import json
from typing import Any


CONTRACT_VERSION = 1
MAX_SOURCE_CHARS = 12_000
MAX_TARGET_LANGUAGE_CHARS = 80
MAX_LABELS = 20
MAX_LABEL_CHARS = 80
MAX_OUTPUT_BYTES = 64 * 1024
MAX_RESEARCH_ITEMS = 8
MAX_RESEARCH_ITEM_CHARS = 5_000
MAX_RESEARCH_TOTAL_CHARS = 20_000
MAX_RESEARCH_TOTAL_BYTES = 48 * 1024
RESEARCH_DOMAINS = {"forex", "youtube", "ptc", "nft"}

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
    "koroush.research-brief": {
        "version": CONTRACT_VERSION,
        "input_fields": ["agent_id", "schema_version", "domain", "evidence"],
        "output_fields": ["agent_id", "output"],
        "required_fields": ["domain", "evidence"],
        "max_evidence_items": MAX_RESEARCH_ITEMS,
        "max_evidence_chars": MAX_RESEARCH_TOTAL_CHARS,
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

    if agent_id == "koroush.research-brief":
        domain = payload.get("domain")
        evidence = payload.get("evidence")
        if not isinstance(domain, str) or domain not in RESEARCH_DOMAINS:
            raise AgentContractError("domain must be one of forex, youtube, ptc, nft")
        if not isinstance(evidence, list) or not 1 <= len(evidence) <= MAX_RESEARCH_ITEMS:
            raise AgentContractError("evidence must contain 1–8 source items")
        clean_evidence = []
        total_chars = 0
        total_bytes = 0
        for item in evidence:
            if not isinstance(item, dict) or set(item) != {"source_id", "text"}:
                raise AgentContractError("each evidence item must contain only source_id and text")
            source_id, source_text = item["source_id"], item["text"]
            if (
                not isinstance(source_id, str) or not source_id.strip() or len(source_id.strip()) > 80
                or not isinstance(source_text, str) or not source_text.strip()
                or len(source_text) > MAX_RESEARCH_ITEM_CHARS
            ):
                raise AgentContractError("evidence source_id/text is invalid or exceeds its limit")
            total_chars += len(source_text)
            total_bytes += len(source_text.encode("utf-8"))
            clean_evidence.append({"source_id": source_id.strip(), "text": source_text})
        if total_chars > MAX_RESEARCH_TOTAL_CHARS:
            raise AgentContractError("combined evidence exceeds 20000 characters")
        if total_bytes > MAX_RESEARCH_TOTAL_BYTES:
            raise AgentContractError("combined UTF-8 evidence exceeds the 48 KiB limit")
        if len({item["source_id"].casefold() for item in clean_evidence}) != len(clean_evidence):
            raise AgentContractError("evidence source_id values must be unique")
        return agent_id, {
            "agent_id": agent_id,
            "schema_version": CONTRACT_VERSION,
            "domain": domain,
            "evidence": clean_evidence,
        }

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
        if not isinstance(labels, list) or not 2 <= len(labels) <= MAX_LABELS:
            raise AgentContractError("labels must contain 2–20 unique non-empty strings")
        if any(
            not isinstance(label, str) or not label.strip() or len(label.strip()) > MAX_LABEL_CHARS
            for label in labels
        ):
            raise AgentContractError("labels must contain 2–20 unique non-empty strings")
        clean_labels = [label.strip() for label in labels]
        if len({label.casefold() for label in clean_labels}) != len(clean_labels):
            raise AgentContractError("labels must contain 2–20 unique non-empty strings")
        normalized["labels"] = clean_labels
    return agent_id, normalized


def validate_agent_output(agent_id: str, output: Any) -> dict[str, Any]:
    """Validate the stable envelope before it is persisted as a job result."""
    if agent_id not in AGENT_CONTRACTS or not isinstance(output, dict):
        raise AgentContractError("agent output does not match a registered contract")
    if output.get("agent_id") != agent_id or not isinstance(output.get("output"), dict):
        raise AgentContractError("agent output envelope is invalid")
    try:
        encoded = json.dumps(output["output"], ensure_ascii=False, separators=(",", ":")).encode("utf-8")
    except (TypeError, ValueError, OverflowError) as exc:
        raise AgentContractError("agent output must be JSON-serializable") from exc
    if len(encoded) > MAX_OUTPUT_BYTES:
        raise AgentContractError("agent output exceeds the 65536-byte limit")
    return {"agent_id": agent_id, "output": output["output"]}
