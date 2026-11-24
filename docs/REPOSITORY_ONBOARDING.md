# Connected repository onboarding

KOROUSH CENTRAL AI is the shared orchestration/control plane. It centralizes approved model routing, capability discovery, tenant-bound jobs, cost/quota enforcement, and operational policy. It does not take ownership of each repository's product data or business logic.

## Candidate repository rollout

These repositories were identified as candidates for staged integration. This is an onboarding plan, not a claim that their production traffic has already been migrated.

| Repository | Primary language | Initial central integration |
|---|---|---|
| `negahdarfar/YouTube-Factory-` | Python | Replace duplicated model selection/provider calls with the Python SDK; submit script/metadata generation as central chat jobs |
| `negahdarfar/Ptc-earning-` | Python | Route approved AI text tasks through central jobs; keep payments, user records, and earning logic local |
| `negahdarfar/Daily-Forex-Analyze-` | Python | Route summarization/classification tasks centrally; keep market-data ingestion, calculations, risk controls, and trading decisions locally |
| `negahdarfar/Nft-art-factory` | JavaScript | Use the Node SDK for text/metadata jobs; keep image rendering, storage, minting, and wallet operations local |

## Rollout sequence

1. Register each exact `owner/repository` under its own team identity using the admin tenant-key API.
2. Issue separate tenant credentials per repository (or per independently trusted service), with only the scopes it needs.
3. Add `KOROUSH_CENTRAL_URL` and `KOROUSH_TENANT_API_KEY` to that repository's secret manager. Never commit credentials.
4. Install the matching SDK (Python or Node) and first call `manifest()`, `agents()`, and `apis()` as read-only discovery checks.
5. Use `sync_extensions()` (Python) or `syncExtensions()` (Node) to read a repository-filtered registry snapshot. This is metadata-only: it does not install, import, or execute remote extensions.
6. If the tenant key is explicitly granted event scopes, use `publish_event()` / `publishEvent()`. A separately operated consumer can claim and settle events. Delivery is at-least-once; consumers must be idempotent.
7. Move one low-risk, non-financial, non-publishing AI task to `chat.completion` jobs. Use a stable idempotency key for every logical operation.
8. Verify tenant isolation, quota accounting, encrypted job payload lifecycle, logs, retry behavior, and real deployed readiness.
9. Only after a repository's integration PR and production checks pass, disable its old duplicate provider integration. Keep rollback available until then.

## Credential scopes

- `inference:chat`: synchronous tenant inference where the specific endpoint supports it.
- `jobs:enqueue`: submit supported durable jobs.
- `jobs:read`: read status/results for jobs owned by the same tenant identity.
- `registry:read`: discover extension metadata for the assigned repository.
- `events:publish`, `events:consume`, `events:read`: separately grant event publication, consumption, and metadata inspection. These are never added to existing keys automatically.

For the durable job API, issue both `jobs:enqueue` and `jobs:read` if the service needs submission and polling. The default tenant-key scope is only `inference:chat`, so do not assume a newly created key can enqueue jobs.

Tenant keys are created with `POST /api/admin/tenant-keys` and listed/revoked through the corresponding admin endpoints. The raw key is returned only once. Use a unique team/repository binding and keep the admin key separate from tenant keys.

## What remains local by design

- User accounts, subscriptions, payment flows, wallet keys, financial ledgers, and personal data.
- Market prices, trading strategy rules, risk limits, trade execution and broker credentials.
- Video/image rendering pipelines, media assets, upload schedules, channel credentials and publication policies.
- NFT minting, wallet signing, object storage and chain transactions.

Centralization means shared AI services and orchestration, not moving sensitive product data or high-risk actions into one global process.

## Current rollout state

The central branch contains discovery endpoints and Python/Node SDK clients. No candidate repository has been changed by this onboarding document. Each downstream integration should be a separate, reviewable pull request. Production use remains gated on tenant-key provisioning, durable worker configuration, persistent storage, provider evidence, and deployment verification.

## Versioned downstream integration profiles

The public platform manifest now includes four version-1 integration profiles: `koroush.forex`, `koroush.youtube`, `koroush.ptc`, and `koroush.nft`. These are **contract-only** profiles: they document shared text-agent reuse, minimum intended scopes, allowed low-risk task categories, and explicitly blocked high-impact operations. They do not create tenant keys, grant scopes, connect accounts, or activate domain-specific execution.

| Profile | Intended shared tasks | Explicitly not enabled |
|---|---|---|
| Forex | Research summaries, scenario classification, market-news translation | Live orders, broker access, position management |
| YouTube | Topic research summaries, script and metadata drafts, subtitle translation | Public publishing, channel mutation, OAuth token exposure |
| PTC | Site-review summaries, offer-risk classification, earnings-data analysis | Automated clicking, account login, CAPTCHA bypass, payouts |
| NFT | Collection research, metadata review, valuation-report drafts | Wallet signing, on-chain transactions, marketplace listing |

All profiles currently advertise `execution: not-enabled`. Domain-specific agents and downstream repository adapters must be implemented and tested in separate PRs. A profile is not proof that an operation is implemented or safe for production. The central manifest is discovery metadata, not an authorization grant; actual permissions remain enforced by repository-bound tenant keys and API scopes. The Python and Node SDKs expose opt-in read-only extension snapshots and explicit event operations. They do not auto-sync code, install extensions, change repository files, or execute remote tools.
