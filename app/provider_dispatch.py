"""Provider-neutral OpenAI-compatible dispatch behind exact zero-price evidence."""
from __future__ import annotations

import httpx


RETRYABLE_STATUS_CODES = {408, 425, 429, 500, 502, 503, 504}


def verified_candidates(configs: list[dict], evidence: dict[str, set[str]],
                        *, requested_model: str | None = None) -> list[dict]:
    """Filter provider configs using trusted exact provider/model evidence."""
    result = []
    seen = set()
    for config in configs:
        provider = str(config.get("provider", "")).strip().lower()
        model = str(config.get("model", "")).strip()
        if not provider or not model or (requested_model and model != requested_model):
            continue
        allowed = evidence.get(provider, set())
        if not isinstance(allowed, (set, frozenset)) or model not in allowed:
            continue
        key = (provider, model, str(config.get("base_url", "")).rstrip("/"))
        if key in seen:
            continue
        if not config.get("api_key") or not config.get("base_url"):
            continue
        seen.add(key)
        result.append({**config, "provider": provider, "model": model})
    return result


def _headers(provider: str, api_key: str) -> dict[str, str]:
    headers = {"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"}
    if provider == "openrouter":
        headers["X-Title"] = "KOROUSH CENTRAL AI"
    return headers


async def dispatch_chat_completion(candidates: list[dict], payload: dict, *,
                                   timeout: float = 90) -> tuple[dict, httpx.Response, str, str]:
    """Try only pre-verified candidates; fail closed and retry transient failures only."""
    if not candidates:
        raise RuntimeError("No provider/model pair has trusted exact zero-price evidence")
    last_failure = "unknown transient provider failure"
    async with httpx.AsyncClient(timeout=timeout) as client:
        for config in candidates:
            provider = config["provider"]
            model = config["model"]
            url = config["base_url"].rstrip("/") + "/chat/completions"
            try:
                response = await client.post(
                    url,
                    headers=_headers(provider, config["api_key"]),
                    json={**payload, "model": model},
                )
            except (httpx.TimeoutException, httpx.NetworkError):
                last_failure = f"{provider}: network or timeout error"
                continue
            if response.status_code in RETRYABLE_STATUS_CODES:
                last_failure = f"{provider}: retryable HTTP {response.status_code}"
                continue
            response.raise_for_status()
            data = response.json()
            if not isinstance(data, dict) or not isinstance(data.get("choices"), list):
                raise RuntimeError(f"{provider} returned an invalid chat-completion response")
            return data, response, provider, model
    raise RuntimeError(
        f"All verified free provider attempts failed ({len(candidates)} attempted; "
        f"last failure: {last_failure}). No paid or unknown-price fallback was attempted."
    )
