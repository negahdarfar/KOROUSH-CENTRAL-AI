# KOROUSH-CENTRAL-AI

Private, audit-first GitHub engineering agent. Audits are read-only. Repair proposals are non-writing; a two-step repair workflow first creates a non-writing preview, then publishes only the exact reviewed preview after explicit confirmation to a new branch and Draft Pull Request. The service never merges a Pull Request automatically.

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

AvalAI API calls may consume account credit or incur charges according to the account's model pricing. The router does not send requests to every model simultaneously (which would multiply cost). It exposes every model returned by the account catalog, supports explicit model selection, and automatically chooses one available chat model when no default is configured. Repository audits and proposals are read-only. The repair workflow uses `POST /api/fix-preview/{owner}/{repo}` to produce complete replacement files and a digest bound to the task, repository, and source-file SHAs. After review, `POST /api/fix-apply/{owner}/{repo}` requires `confirm=true`, the unchanged preview, source SHAs, and matching digest. The service rechecks source SHAs before writing and uses the same GitHub content SHAs in its updates to reject concurrent source changes. It does not merge changes. Files containing detected secret redactions or truncated source content are excluded from repair candidates, preventing placeholder text or partial file snapshots from overwriting the original files.

Official references: https://docs.avalai.org/en/api-reference/introduction, /images, /audio, /embeddings, /decisions, /responses.


## Evidence-aware AvalAI model intelligence

The admin panel can inspect selected account models in batches of up to 25 using `POST /api/avalai/models/inspect`. Each model detail lookup is bounded to five concurrent requests and uses a per-request timeout. The inspection endpoint first verifies every requested ID against the authenticated `/v1/models` catalog.

Capability labels distinguish provider metadata (verified evidence) from model-name hints (inference). Missing pricing is reported as unknown; account tier is never treated as proof that a model is free. The panel advances through the catalog in small batches so the operator controls provider load. Inspection is metadata-only and does not run paid inference benchmarks.

The JSON capability gateway validates model availability against the lightweight catalog only; it does not fetch detail metadata for all account models on every request.


## Team- and repository-aware model routing

The router ranks the authenticated AvalAI catalog by explicit pricing evidence before task preferences: models whose returned pricing is explicitly zero rank first, unknown-price models rank next, and paid models rank last. Missing pricing is never labelled free. Coding repairs use the coding route; audits use the general route unless a more specific repository policy overrides it.

Optional Railway variable `KOROUSH_WORKFLOW_POLICIES` accepts JSON. Resolution order is defaults → team → exact repository, with repository settings taking precedence:

```json
{
  "defaults": {
    "provider_order": ["avalai"],
    "free_first": true,
    "free_only": false,
    "allow_unknown_cost": true,
    "allow_paid": false,
    "max_retries": 1,
    "task": "general"
  },
  "teams": {
    "quant": {"task": "research", "allow_unknown_cost": false},
    "engineering": {"task": "coding"}
  },
  "repositories": {
    "negahdarfar/example-private": {"task": "coding", "allow_paid": true}
  }
}
```

Supported task classes: `general`, `coding`, `vision`, `fast`, `reasoning`, and `research`. Invalid JSON fails closed to safe defaults. Do not enable paid models until an intentional budget and provider-side spending controls are configured.

## OpenAI-compatible provider adapters and guarded failover

The agent's audit and repair-generation chat calls now use a shared adapter for the active provider plus explicitly configured fallback providers. Supported fallback environment-variable groups are:

- OpenRouter: `OPENROUTER_API_KEY`, `OPENROUTER_MODEL`, optional `OPENROUTER_BASE_URL` (defaults to `https://openrouter.ai/api/v1`), and `OPENROUTER_COST_CLASS`.
- FreeLLMAPI: `FREELLMAPI_API_KEY`, `FREELLMAPI_MODEL`, `FREELLMAPI_BASE_URL`, and `FREELLMAPI_COST_CLASS`.
- Gemini OpenAI-compatible endpoint: `GEMINI_API_KEY`, `GEMINI_MODEL`, optional `GEMINI_BASE_URL` (defaults to `https://generativelanguage.googleapis.com/v1beta/openai`), and `GEMINI_COST_CLASS`.

Add provider names to `provider_order` in `KOROUSH_WORKFLOW_POLICIES` to make them eligible for fallback. The `*_COST_CLASS` value must be declared as `free`, `unknown`, or `paid`; omitted values default to `unknown`. Paid providers are blocked unless that workflow explicitly sets `allow_paid: true`. Unknown-cost fallback providers are blocked unless both `allow_unknown_cost: true` and `KOROUSH_ALLOW_UNKNOWN_PROVIDER_FALLBACK=true` are set. For a strict free-only workflow, set `free_only: true` and declare only providers whose selected model is confirmed free.

Failover occurs only for timeouts, network errors, HTTP 408/409/425/429, or 5xx responses. Authentication errors, invalid requests, and other 4xx responses are not retried against another provider. Credentials are read from Railway variables and are never returned in provider metadata. Provider model IDs and cost classes are operator-supplied for non-AvalAI adapters; the service does not independently verify their price or availability.

**Remaining scope:** this adapter currently covers agent chat-completion calls, not every AvalAI-specific media/capability gateway route. Team identity propagation, durable background queues, per-team usage accounting, hard budget ledgers, and live provider/model benchmarking are still future phases.
