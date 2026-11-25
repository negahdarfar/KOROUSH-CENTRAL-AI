# KOROUSH-CENTRAL-AI

Private, audit-first GitHub engineering agent. Audits are read-only. Repair proposals are non-writing; a two-step repair workflow first creates a non-writing preview, then publishes only the exact reviewed preview after explicit confirmation to a new branch and Draft Pull Request. The service never merges a Pull Request automatically.

## LLM provider configuration

The existing `LLM_*` configuration remains the default and is preserved. To select AvalAI, set these Railway service variables:

- `LLM_PROVIDER=avalai`
- `AVALAI_BASE_URL=https://api.avalai.ir/v1`
- `AVALAI_API_KEY=<your AvalAI API key>`
- `AVALAI_MODEL` (optional): leave empty for automatic selection from the authenticated account catalog, or set an exact available model ID.

The service discovers the authenticated `/v1/models` catalog. In the zero-dollar mode, only chat-capable models whose authenticated pricing metadata explicitly reports zero input and output cost are eligible. Missing or ambiguous pricing is blocked. The admin panel can inspect metadata without running inference. Keep the API key in Railway Variables; never commit it to GitHub or paste it into chat.

To return to the existing provider, set `LLM_PROVIDER=legacy`; the existing `LLM_BASE_URL`, `LLM_API_KEY`, and `LLM_MODEL` values remain available.

After changing Railway variables, redeploy/restart the service and use `/panel` to run diagnostics. Under the zero-dollar policy, diagnostics are metadata-only and do not send an inference request.

Official AvalAI API reference: https://docs.avalai.org/en/api-reference/introduction


## AvalAI multi-capability gateway

The admin panel documents a fixed, allow-listed JSON gateway for AvalAI API surfaces. Under the strict USD 0.00 policy, only Chat Completions is currently executable; other surfaces are blocked until their own surface-specific zero-price evidence is independently verified:

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


## Zero-dollar guard and usage ledger

The global inference policy is USD 0.00: only models whose authenticated catalog metadata explicitly reports zero pricing are eligible. Unknown-price and paid models are blocked. Metadata-only diagnostics do not send inference requests.

Successful inference calls made through the agent and the JSON capability gateway are recorded in a SQLite usage ledger, grouped by repository and day/month. Token counts come from provider usage metadata; missing usage values remain zero and are never guessed. Calls without an explicit repository identity are rejected before inference; the ledger does not accept unassigned usage. The admin-only `GET /api/usage` endpoint returns aggregate totals and does not expose prompts or responses.

**Railway persistence requirement:** attach a Railway Volume to the service with mount path `/data` and set `USAGE_DB_PATH=/data/koroush_usage.sqlite3`. Without a mounted volume, SQLite data may be lost when Railway replaces the container. The ledger is accounting/observability, not a provider quota guarantee; free-tier quotas remain subject to provider limits and can change independently of price metadata.

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

**Current scope:** the global zero-dollar guard, AvalAI free-model failover, SQLite usage ledger, and per-repository preflight quotas are implemented in this draft branch. They are not active in production until the PR is reviewed, merged, and the Railway volume is configured. Multi-provider routing beyond catalog-verified AvalAI models, authenticated tenant identity, and durable background jobs remain future work.


### Per-repository preflight quotas and alerts

Every agent and permitted JSON-gateway inference reserves capacity atomically in SQLite before contacting AvalAI. Both agent inference and gateway inference require a non-empty `ALLOWED_REPOS` operator allowlist and an exact approved `owner/repository` identity; caller-supplied arbitrary repository names are rejected before model-catalog or inference requests. Quota keys are normalized to lowercase, and malformed repository identities fail closed. Cancelled/failed attempts release their reservation; successful calls replace the conservative token reservation with provider-reported token usage when available. Stale pending reservations expire after 15 minutes.

