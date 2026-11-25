# Unified agents, domain integrations and model routing

## 1. Fixed multi-agent execution

The durable worker now registers `agent.workflow`. Workflow definitions are code-owned and cannot be supplied by a tenant. The four fixed graphs execute in order:

1. `koroush.research-brief` — evidence-grounded analysis with source IDs and provenance fingerprints.
2. `koroush.text-classifier` — domain-specific finite-label classification.
3. `koroush.text-summarizer` — final concise report.
4. Optional `koroush.text-translator` — only when `target_language` is provided.

Each inference reuses the central free-model eligibility, repository quota reservation, usage ledger and tenant authorization. A workflow therefore uses three model calls by default and at most four with translation. The workflow is sequential by design: it avoids uncontrolled parallel provider bursts and preserves explicit step ordering. Failed steps fail the job; a partial result is not reported as a successful workflow.

## 2. Downstream repository API

The four research-only endpoints are:

- `POST /api/integrations/forex/research`
- `POST /api/integrations/youtube/research`
- `POST /api/integrations/ptc/research`
- `POST /api/integrations/nft/research`

All use the same tenant header and encrypted durable queue. The tenant key must be assigned to the exact `owner/repository` and include `jobs:enqueue`, `jobs:read`, and `inference:chat`. The enqueue endpoint requires all three because it returns a tenant-scoped result URL. Retrieve job results through `GET /api/jobs/{job_id}?repository=owner/repository`.

Example request:

```http
POST /api/integrations/forex/research
X-Tenant-Key: kor_...
Content-Type: application/json
```

```json
{
  "repository": "negahdarfar/daily-forex-analyze",
  "idempotency_key": "daily-brief-2026-11-25",
  "target_language": "Persian",
  "evidence": [
    {
      "source_id": "source-001",
      "publisher": "Example publisher",
      "source_url": "https://example.org/report",
      "observed_at": "2026-11-25T00:00:00Z",
      "text": "Caller-supplied evidence excerpt."
    }
  ],
  "max_attempts": 3
}
```

Evidence must be supplied by the caller (1–8 items). The central workflow does not browse the web or fetch arbitrary URLs. Source URLs are provenance metadata only; they are not fetched. Use a stable idempotency key for safe retries.

Python and Node SDKs expose `submit_domain_research` / `submitDomainResearch`. Each downstream repository still needs its own tenant key, central base URL and SDK/client integration; publishing these endpoints does not silently modify or connect the four remote repositories.

## 3. Safety boundaries

These workflows are research/drafting only:
- Forex: no broker credentials, live orders, position management or executable trade instructions.
- YouTube: no channel OAuth exposure, channel mutation or public publishing.
- PTC: no login, clicking, CAPTCHA bypass or payout actions.
- NFT: no wallet signing, marketplace listing, custody or on-chain transactions.

The endpoint does not claim that a research label is a verified probability or a guaranteed recommendation.

## 4. Model selection and observed performance

The router continues to apply the USD 0.00 policy before performance ranking: paid and unknown-price models are excluded from the strict free path. Within the eligible cost class, the score combines:
- task-fit preference (35%);
- observed successful-call rate (30%);
- observed latency EWMA (20%);
- observed HTTP 429 rate (15%).

Runtime observations remain neutral until a model has at least three attempts. Each provider attempt records only provider/model IDs, latency, success/failure and HTTP status; prompts, responses and credentials are not stored in the telemetry table. The EWMA uses 30% of the latest latency and 70% of the prior value.

A benchmark-quality score is included only when provider metadata explicitly supplies a numeric score and `quality_evidence=verified_benchmark`. The system does not infer answer quality from speed or model names. In the absence of verified benchmarks, the quality field remains `not_measured`.

The admin-only `GET /api/models/performance` endpoint exposes aggregated runtime metrics. Existing repository quota reservations remain the hard preflight control; HTTP 429 observations reduce a model's quota-health score and trigger the existing retry/failover path.

## 5. Activation requirements

