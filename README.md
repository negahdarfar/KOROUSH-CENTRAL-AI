# KOROUSH-CENTRAL-AI

Private, audit-first GitHub engineering agent. Audits are read-only. Repair proposals are non-writing; a separate repair-apply endpoint can publish explicitly confirmed changes to a new branch and open a Draft Pull Request. The service never merges a Pull Request automatically.

## LLM provider configuration

The existing `LLM_*` configuration remains the default and is preserved. To select AvalAI, set these Railway service variables:

- `LLM_PROVIDER=avalai`
- `AVALAI_BASE_URL=https://api.avalai.ir/v1`
- `AVALAI_API_KEY=<your AvalAI API key>`
- `AVALAI_MODEL` (optional): leave empty for automatic selection from the authenticated account catalog, or set an exact available model ID.

The service discovers the authenticated `/v1/models` catalog. If `AVALAI_MODEL` is empty, it automatically selects a suitable chat/reasoning model that is actually present in that account catalog. You can still select any returned model explicitly in the admin panel. Keep the API key in Railway Variables; never commit it to GitHub or paste it into chat.

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

AvalAI API calls may consume account credit or incur charges according to the account's model pricing. The router does not send requests to every model simultaneously (which would multiply cost). It exposes every model returned by the account catalog, supports explicit model selection, and automatically chooses one available chat model when no default is configured. Repository audits and proposals are read-only. The separate repair-apply workflow requires an authenticated admin request with `confirm=true`, creates a new branch, updates only inspected existing files, and opens a Draft Pull Request. It does not merge changes. Files containing detected secret redactions or truncated source content are excluded from repair candidates, preventing placeholder text or partial file snapshots from overwriting the original files.

Official references: https://docs.avalai.org/en/api-reference/introduction, /images, /audio, /embeddings, /decisions, /responses.
