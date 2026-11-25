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


def classify_chat_price(pricing):
    """Fail closed for incomplete or ambiguous token pricing.

    Recognize the two flat schemas used by the existing catalog contracts.
    A zero value for only one side is insufficient. Extra fields must also
    be explicit finite zero prices; unfamiliar metadata is not evidence.
    """
    from decimal import Decimal, InvalidOperation
    if not isinstance(pricing, dict) or not pricing:
        return "unknown"
    values = {}
    invalid = False
    for key, value in pricing.items():
        if isinstance(value, bool) or not isinstance(value, (int, float, str)):
            invalid = True
            continue
        try:
            number = Decimal(str(value))
        except (InvalidOperation, ValueError):
            invalid = True
            continue
        if not number.is_finite() or number < 0:
            invalid = True
            continue
        values[key] = number
    if any(value > 0 for value in values.values()):
        return "paid"
    if invalid or not ({"input", "output"} <= values.keys() or {"prompt", "completion"} <= values.keys()):
        return "unknown"
    return "free"


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

    price_class = classify_chat_price(model.get("pricing"))
    pricing_status = {"free": "free_pricing_reported", "paid": "paid_pricing_reported", "unknown": "unknown"}[price_class]

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
