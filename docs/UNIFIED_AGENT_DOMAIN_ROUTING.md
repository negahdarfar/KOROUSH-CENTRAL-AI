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

All use the same tenant header and encrypted durable queue. The tenant key must be assigned to the exact `owner/repository` and include `jobs:enqueue` and `inference:chat`. Add `jobs:read` to retrieve job results through `GET /api/jobs/{job_id}?repository=owner/repository`.

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