1. Configure the durable worker and encrypted payload storage using the existing production checklist.
2. Create a tenant key for each downstream repository with `jobs:enqueue`, `jobs:read`, and `inference:chat`.
3. Add the central API URL and tenant key to the downstream repository's secret store (never commit keys).
4. Install/use the Python or Node SDK method and send evidence records with unique source IDs and timestamps.
5. Confirm the returned job reaches `succeeded` and inspect its result via the tenant-scoped status endpoint.

The code path is now executable in the central repository, but a downstream repository is not considered connected until its own client configuration and a successful authenticated end-to-end job are verified.


## 6. Future repositories: register once, no central code change

The four built-in adapters remain available. A fifth, tenth or later repository does not need a new route, Python handler, workflow graph or SDK release for the shared general-research capability. It uses the generic domain `general` and a versioned connector manifest.

### One-time onboarding (admin-controlled)

1. Approve the exact GitHub identity `owner/repository` and create a tenant key scoped to that repository. Minimum scopes: `jobs:enqueue`, `jobs:read`, `inference:chat`. Store the key only in that repository's GitHub Actions secrets or deployment secret store.
2. Register a connector manifest through `POST /api/extensions` with `X-Admin-Key`. Example:

```json
{
  "manifest": {
    "extension_id": "acme.future-project",
    "version": "1.0.0",
    "kind": "connector",
    "name": "Future Project Adapter",
    "protocol": "koroush-research-v1",
    "capabilities": ["research.workflow.v1"],
    "domains": ["general"],
    "repositories": ["acme/future-project"],
    "description": "Uses the shared evidence research workflow",
    "input_schema": {"type": "object"},
    "output_schema": {"type": "object"},
    "pricing": {"status": "unverified"}
  }
}
```

3. The new repository uses the generic SDK method `submit_integration_research` (Python) or `submitIntegrationResearch` (Node), passing `integration_id="acme.future-project"`, evidence, and a stable idempotency key.
4. The central service validates that the extension is active, has the `research.workflow.v1` capability, declares the `general` domain, and explicitly lists that exact repository. It then routes the request through the same encrypted queue, quota guard and three-agent workflow (four calls if translation is requested).
5. Read the result with the tenant-scoped job status endpoint.

The public `GET /api/integrations` endpoint lists only the four stable built-in profiles. Registered connectors are deliberately excluded from global discovery and are visible only through tenant-scoped `GET /api/extensions?repository=owner/repository&kind=connector` with `registry:read`. Extension versions are immutable; publish a new semantic version for contract metadata changes.

### Important boundary

This zero-code onboarding applies to the shared evidence → classification → summary → optional translation workflow. The central service does not download or execute plugin code, call arbitrary manifest endpoints, or trust a connector merely because it is registered. New specialized execution logic, new privileged operations, or a new external protocol still requires a reviewed central implementation and tests. A manifest is a discovery/authorization contract, not executable code, not proof of safety, and not proof of free pricing.

The central API cannot create or safely distribute tenant credentials on behalf of an unreviewed repository. Repository approval and tenant-key issuance remain explicit administrator actions. Never place `X-Admin-Key` in a downstream repository.


### Tenant-key provisioning example

After setting `TENANT_AUTH_PEPPER` and `ADMIN_API_KEY` on the central deployment, an administrator provisions a key for the exact repository with:

```http
POST /api/admin/tenant-keys
X-Admin-Key: <admin secret>
Content-Type: application/json
```

```json
{
  "user_id": "future-project-adapter",
  "team_id": "approved-team",
  "repositories": ["owner/repository"],
  "scopes": ["jobs:enqueue", "jobs:read", "inference:chat"]
}
```

The API returns the raw tenant key once. Copy it directly into the target repository's GitHub Actions secret named `KOROUSH_CENTRAL_TENANT_KEY`; do not paste it into chat, commit it, or add it to logs. The central base URL goes into `KOROUSH_CENTRAL_BASE_URL`. Revoke and reissue a key if it is exposed.


