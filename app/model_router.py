"""Policy-aware model ranking for the authenticated AvalAI catalog.

The router never invents model IDs. Cost is ranked conservatively: explicitly
free models first, unknown-price models second, paid models last. A caller may
forbid unknown or paid models through a workflow policy.
"""
from __future__ import annotations

from .model_intelligence import classify_chat_price

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
    return classify_chat_price(item.get("pricing"))


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
    performance_metrics: dict | None = None,
) -> list[dict]:
    """Rank by cost, task fit and observed runtime telemetry.

    Runtime observations are neutral until three attempts exist. Latency is
    never presented as a benchmark of answer quality.
    """
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
        preference = preference_rank.get(item["id"], len(preferred) + 1)
        observed = (performance_metrics or {}).get(f"avalai:{item['id']}", {})
        samples = int(observed.get("attempts") or 0)
        if samples >= 3:
            reliability = max(0.0, min(100.0, float(observed.get("success_rate") or 0) * 100))
            rate_limit = max(0.0, min(100.0, float(observed.get("rate_limit_rate") or 0) * 100))
            latency = observed.get("latency_ewma_ms")
            speed = max(0.0, 100.0 - min(float(latency or 60000), 60000.0) / 600.0)
            quota_health = 100.0 - rate_limit
        else:
            reliability, speed, quota_health = 60.0, 60.0, 60.0
        task_fit = max(0.0, 100.0 - min(preference, 10) * 10.0)
        benchmark_quality = item.get("quality_score")
        quality_verified = (
            isinstance(benchmark_quality, (int, float))
            and not isinstance(benchmark_quality, bool)
            and 0 <= benchmark_quality <= 100
            and item.get("quality_evidence") == "verified_benchmark"
        )
        score = 0.35 * task_fit + 0.30 * reliability + 0.20 * speed + 0.15 * quota_health
        if quality_verified:
            score = 0.8 * score + 0.2 * float(benchmark_quality)
        candidates.append({
            **item,
            "routing": {
                "cost_class": cost,
                "task": task,
                "preference_rank": preference,
                "task_fit_score": round(task_fit, 2),
                "reliability_score": round(reliability, 2),
                "speed_score": round(speed, 2),
                "quota_health_score": round(quota_health, 2),
                "quality_score": float(benchmark_quality) if quality_verified else None,
                "quality_evidence": "verified_benchmark" if quality_verified else "not_measured",
                "runtime_samples": samples,
                "composite_score": round(score, 2),
                "selection_evidence": "catalog_policy_and_observed_runtime" if samples >= 3 else "catalog_policy_only",
            },
        })
    candidates.sort(key=lambda item: (
        {"free": 0, "unknown": 1, "paid": 2}[item["routing"]["cost_class"]],
        -item["routing"]["composite_score"],
        item["routing"]["preference_rank"],
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
