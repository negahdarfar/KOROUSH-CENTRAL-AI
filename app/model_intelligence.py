"""Evidence-aware model capability and cost classification.

Provider metadata is authoritative. Name-based hints are explicitly marked as
inferred and must never be treated as verified capabilities or pricing.
"""
from __future__ import annotations


_HINTS = {
    "coding": ("code", "coder", "codex", "devstral"),
    "vision": ("vision", "vl", "multimodal"),
    "image_generation": ("image", "flux", "dall-e"),
    "audio": ("audio", "speech", "tts", "whisper", "transcription"),
    "video": ("video",),
    "embedding": ("embed", "embedding"),
    "rerank": ("rerank",),
}


def _numeric_values(value):
    if isinstance(value, dict):
        for nested in value.values():
            yield from _numeric_values(nested)
    elif isinstance(value, (int, float)) and not isinstance(value, bool):
        yield float(value)
    elif isinstance(value, str):
        try:
            yield float(value)
        except ValueError:
            return


def classify_model(model: dict) -> dict:
    """Return conservative categories and pricing status with evidence labels."""
    model_id = str(model.get("id") or "")
    mode = str(model.get("mode") or "").lower()
    categories = []
    evidence = {}

    if mode in {"chat", "completion", "text", "reasoning"}:
        categories.append("text_chat")
        evidence["text_chat"] = "provider_metadata"
    elif mode in {"image", "image_generation"}:
        categories.append("image_generation")
        evidence["image_generation"] = "provider_metadata"
    elif mode in {"embedding", "embeddings"}:
        categories.append("embedding")
        evidence["embedding"] = "provider_metadata"
    elif mode == "multimodal":
        categories.append("multimodal")
        evidence["multimodal"] = "provider_metadata"
    elif mode in {"audio", "speech"}:
        categories.append("audio")
        evidence["audio"] = "provider_metadata"

    if model.get("supports_vision") is True and "vision" not in categories:
        categories.append("vision")
        evidence["vision"] = "provider_metadata"
    if model.get("supports_function_calling") is True:
        categories.append("tool_calling")
        evidence["tool_calling"] = "provider_metadata"

    lowered = model_id.lower()
    for category, hints in _HINTS.items():
        if category not in categories and any(hint in lowered for hint in hints):
            categories.append(category)
            evidence[category] = "model_id_hint"

    pricing = model.get("pricing")
    values = list(_numeric_values(pricing)) if pricing is not None else []
    if values and all(value == 0 for value in values):
        pricing_status = "free_pricing_reported"
    elif any(value > 0 for value in values):
        pricing_status = "paid_pricing_reported"
    else:
        pricing_status = "unknown"

    return {
        "id": model_id,
        "categories": categories,
        "evidence": evidence,
        "classification_status": "provider_metadata_available" if model.get("details_available") else "partially_inferred",
        "pricing_status": pricing_status,
        "min_tier": model.get("min_tier"),
        "context_length": model.get("context_length"),
        "max_input_tokens": model.get("max_input_tokens"),
        "max_output_tokens": model.get("max_output_tokens"),
        "details_available": bool(model.get("details_available")),
        "inspection_status": model.get("status", "not_inspected"),
    }
