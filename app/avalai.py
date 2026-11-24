import asyncio
import httpx

from .config import settings


async def list_avalai_models() -> list[dict]:
    """Return the authenticated AvalAI catalog with per-model capability metadata."""
    llm = settings.active_llm
    if llm["provider"] != "avalai" or not llm["api_key"] or not llm["base_url"]:
        raise RuntimeError("AvalAI provider is not configured")

    headers = {"Authorization": f"Bearer {llm['api_key']}"}
    timeout = httpx.Timeout(30.0)
    async with httpx.AsyncClient(timeout=timeout) as client:
        response = await client.get(f"{llm['base_url']}/models", headers=headers)
        response.raise_for_status()
        payload = response.json()

        raw_models = payload.get("data", []) if isinstance(payload, dict) else []
        models = [item for item in raw_models if isinstance(item, dict) and isinstance(item.get("id"), str)]
        semaphore = asyncio.Semaphore(8)

        async def enrich(item: dict) -> dict:
            model_id = item["id"]
            result = {
                "id": model_id,
                "owned_by": item.get("owned_by"),
                "mode": None,
                "supports_vision": None,
                "supports_function_calling": None,
                "max_input_tokens": None,
                "max_output_tokens": None,
                "details_available": False,
            }
            async with semaphore:
                try:
                    detail = await client.get(
                        f"{llm['base_url']}/models/{model_id}",
                        headers=headers,
                    )
                    if detail.is_success:
                        data = detail.json()
                        extra = data.get("extra", {}) if isinstance(data, dict) else {}
                        metadata = extra.get("metadata", extra) if isinstance(extra, dict) else {}
                        if isinstance(metadata, dict):
                            result.update({
                                "mode": metadata.get("mode"),
                                "supports_vision": metadata.get("supports_vision"),
                                "supports_function_calling": metadata.get("supports_function_calling"),
                                "max_input_tokens": metadata.get("max_input_tokens"),
                                "max_output_tokens": metadata.get("max_output_tokens"),
                                "details_available": True,
                            })
                except (httpx.HTTPError, ValueError):
                    pass
            return result

        enriched = await asyncio.gather(*(enrich(item) for item in models))
    return sorted(enriched, key=lambda item: item["id"].lower())
