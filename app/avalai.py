import asyncio
import httpx

from .config import settings


_DETAIL_FIELDS = (
    "mode",
    "supports_vision",
    "supports_function_calling",
    "max_input_tokens",
    "max_output_tokens",
    "context_length",
    "pricing",
    "min_tier",
    "description",
    "capabilities",
)


def extract_model_catalog(payload: dict) -> list[dict]:
    """Extract a safe, lightweight view of the authenticated account catalog."""
    raw_models = payload.get("data") if isinstance(payload, dict) else None
    if not isinstance(raw_models, list):
        raw_models = []
    models = []
    for item in raw_models:
        if not isinstance(item, dict) or not isinstance(item.get("id"), str) or not item["id"].strip():
            continue
        model = {"id": item["id"], "owned_by": item.get("owned_by"), "mode": item.get("mode")}
        for field in ("created", "object", "context_length", "pricing", "min_tier"):
            if field in item:
                model[field] = item[field]
        models.append(model)
    return models


async def _active_avalai_config() -> tuple[dict, dict]:
    llm = settings.active_llm
    if llm["provider"] != "avalai" or not llm["api_key"] or not llm["base_url"]:
        raise RuntimeError("AvalAI provider is not configured")
    return llm, {"Authorization": f"Bearer {llm['api_key']}"}


async def list_avalai_model_catalog() -> list[dict]:
    """Fetch the authenticated model catalog with one request for fast diagnostics."""
    llm, headers = await _active_avalai_config()
    async with httpx.AsyncClient(timeout=httpx.Timeout(12.0, connect=5.0)) as client:
        response = await client.get(f"{llm['base_url']}/models", headers=headers)
        response.raise_for_status()
        return extract_model_catalog(response.json())


def _detail_metadata(payload: dict) -> dict:
    """Normalize only documented/known metadata fields; never expose arbitrary payloads."""
    if not isinstance(payload, dict):
        return {}
    extra = payload.get("extra", {})
    metadata = extra.get("metadata", extra) if isinstance(extra, dict) else {}
    if not isinstance(metadata, dict):
        metadata = {}
    merged = dict(payload)
    merged.update(metadata)
    return {key: merged[key] for key in _DETAIL_FIELDS if key in merged}


async def inspect_avalai_models(model_ids: list[str], max_concurrency: int = 5) -> list[dict]:
    """Inspect at most 25 caller-selected models with bounded concurrency and per-model timeouts."""
    if not model_ids or len(model_ids) > 25:
        raise ValueError("Provide between 1 and 25 model IDs per inspection batch")
    clean_ids = []
    seen = set()
    for model_id in model_ids:
        if not isinstance(model_id, str) or not model_id.strip() or len(model_id) > 200:
            raise ValueError("Every model ID must be a non-empty string of at most 200 characters")
        if model_id not in seen:
            clean_ids.append(model_id)
            seen.add(model_id)

    llm, headers = await _active_avalai_config()
    semaphore = asyncio.Semaphore(max(1, min(max_concurrency, 5)))
    timeout = httpx.Timeout(12.0, connect=5.0)

    async with httpx.AsyncClient(timeout=timeout) as client:
        async def inspect_one(model_id: str) -> dict:
            async with semaphore:
                try:
                    response = await client.get(
                        f"{llm['base_url']}/models/{model_id}",
                        headers=headers,
                    )
                    if response.status_code == 404:
                        return {"id": model_id, "details_available": False, "status": "not_found"}
                    response.raise_for_status()
                    payload = response.json()
                    metadata = _detail_metadata(payload)
                    return {
                        "id": model_id,
                        "details_available": bool(metadata),
                        "status": "ok" if metadata else "metadata_empty",
                        **metadata,
                    }
                except httpx.TimeoutException:
                    return {"id": model_id, "details_available": False, "status": "timeout"}
                except httpx.HTTPStatusError as exc:
                    return {
                        "id": model_id,
                        "details_available": False,
                        "status": "http_error",
                        "http_status": exc.response.status_code,
                    }
                except (httpx.HTTPError, ValueError):
                    return {"id": model_id, "details_available": False, "status": "invalid_response"}

        results = await asyncio.gather(*(inspect_one(model_id) for model_id in clean_ids))
    return results


async def list_avalai_models() -> list[dict]:
    """Compatibility helper: inspect the full catalog in bounded batches."""
    catalog = await list_avalai_model_catalog()
    results = []
    for start in range(0, len(catalog), 25):
        batch = catalog[start:start + 25]
        results.extend(await inspect_avalai_models([item["id"] for item in batch]))
    return sorted(results, key=lambda item: item["id"].lower())
