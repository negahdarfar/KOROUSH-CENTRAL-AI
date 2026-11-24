"""Safe, allow-listed JSON gateway for AvalAI API surfaces.

Binary/multipart and realtime transports are explicitly reported as upload/live
capabilities and are not falsely exposed through this JSON-only endpoint.
"""
from __future__ import annotations

import httpx

from .config import settings
from .avalai import list_avalai_model_catalog
from .model_router import rank_avalai_models
from .usage_ledger import record_usage, normalize_usage
from .quota_guard import reserve_inference, complete_reservation, cancel_reservation


# Only fixed relative paths are allowed. Callers cannot choose arbitrary URLs.
JSON_SURFACES = {
    "responses": {"path": "/responses", "group": "text_reasoning", "description": "Responses, reasoning, multimodal input and tool workflows"},
    "chat_completions": {"path": "/chat/completions", "group": "text_reasoning", "description": "Chat and compatible text/vision model workflows"},
    "decisions": {"path": "/decisions", "group": "decision", "description": "Typed decisions, classifications and scoring"},
    "systemone": {"path": "/systemone", "group": "decision", "description": "Named questions over shared state"},
    "extraction": {"path": "/extraction", "group": "structured_data", "description": "Typed extraction, estimates and forecasts"},
    "embeddings": {"path": "/embeddings", "group": "retrieval", "description": "Text and documented multimodal embeddings"},
    "images_generations": {"path": "/images/generations", "group": "image", "description": "Image generation"},
    "audio_speech": {"path": "/audio/speech", "group": "audio", "description": "Text-to-speech generation"},
    "moderations": {"path": "/moderations", "group": "safety", "description": "Text moderation"},
    "rerank": {"path": "/rerank", "group": "retrieval", "description": "Document reranking"},
    "ocr": {"path": "/ocr", "group": "documents", "description": "Optical character recognition, subject to account route availability"},
    "videos": {"path": "/videos", "group": "video", "description": "Video generation jobs, subject to account/model availability"},
}

UPLOAD_CAPABILITIES = [
    {"name": "audio_transcriptions", "path": "/audio/transcriptions", "group": "audio", "transport": "multipart_upload", "description": "Speech-to-text; requires audio file upload"},
    {"name": "audio_translations", "path": "/audio/translations", "group": "audio", "transport": "multipart_upload", "description": "Audio translation; requires audio file upload"},
    {"name": "images_edits", "path": "/images/edits", "group": "image", "transport": "multipart_upload", "description": "Image editing; requires image file upload"},
    {"name": "files", "path": "/files", "group": "files", "transport": "multipart_upload", "description": "File upload and management"},
]

CAPABILITY_CATALOG = [
    {"name": name, **details, "transport": "json"}
    for name, details in JSON_SURFACES.items()
] + UPLOAD_CAPABILITIES + [
    {"name": "realtime_audio", "path": None, "group": "audio", "transport": "realtime", "description": "Live low-latency audio; enable only when AvalAI account has a matching realtime route"},
    {"name": "batch", "path": "/batches", "group": "jobs", "transport": "json_plus_file", "description": "Batch processing; requires prior JSONL file upload"},
]


async def execute_avalai_surface(surface: str, payload: dict, repository: str | None = None) -> dict:
    """Send one JSON request to a fixed AvalAI route; never accept a caller URL."""
    if surface not in JSON_SURFACES:
        raise ValueError("Unsupported or non-JSON AvalAI capability")
    llm = settings.active_llm
    if llm["provider"] != "avalai" or not llm["api_key"] or not llm["base_url"]:
        raise RuntimeError("AvalAI provider is not configured")

    body = dict(payload)
    model = body.get("model")
    catalog = await list_avalai_model_catalog()
    eligible = rank_avalai_models(catalog, task="general", free_only=True, allow_unknown_cost=False, allow_paid=False)
    eligible_ids = {item["id"] for item in eligible}
    if model is not None:
        if not isinstance(model, str) or not model.strip():
            raise ValueError("Model must be a non-empty model ID")
        if model not in eligible_ids:
            raise ValueError("Requested model is blocked: zero-dollar policy permits only catalog-confirmed free models")
    else:
        configured = llm.get("model")
        if configured:
            if configured not in eligible_ids:
                raise ValueError("AVALAI_MODEL is blocked by the zero-dollar policy; clear it or choose a catalog-confirmed free model")
            model = configured
        else:
            if not eligible:
                raise RuntimeError("No catalog-confirmed free chat model is available under the zero-dollar policy")
            model = eligible[0]["id"]
        body["model"] = model

    route = JSON_SURFACES[surface]["path"]
    url = llm["base_url"].rstrip("/") + route
    timeout = httpx.Timeout(180.0, connect=20.0)
    reservation_id = reserve_inference(repository, body)
    try:
        async with httpx.AsyncClient(timeout=timeout) as client:
            response = await client.post(
                url,
                headers={"Authorization": f"Bearer {llm['api_key']}", "Content-Type": "application/json"},
                json=body,
            )
            if not response.is_success:
                detail = response.text[:3000]
                raise AvalAIRequestError(response.status_code, detail)
            try:
                data = response.json()
            except ValueError as exc:
                raise RuntimeError("AvalAI returned a non-JSON response on a JSON surface") from exc
            request_id = response.headers.get("avalai-request-id") or response.headers.get("x-request-id") or data.get("id")
            prompt_tokens, completion_tokens, total_tokens = normalize_usage(data.get("usage"))
            record_usage(repository=repository, provider="avalai", model=model, surface=surface,
                         usage=data.get("usage"), provider_request_id=request_id)
            complete_reservation(reservation_id, total_tokens or prompt_tokens + completion_tokens)
            reservation_id = None
            return {
                "provider": "avalai",
                "surface": surface,
                "model": model,
                "request_id": response.headers.get("avalai-request-id") or response.headers.get("x-request-id"),
                "result": data,
            }
    finally:
        if reservation_id:
            cancel_reservation(reservation_id)


class AvalAIRequestError(Exception):
    def __init__(self, status_code: int, detail: str):
        self.status_code = status_code
        self.detail = detail
        super().__init__(f"AvalAI returned HTTP {status_code}")