## 7. Dynamic market-data source registry (metadata contract)

The extension registry already accepts `kind=data_source` and supports tenant-scoped discovery through:

```http
GET /api/extensions?repository=owner/repository&kind=data_source
X-Tenant-Key: <repository-scoped tenant key>
```

The tenant key must include `registry:read`. Registration remains admin-only through `POST /api/extensions` with `X-Admin-Key`. A source manifest is metadata only; the central service does not fetch the endpoint, proxy market data, execute provider code, or attest to licensing, correctness, or zero price.

For the Forex OHLC v1 contract, register:
- `kind=data_source`
- `protocol=koroush-market-data-v1`
- `capabilities=["market.ohlc.v1"]`
- `domains=["forex"]` (or `["general"]` for an explicitly general source)
- Exact repository allowlist, e.g. `["negahdarfar/daily-forex-analyze-"]`
- HTTPS `endpoint` on the default port, with no embedded credentials
- `pricing={"cost_usd":0,"zero_cost_attested_by_admin":true,"source_reviewed_by_admin":true,"terms_url":"https://provider.example/terms"}`

The Forex consumer independently rejects private/local endpoints, follows no redirects, never forwards its tenant key to the provider, and validates the response's instrument identity, interval, timestamps, completed OHLC bars and price geometry. Its v1 provider response uses exact `symbol`, `interval`, and a `candles` array with timezone-aware `open_time`, `close_time`, `open`, `high`, `low`, `close`, and optional `volume`. Only public, no-key endpoints are supported in this first iteration.

The Forex consumer discovers the catalog at runtime (five-minute cache), checks up to five eligible sources, and chooses the freshest valid completed bar. Adding a source that implements this stable protocol requires a new admin-approved manifest and the repository's `registry:read` scope, not a source-specific Forex code change. A new protocol, authenticated provider, paid feed, privileged operation, or different response contract still requires a reviewed adapter change. The central registry does not guarantee the source is free or accurate; the zero-cost field is an administrator attestation and must be backed by independent terms/pricing review.


## 8. Reliability boundary and final integration architecture

### Control plane and data plane

- **Control plane:** repository identity, tenant/team ownership, key issuance/revocation, scopes, extension approval, immutable versions, pricing attestations, and policy decisions.
- **Contract plane:** versioned agent I/O schemas, integration capabilities, event schemas, and SDK compatibility checks. A repository identifies itself and declares the contract version it supports; it never selects a Python module, URL, model provider, or arbitrary executable.
- **Execution plane:** the shared encrypted job queue, fixed allow-listed handlers, zero-cost eligibility gate, quota reservation, and bounded workflow steps.
- **Resource plane:** provider/model catalogs and metadata-only source/connector registries. Registry entries describe capabilities; they do not prove trust, price, correctness, or license rights and are not executable.
- **Event plane:** tenant-scoped event publication/claim/settlement with idempotency, leases, correlation and causation identifiers. Consumers must tolerate at-least-once delivery.
- **Observability plane:** job state, worker heartbeat, operational alerts, usage ledger, and provider/model latency and outcome metrics. Logs and telemetry must not contain prompts, response bodies, credentials, or raw tenant keys.

### Repository onboarding invariant

A new repository should require only:
1. explicit owner/repository approval and a tenant key restricted to that exact repository;
2. least-privilege scopes;
3. an approved immutable connector manifest for an already supported capability;
4. the official Python/Node SDK or a small HTTP adapter implementing the same contract;
5. a successful authenticated end-to-end contract test before the repository is considered connected.

No central code change is required only when the new repository uses an existing capability and protocol such as `research.workflow.v1`. A new data protocol, new privileged operation, or new execution behavior still requires reviewed central code and tests. This is intentional: metadata-only plugins prevent arbitrary third-party code execution.

### Retry and checkpoint limitation

