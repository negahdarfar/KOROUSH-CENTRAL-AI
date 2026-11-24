"""Policy-aware model ranking for the authenticated AvalAI catalog.

The router never invents model IDs. Cost is ranked conservatively: explicitly
free models first, unknown-price models second, paid models last. A caller may
forbid unknown or paid models through a workflow policy.
"""
from __future__ import annotations

_PREFERENCES = {
    "general": ("gpt-6.1-sol", "gpt-6-astra", "gemini-4-argon", "claude-opus-5-5", "deepseek-v4.1-flash", "gpt-6-luna"),
    "coding": ("gpt-6-astra", "gpt-5.3-codex", "claude-opus-5-5", "claude-sonnet-5-5", "gemini-4-argon", "glm-5.3", "deepseek-v4.1-flash"),
    "vision": ("gemini-4-argon", "gpt-6-astra", "claude-opus-5-5", "glm-5.3-flash"),
    "fast": ("gpt-6-luna", "gpt-5.4-mini", "deepseek-v4.1-flash", "claude-haiku-5-5"),
    "reasoning": ("gpt-6-astra", "claude-opus-5-5", "deepseek-v4.1-flash"),
    "research": ("gemini-4-argon", "claude-opus-5-5", "gpt-6-astra"),
}
_NON_CHAT_HINTS = ("image", "embedding", "embed", "speech", "tts", "transcription", "moderation", "rerank", "ocr", "video")


def _is_chat_candidate(item: dict) -> bool:
    model_id = item.get("id")
    if not isinstance(model_id, str) or not model_id.strip():
        return False
    mode = str(item.get("mode") or "").lower()
    if mode and mode not in {"chat", "completion", "text", "reasoning", "multimodal"}:
        return False
    return not any(hint in model_id.lower() for hint in _NON_CHAT_HINTS)


def _cost_class(item: dict) -> str:
    pricing = item.get("pricing")
    values = []
    def walk(value):
        if isinstance(value, dict):
            for nested in value.values():
                walk(nested)
        elif isinstance(value, (int, float)) and not isinstance(value, bool):
            values.append(float(value))
        elif isinstance(value, str):
            try:
                values.append(float(value))
            except ValueError:
                pass
    walk(pricing)
    if values and all(value == 0 for value in values):
        return "free"
    if any(value > 0 for value in values):
        return "paid"
    return "unknown"


def infer_task(task: str, description: str = "") -> str:
    """Map a workflow description to a conservative capability class."""
    value = f"{task} {description}".lower()
    if any(x in value for x in ("vision", "image input", "screenshot", "تصویر", "عکس")):
        return "vision"
    if any(x in value for x in ("code", "coding", "debug", "refactor", "برنامه", "کدنویسی", "باگ")):
        return "coding"
    if any(x in value for x in ("research", "search", "report", "تحقیق", "گزارش", "تحلیل بازار")):
        return "research"
    if any(x in value for x in ("reason", "planning", "architecture", "معماری", "طراحی سیستم")):
        return "reasoning"
    if any(x in value for x in ("fast", "quick", "summary", "خلاصه", "سریع")):
        return "fast"
    return "general"


def rank_avalai_models(
    models: list[dict],
    task: str = "general",
    *,
    preferred_models: list[str] | tuple[str, ...] = (),
    free_only: bool = False,
    allow_unknown_cost: bool = True,
    allow_paid: bool = True,
) -> list[dict]:
    """Return eligible candidates in preference/cost/capability order."""
    task = task if task in _PREFERENCES else "general"
    preferred = list(preferred_models) or list(_PREFERENCES[task])
    preference_rank = {model_id: index for index, model_id in enumerate(preferred)}
    candidates = []
    for item in models:
        if not isinstance(item, dict) or not _is_chat_candidate(item):
            continue
        cost = _cost_class(item)
        if free_only and cost != "free":
            continue
        if cost == "unknown" and not allow_unknown_cost:
            continue
        if cost == "paid" and not allow_paid:
            continue
        mode = str(item.get("mode") or "").lower()
        candidates.append({
            **item,
            "routing": {
                "cost_class": cost,
                "task": task,
                "preference_rank": preference_rank.get(item["id"], len(preferred) + 1),
                "selection_evidence": "catalog_metadata_plus_policy",
            },
        })
    candidates.sort(key=lambda item: (
        {"free": 0, "unknown": 1, "paid": 2}[item["routing"]["cost_class"]],
        item["routing"]["preference_rank"],
        0 if str(item.get("mode") or "").lower() in {"chat", "completion", "text", "reasoning"} else 1,
        item["id"].lower(),
    ))
    return candidates


def select_avalai_model(
    models: list[dict],
    task: str = "general",
    *,
    free_only: bool = False,
    allow_unknown_cost: bool = True,
    allow_paid: bool = True,
) -> str:
    """Select the highest-ranked eligible model from the live account catalog."""
    candidates = rank_avalai_models(
        models, task, free_only=free_only,
        allow_unknown_cost=allow_unknown_cost, allow_paid=allow_paid,
    )
    if not candidates:
        raise RuntimeError("No chat-capable models are eligible under the current workflow cost policy")
    return candidates[0]["id"]