Project safety defaults (not AvalAI's published free-tier limits) are:

- 20 requests per repository per day
- 400 requests per repository per month
- 20,000 reserved/used tokens per repository per day
- 200,000 reserved/used tokens per repository per month

Override limits with the Railway variable `KOROUSH_REPO_QUOTAS`, a JSON object keyed by exact lowercase `owner/repo` or `*` fallback. Supported integer keys: `requests_per_day`, `requests_per_month`, `tokens_per_day`, `tokens_per_month`. Invalid configuration fails closed. A conservative prompt/output-token estimate is reserved before the provider call; actual provider usage replaces it after success. If the provider omits usage metadata, the estimate is not represented as actual usage in the usage ledger.

Threshold alerts are deduplicated at 70%, 85%, and 100%. Admin-only `GET /api/usage/alerts` returns recorded alerts; `GET /api/usage` continues to expose actual usage aggregates. Alerts are currently API-visible only; no Telegram/email delivery is configured. Quotas are internal project safeguards, not a guarantee of provider-side free quota or a hard provider billing ceiling.


## Security and quality gates

- CodeQL analyzes Python on pushes, pull requests, and a weekly schedule.
- Dependabot checks Python dependencies and GitHub Actions weekly.
- A concurrency regression test verifies that simultaneous requests cannot overbook a repository's request quota.
- These checks supplement, but do not replace, review of Railway permissions, repository access controls, secret rotation, and production configuration.

## Production activation checklist

1. Review and merge only after CI and CodeQL complete successfully.
2. Attach a persistent Railway Volume mounted at `/data`.
3. Set `USAGE_DB_PATH=/data/koroush_usage.sqlite3`.
4. Verify the mounted path is writable and usage survives a Railway restart.
5. Confirm the active model catalog contains at least one chat model with explicit zero input and output pricing.
6. Verify `/api/usage` and `/api/usage/alerts` with the admin key; never expose the admin key in client-side source or logs.
7. Verify `/api/version` reports the expected production commit before declaring activation complete.

The internal quota is a conservative project safeguard. It is not a provider-side billing cap and cannot guarantee that an upstream free tier will remain available or free.


### Strict gateway restrictions

The USD 0.00 gateway currently permits only `chat_completions`, because the authenticated model catalog's input/output token pricing does not prove that image, audio, video, OCR, reranking, embeddings, or other specialized API surfaces are free. Those routes remain documented but blocked until reliable surface-specific zero-price evidence and dedicated tests exist.

Set Railway `ALLOWED_REPOS` to a comma-separated list of approved `owner/repository` identities before enabling any agent or gateway inference, for example `org/project-a,org/project-b`. If the allowlist is empty, all inference paths fail closed. This allowlist is an operator approval boundary, not end-user authentication; keep the admin API key private.


## Safe provider-adapter integration

The provider adapter registry from PR19 is integrated behind the PR20 zero-dollar guard. A provider's self-declared `*_COST_CLASS=free` value is not accepted as proof of zero price. Every exact provider/model pair must be present in a trusted runtime-verified free-model evidence map before it can be dispatched. At present, that evidence is supplied only by the authenticated AvalAI model catalog; OpenRouter, FreeLLMAPI, and Gemini adapters remain configured-but-blocked until an independent zero-price verification source and tests are implemented. All permitted agent calls continue through the repository allowlist, atomic quota reservation, and usage-ledger lifecycle. No provider fallback may bypass those controls.


## Team-scoped API keys

The draft adds a separate tenant API-key layer for inference access. An administrator creates a key through `POST /api/admin/tenant-keys` using `X-Admin-Key`, with `user_id`, `team_id`, an explicit repository list, and the `inference:chat` scope. The raw key is returned once; only an HMAC-SHA256 digest is stored in SQLite. Set `TENANT_AUTH_PEPPER` to a high-entropy secret of at least 32 characters before creating or using tenant keys. Losing or rotating this pepper invalidates existing keys; plan a controlled key re-issuance process.

Tenant inference uses `X-Tenant-Key` on `POST /api/avalai/execute/chat_completions`. The repository in the request must belong to that key and is still checked against the operator-controlled `ALLOWED_REPOS` allowlist and internal quota ledger. A repository can be assigned to only one team. Administrators can list key metadata at `GET /api/admin/tenant-keys` and revoke a key at `POST /api/admin/tenant-keys/{key_id}/revoke`. Raw secrets are never returned by list/revoke endpoints. The existing admin key remains required for management and all other admin endpoints.

This is API-key authentication and repository-level tenant isolation, not a full interactive user identity provider: there is no password login, SSO/OIDC, MFA, invitation workflow, or fine-grained role editor in this phase. Protect `ADMIN_API_KEY` and `TENANT_AUTH_PEPPER` as production secrets. Configure the Railway Volume at `/data` before relying on key persistence.

## Automatic Telegram and email quota alerts

The draft includes a background worker that polls deduplicated quota threshold alerts. Telegram delivery requires `TELEGRAM_BOT_TOKEN` and `TELEGRAM_CHAT_ID`. Email delivery requires `SMTP_HOST`, `SMTP_FROM`, and `SMTP_TO`; optional settings are `SMTP_PORT` (default 587), `SMTP_USERNAME`, `SMTP_PASSWORD`, and `SMTP_USE_TLS` (default true). `ALERT_POLL_SECONDS` controls polling and is bounded to 15–3600 seconds.

Delivery attempts are tracked in SQLite by alert ID and channel to prevent duplicate sends; failed attempts can be retried on a later worker cycle. The admin-only `POST /api/usage/alerts/dispatch` endpoint also triggers a delivery pass. No credentials are required if notifications are not enabled; in that case the worker remains idle. Secrets are read from environment variables and are not exposed by status responses. Delivery depends on Telegram/SMTP availability and provider policies; it is not a guaranteed emergency paging service.


## Central AI Agent Hub

This service is the shared control plane for connected repositories. See [docs/CENTRAL_AGENT_HUB.md](docs/CENTRAL_AGENT_HUB.md) for the agent catalog, tenant integration contract, Python SDK, onboarding requirements, migration strategy, and current limitations. Discovery endpoints are `GET /api/platform/manifest` and tenant-scoped `GET /api/agents?repository=owner/repository`.


## Live resource discovery

The admin-only `POST /api/admin/discovery/search` endpoint searches public GitHub repository metadata with bounded terms, recency, result counts, timeouts, and response size. It returns ranked candidates and evidence gaps; it does not install, execute, or register external code. All pricing remains unverified until an administrator validates the official publisher and terms. See [docs/INTELLIGENT_DISCOVERY_ENGINE_V1_1.md](docs/INTELLIGENT_DISCOVERY_ENGINE_V1_1.md).


## Unified multi-agent workflows and four domain adapters

The central service now exposes fixed, bounded research workflows for Forex, YouTube, PTC and NFT through `POST /api/integrations/{domain}/research`. Each workflow runs evidence-grounded research, domain classification and synthesis through the encrypted durable queue, with optional translation. Python and Node SDKs provide `submit_domain_research` / `submitDomainResearch`. These are research/drafting integrations only: trading, public publishing, automated clicking, wallet signing and payouts remain disabled.

The model router records secret-free provider latency, success and HTTP 429 telemetry and uses it with task-fit preference when ranking eligible models. The strict USD 0.00 eligibility guard remains first; telemetry cannot make a paid or unknown-price model eligible. Admins can inspect aggregates at `GET /api/models/performance`. A model quality score is used only when explicitly backed by verified benchmark evidence; otherwise quality is reported as not measured.

See [Unified Agent and Domain Routing](docs/UNIFIED_AGENT_DOMAIN_ROUTING.md) for endpoint payloads, SDK examples, security boundaries and downstream activation steps. The central API and SDKs are executable, but each remote repository still requires its own tenant secret/configuration and an authenticated end-to-end verification before it can be called connected.


## Future repository onboarding without central code changes

A new repository can use the generic registered connector contract rather than requiring a new hard-coded adapter. An administrator approves the exact repository, issues a tenant key scoped to that repository, and registers a versioned connector manifest with the capability `research.workflow.v1` and domain `general`. The repository then calls `submit_integration_research` (Python) or `submitIntegrationResearch` (Node) through the same encrypted durable queue and fixed research/classification/synthesis workflow. The tenant key must include `jobs:enqueue`, `jobs:read`, and `inference:chat`; registry discovery additionally requires `registry:read` and uses `GET /api/extensions?repository=owner/repository&kind=connector`. The public `GET /api/integrations` endpoint lists only the four built-in profiles.

This no-code path supports evidence-based research and optional translation. It does not execute downloaded plugin code, arbitrary remote endpoints, trading, publishing, wallet operations, or other privileged actions. New specialized behavior still requires reviewed central code. See the onboarding section in [docs/UNIFIED_AGENT_DOMAIN_ROUTING.md](docs/UNIFIED_AGENT_DOMAIN_ROUTING.md).