The current research workflow is one durable job containing three sequential model stages and an optional fourth translation stage. Queue retries restart the workflow from the first stage; there is not yet a durable per-stage checkpoint/resume journal. A retry can therefore repeat earlier inference calls and consume additional provider quota. The workflow remains research-only and must not be extended with publishing, trading, payouts, account mutation, wallet signing, or other side effects until stage-level idempotency, encrypted checkpoint persistence, cancellation/compensation semantics, and explicit approval gates are implemented and tested.

### Compatibility policy

- Add optional fields without changing existing meanings.
- Breaking input/output changes require a new major contract version and parallel support during migration.
- Keep stable event type and schema identifiers; consumers reject unsupported major versions rather than guessing.
- Use capability negotiation, not repository-name conditionals, for future integrations.
- Keep provider/source adapters behind central policy checks; no connector may bypass the zero-cost, tenant, quota, or safety gates.
- Treat integration health as **unverified** until contract tests and a real tenant-authenticated round trip succeed.

## 9. Standards alignment and production-readiness gaps

The target design follows interoperable standards where they materially improve portability. The following are **not claimed as implemented** merely because the current APIs carry similar metadata:

| Area | Current implementation | Target / remaining work |
|---|---|---|
| Identity and authorization | Repository-bound tenant keys, scopes, revocation, and per-request checks | Add a full OIDC/MFA identity provider only when interactive human access is required; preserve workload identity for repository automation |
| Event interoperability | Custom versioned event envelope with producer/consumer, idempotency, correlation and causation | Add an additive CloudEvents 1.0 envelope (specversion, id, source, type, subject, time, dataschema) while retaining the existing event API during migration |
| Distributed observability | Worker heartbeat, job/usage records, provider metrics, correlation and causation IDs | Add OpenTelemetry trace context and consistent semantic attributes across API, queue, worker, provider calls, and Python/Node SDKs |
| Extension catalog governance | Immutable versioned manifests, exact repository allowlists, capability and schema metadata | Add required owner, lifecycle, documentation, support contact, source/license evidence, reviewer, and review-expiry metadata |
| Build integrity | GitHub Actions CI and CodeQL workflows | Pin every third-party Action to a verified full commit SHA; generate and verify build provenance before claiming a hardened software supply chain |
| Durable orchestration | SQLite queue with leases, retries, idempotent enqueue, and encrypted payload storage | Add encrypted per-stage checkpoints, workflow cancellation, bounded deadlines, and explicit resume semantics before expanding beyond research-only work |
| Runtime scale | SQLite-backed single-service persistence and a bounded worker loop | Keep a single active writer/worker deployment for this mode; move queue, tenant registry, event state and checkpoint storage to a transactional shared database before horizontal multi-instance execution |
| Source ingestion | Metadata-only connector/source catalog; evidence is submitted by repositories | Add reviewed, protocol-specific source adapters with DNS/IP/redirect/size/time limits and licensing evidence; never make arbitrary manifest URLs executable |
| Integration proof | Unit/contract tests and SDK bridge definitions | Require one authenticated end-to-end job per repository and a recorded successful result before marking it connected |

### Recommended implementation order

1. **Release gate:** restore GitHub Actions runner execution; obtain passing Python tests, Node SDK tests, and CodeQL on the exact PR head. No merge based on an empty or unallocated runner.
2. **Reliability:** add encrypted workflow-stage checkpoints and idempotent stage keys; test worker crash/reclaim between every pair of stages.
3. **Interoperability:** introduce CloudEvents-compatible event envelopes and OpenTelemetry trace propagation as additive, versioned changes.
4. **Governance:** make ownership, lifecycle, license evidence, pricing evidence, reviewer and expiry mandatory for production connector approval.
5. **Scale and supply chain:** pin Actions to verified commit SHAs, publish build provenance, and migrate from SQLite only when multi-instance operation is actually needed.

This sequence deliberately avoids premature microservices. The current modular central service is the simplest safe control plane for the present scale; stable contracts and adapters provide future portability without coupling every downstream repository to internal Python modules.
