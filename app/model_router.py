"""Dynamic model selection from the authenticated AvalAI account catalog.

No model IDs are assumed to be available: every candidate must come from
GET /v1/models for the configured API key.
"""
from __future__ import annotations

# Preferences are ranking hints only. A candidate is selected only if it exists
# in the authenticated account catalog.
_PREFERENCES = {
    "general": (
        "gpt-6.1-sol", "gpt-6-astra", "gemini-4-argon",
        "claude-opus-5-5", "deepseek-v4.1-flash", "gpt-6-luna",
    ),
    "coding": (
        "gpt-6-astra", "gpt-5.3-codex", "claude-opus-5-5",
        "claude-sonnet-5-5", "gemini-4-argon", "glm-5.3",
        "deepseek-v4.1-flash",
    ),
    "vision": ("gemini-4-argon", "gpt-6-astra", "claude-opus-5-5", "glm-5.3-flash"),
    "fast": ("gpt-6-luna", "gpt-5.4-mini", "deepseek-v4.1-flash", "claude-haiku-5-5"),
}

_NON_CHAT_HINTS = (
    "image", "embedding", "embed", "speech", "tts", "transcription",
    "moderation", "rerank", "ocr", "video",
)


def _is_chat_candidate(item: dict) -> bool:
    model_id = item.get("id")
    if not isinstance(model_id, str) or not model_id.strip():
        return False
    mode = str(item.get("mode") or "").lower()
    if mode and mode not in {"chat", "completion", "text", "reasoning", "multimodal"}:
        return False
    lowered = model_id.lower()
    return not any(hint in lowered for hint in _NON_CHAT_HINTS)


def select_avalai_model(models: list[dict], task: str = "general") -> str:
    """Select a chat-capable model that is actually present in the account catalog."""
    candidates = [item for item in models if isinstance(item, dict) and _is_chat_candidate(item)]
    if not candidates:
        raise RuntimeError("No chat-capable models are available to this AvalAI API key")
    by_id = {item["id"]: item for item in candidates}
    preference = _PREFERENCES.get(task, _PREFERENCES["general"])
    for model_id in preference:
        if model_id in by_id:
            return model_id
    # Prefer explicitly identified chat/reasoning models, then stable ID order.
    explicit = [item for item in candidates if str(item.get("mode") or "").lower() in {"chat", "completion", "text", "reasoning"}]
    pool = explicit or candidates
    return sorted(pool, key=lambda item: item["id"].lower())[0]["id"]
