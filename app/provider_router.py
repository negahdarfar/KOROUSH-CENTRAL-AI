"""Zero-budget-safe OpenAI-compatible provider registry.

A provider's self-declared COST_CLASS=free is NOT pricing evidence. A provider
can be used only when its exact model ID appears in a trusted, runtime-verified
free-model evidence map supplied by the caller. PR20 currently supplies such
evidence only for authenticated AvalAI catalog entries.
"""
from __future__ import annotations

import os


def _env_provider(name: str, *, base_default: str = "") -> dict | None:
    prefix = name.upper()
    api_key = os.getenv(f"{prefix}_API_KEY", "").strip()
    model = os.getenv(f"{prefix}_MODEL", "").strip()
    base_url = os.getenv(f"{prefix}_BASE_URL", base_default).strip().rstrip("/")
    if not (api_key and model and base_url):
        return None
    return {
        "provider": name.lower(),
        "base_url": base_url,
        "api_key": api_key,
        "model": model,
    }


def configured_chat_providers(active_llm: dict, provider_order: list[str] | None = None) -> list[dict]:
    """Return configured adapters in requested order; never return credentials to callers."""
    configs: dict[str, dict] = {}
    active_name = str(active_llm.get("provider") or "").strip().lower()
    if active_name and all(active_llm.get(key) for key in ("base_url", "api_key", "model")):
        configs[active_name] = {
            "provider": active_name,
            "base_url": str(active_llm["base_url"]).rstrip("/"),
            "api_key": active_llm["api_key"],
            "model": active_llm["model"],
        }
    for item in (
        _env_provider("openrouter", base_default="https://openrouter.ai/api/v1"),
        _env_provider("freellmapi"),
        _env_provider("gemini", base_default="https://generativelanguage.googleapis.com/v1beta/openai"),
    ):
        if item:
            configs[item["provider"]] = item
    order = []
    for name in [*(provider_order or []), active_name]:
        normalized = str(name).strip().lower()
        if normalized and normalized not in order:
            order.append(normalized)
    return [configs[name] for name in order if name in configs]


def verified_free_chat_providers(
    active_llm: dict,
    *,
    provider_order: list[str] | None,
    verified_free_models: dict[str, set[str]],
) -> list[dict]:
    """Fail closed unless exact provider/model has trusted zero-price evidence.

    Environment variables such as OPENROUTER_COST_CLASS=free are intentionally
    ignored. Evidence must be obtained from a trusted provider catalog or
    independently verified source by the caller.
    """
    if not isinstance(verified_free_models, dict):
        return []
    providers = configured_chat_providers(active_llm, provider_order)
    eligible = []
    for provider in providers:
        models = verified_free_models.get(provider["provider"], set())
        if not isinstance(models, (set, frozenset)):
            continue
        if provider["model"] not in models:
            continue
        eligible.append({
            "provider": provider["provider"],
            "base_url": provider["base_url"],
            "api_key": provider["api_key"],
            "model": provider["model"],
        })
    return eligible
