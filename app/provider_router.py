"""Configured OpenAI-compatible provider adapters with guarded failover.

Provider credentials are read only from environment variables and are never
returned in diagnostics. Fallback is limited to transient transport/provider
errors and is disabled for unclassified-cost providers unless explicitly
allowed by workflow policy.
"""
from __future__ import annotations

import os
from typing import Any

import httpx


_TRANSIENT_STATUS = {408, 409, 425, 429}


def _env_provider(name: str, *, base_default: str = "") -> dict | None:
    prefix = name.upper()
    api_key = os.getenv(f"{prefix}_API_KEY", "").strip()
    model = os.getenv(f"{prefix}_MODEL", "").strip()
    base_url = os.getenv(f"{prefix}_BASE_URL", base_default).strip().rstrip("/")
    if not (api_key and model and base_url):
        return None
    cost_class = os.getenv(f"{prefix}_COST_CLASS", "unknown").strip().lower()
    if cost_class not in {"free", "unknown", "paid"}:
        cost_class = "unknown"
    return {
        "provider": name.lower(),
        "base_url": base_url,
        "api_key": api_key,
        "model": model,
        "cost_class": cost_class,
    }


def configured_chat_providers(active_llm: dict, provider_order: list[str] | None = None) -> list[dict]:
    """Return configured candidates in policy order, without exposing secrets."""
    configs: dict[str, dict] = {}
    active_name = str(active_llm.get("provider") or "").lower()
    if active_name in {"avalai", "legacy"} and all(active_llm.get(k) for k in ("base_url", "api_key", "model")):
        configs[active_name] = {
            "provider": active_name,
            "base_url": active_llm["base_url"].rstrip("/"),
            "api_key": active_llm["api_key"],
            "model": active_llm["model"],
            "cost_class": "free" if active_name == "avalai" and os.getenv("KOROUSH_ACTIVE_AVALAI_MODEL_VERIFIED_FREE", "").lower() == "true" else "unknown",
        }

    candidates = (
        _env_provider("openrouter", base_default="https://openrouter.ai/api/v1"),
        _env_provider("freellmapi"),
        _env_provider("gemini", base_default="https://generativelanguage.googleapis.com/v1beta/openai"),
    )
    for item in candidates:
        if item:
            configs[item["provider"]] = item

    order = []
    for provider in [*(provider_order or []), active_name]:
        provider = str(provider).strip().lower()
        if provider and provider not in order:
            order.append(provider)
    return [configs[name] for name in order if name in configs]


def _eligible(provider: dict, policy: dict, *, is_primary: bool) -> bool:
    cost = provider.get("cost_class", "unknown")
    if cost == "paid" and not policy.get("allow_paid", False):
        return False
    if cost == "unknown" and (not policy.get("allow_unknown_cost", False) or (not is_primary and os.getenv("KOROUSH_ALLOW_UNKNOWN_PROVIDER_FALLBACK", "").lower() != "true")):
        return False
    if policy.get("free_only", False) and cost != "free":
        return False
    # The active provider is retained for compatibility; non-primary providers
    # must be explicitly listed and pass the same cost policy.
    return is_primary or provider["provider"] in policy.get("provider_order", [])


def _is_transient_error(exc: Exception) -> bool:
    if isinstance(exc, httpx.TimeoutException | httpx.NetworkError):
        return True
    if isinstance(exc, httpx.HTTPStatusError):
        return exc.response.status_code in _TRANSIENT_STATUS or exc.response.status_code >= 500
    return False


async def chat_completion(
    active_llm: dict,
    payload: dict,
    *,
    policy: dict | None = None,
    timeout: float = 120.0,
) -> tuple[dict, dict]:
    """Call configured providers in order; retry only transient failures.

    Returns (OpenAI-compatible JSON response, safe provider metadata).
    """
    policy = policy or {}
    providers = configured_chat_providers(active_llm, policy.get("provider_order"))
    if not providers:
        raise RuntimeError("No configured chat provider is available")

    eligible = [
        item for index, item in enumerate(providers)
        if _eligible(item, policy, is_primary=(index == 0))
    ]
    if not eligible:
        raise RuntimeError("No configured provider is eligible under the workflow cost policy")

    last_error: Exception | None = None
    for index, provider in enumerate(eligible):
        request_payload = dict(payload)
        request_payload["model"] = provider["model"]
        try:
            async with httpx.AsyncClient(timeout=timeout) as client:
                response = await client.post(
                    provider["base_url"] + "/chat/completions",
                    headers={"Authorization": f"Bearer {provider['api_key']}"},
                    json=request_payload,
                )
                response.raise_for_status()
                data = response.json()
                if not isinstance(data, dict) or not isinstance(data.get("choices"), list):
                    raise ValueError("Provider returned an invalid chat-completion schema")
                return data, {
                    "provider": provider["provider"],
                    "model": provider["model"],
                    "fallback_used": index > 0,
                    "attempts": index + 1,
                }
        except Exception as exc:
            last_error = exc
            if not _is_transient_error(exc) or index == len(eligible) - 1:
                raise
    if last_error:
        raise last_error
    raise RuntimeError("No provider attempt was made")
