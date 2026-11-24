# KOROUSH-CENTRAL-AI

Private, audit-first GitHub engineering agent. The current repair workflow generates bounded proposals only; it does not write to target repositories or merge changes.

## LLM provider configuration

The existing `LLM_*` configuration remains the default and is preserved. To select AvalAI, set these Railway service variables:

- `LLM_PROVIDER=avalai`
- `AVALAI_BASE_URL=https://api.avalai.ir/v1`
- `AVALAI_API_KEY=<your AvalAI API key>`
- `AVALAI_MODEL=<exact model ID from your AvalAI account/catalog>`

The service calls the OpenAI-compatible `/chat/completions` endpoint. Keep the API key in Railway Variables; never commit it to GitHub or paste it into chat.

To return to the existing provider, set `LLM_PROVIDER=legacy`; the existing `LLM_BASE_URL`, `LLM_API_KEY`, and `LLM_MODEL` values remain available.

After changing Railway variables, redeploy/restart the service and use `/panel` to run the diagnostics check. A successful diagnostic confirms one small live inference request, not every model capability.

Official AvalAI API reference: https://docs.avalai.org/en/api-reference/introduction


## AvalAI multi-capability gateway

The admin panel exposes a fixed, allow-listed JSON gateway for documented AvalAI API surfaces:

- Text/reasoning: Responses and Chat Completions
- Structured intelligence: Decisions, System One and Extraction
- Retrieval: Embeddings and Rerank
- Media: image generation, text-to-speech, OCR and video jobs
- Safety: Moderation

Use `GET /api/avalai/capabilities` to inspect supported routes and transport requirements. Use `POST /api/avalai/execute/{surface}` with an object named `payload` to invoke a JSON surface. The selected model ID is checked against the authenticated `/v1/models` catalog before the request is sent.

The gateway never accepts arbitrary URLs and never returns the AvalAI API key. Provider errors are bounded and returned without request headers. A visible route in the catalog does not guarantee that a particular model or account has access; AvalAI may return an unsupported-route, model-access, quota, or billing error.

### Capabilities that need a different transport

Audio transcription/translation and image editing require multipart file uploads; Files and Batch require file workflows; Realtime audio requires a live session transport. These are listed as capabilities but are intentionally not routed through the JSON endpoint. They require dedicated upload/realtime implementations before they can be called from the panel.

### Cost and safety

AvalAI API calls may consume account credit or incur charges according to the account's model pricing. This gateway does not automatically call every model: the administrator explicitly chooses a surface and model and submits a request. Repository repair remains proposal-only; this feature does not write to audited repositories.

Official references: https://docs.avalai.org/en/api-reference/introduction, /images, /audio, /embeddings, /decisions, /responses.
