# KOROUSH UNIVERSAL AI HUB — Target Architecture

## Mission

KOROUSH CENTRAL AI is the control plane and shared capability platform for all current and future repositories. It is the authoritative catalog for agents, model providers, tools, APIs, data sources, schemas, policies, and integration profiles. Domain repositories retain their own business logic and data ownership.

The design goal is additive evolution: registering a new compatible resource should update discovery and synchronization data, not require editing the central application or every downstream repository.

## Logical architecture

```text
                   KOROUSH CENTRAL AI — CONTROL PLANE
  ┌──────────────────────────────────────────────────────────────┐
  │ Identity / Tenant Policy │ Registry │ Schema & Version Catalog│
  │ Zero-Cost Policy         │ Capability Router │ Audit Ledger   │
  └──────────────────────────────────────────────────────────────┘
             │ discovery / policy / capability negotiation
  ┌──────────┴───────────────────────────────────────────────────┐
  │                  SHARED DATA PLANE                           │
  │ Source Collectors → Evidence Hub → Normalizers → Event Bus   │
  │ Model Gateway     → Agent Runtime → Durable Jobs → Results   │
  │ Connector Workers → Retry / Lease / DLQ → Observability      │
  └──────────┬───────────────────────────────────────────────────┘
             │ stable REST / SDK / webhook contracts
   ┌─────────┼───────────┬────────────┬───────────────┐
   Forex   YouTube      PTC          NFT         Future repos
   domain  domain       domain       domain      domain adapters
```

## Core registries

1. **Agent Registry** — agent ID, immutable version, input/output schema refs, capabilities, supported domains, execution mode, required scopes, health and lifecycle state.
2. **Resource Registry** — models, providers, APIs, tools, source connectors, data feeds, licenses, pricing evidence and rate limits.
3. **Schema Registry** — versioned event, request, response and evidence contracts; compatibility policy is backward-compatible by default.
4. **Repository Integration Registry** — repository identity, enabled capabilities, scopes, policy profile and sync cursor.
5. **Trust & Evidence Registry** — provenance, content fingerprint, observed/fetched timestamps, publisher evidence and trust state.

The current dynamic extension registry is the first metadata registry slice. It does not yet implement executable adapters, schema validation, event delivery, or automatic downstream synchronization.

## Agent-to-agent communication

Agents must not call one another through private in-process imports or share credentials. Communication uses a durable event/job envelope:
- `event_id`, `event_type`, `schema_version`, `tenant_id`, `repository`, `producer`, `correlation_id`, `causation_id`, `idempotency_key`, `created_at`, `expires_at`, and encrypted payload reference.
- Publish and consume permissions are scoped by tenant, repository, event type and agent capability.
- Delivery is at-least-once; consumers must be idempotent. Use leases, bounded retries, exponential backoff, dead-letter queues and explicit replay audit.
- Event payloads use the existing encrypted payload store; the event index stores metadata and opaque references, not raw secrets or large content.
- A workflow can chain agents by emitting a typed result event. The orchestrator validates schema compatibility and policy before enqueueing the next job.
- No arbitrary agent-to-agent network access or dynamic code execution.

## Automatic discovery and synchronization

1. A new provider, model, agent or data source is submitted as a signed/approved, versioned manifest.
2. The central registry validates identity, semantic version, endpoint policy, schema references, declared scopes, license and pricing evidence.
3. The registry increments a monotonically increasing catalog revision and records an audit event.
4. Each repository adapter polls the manifest/revision endpoint or receives a webhook notification; it fetches only changed entries since its last acknowledged revision.
5. The adapter verifies the manifest digest and compatibility, applies local allow/deny policy, then updates its local capability cache atomically.
6. The repository acknowledges the revision. Failed updates remain pending and retry; they never partially overwrite a working configuration.
7. Breaking changes require a new major version and an explicit migration plan. Old versions remain discoverable during a defined deprecation window.

This avoids editing application code for catalog additions. A new *protocol family* still requires one centrally reviewed adapter implementation; a metadata manifest alone cannot magically implement an unknown protocol.

## Zero-cost and trust policy

- “Free” is a verified property of an exact provider + model + endpoint + modality + current terms, not a label supplied by a plugin author.
- Unknown or stale pricing is blocked when the repository's budget is zero.
- A new source remains unverified until ownership, provenance and freshness are independently checked.
- Licenses, attribution requirements, quotas, rate limits and usage restrictions travel with each resource manifest.
- No automatic purchase, paid fallback, live trade, public publish, wallet signing or other high-impact action is enabled by discovery alone.

## Backward compatibility

- Existing repositories keep their current workflows and domain data.
- Integration is opt-in per repository using a small stable SDK/REST adapter and explicit scopes.
- Manifest fields are additive within a major version; unknown required capabilities fail closed.
- Local cache expiry and last-known-good manifests allow graceful operation during a central outage.
- Synchronization never writes secrets into Git, repository files, logs or manifests.
- Registry updates are metadata-only; code deployment is a separate reviewed action.

## Implementation sequence

1. Versioned dynamic extension registry and scoped discovery — initial implementation in PR44.
2. Schema registry and compatibility validator.
3. Durable tenant-scoped event bus/outbox, consumer leases and dead-letter/replay audit.
4. Agent orchestration graph and capability-based routing over the existing encrypted job queue.
5. Source collector scheduler with fixed allowlisted feeds, DNS/IP protections, rate limits and provenance.
6. Repository SDK sync client, revision cursors, webhooks and local last-known-good cache.
7. Provider adapters with independently verified zero-price evidence and runtime health checks.
8. Per-repository onboarding, canary rollout, audit and rollback.

## Operational acceptance criteria

- Tenant isolation and scope checks pass across every registry, event, job and result endpoint.
- Duplicate delivery does not duplicate downstream side effects.
- Schema incompatibility is rejected before dispatch.
- A registry update can be discovered without changing downstream source code.
- A repository can pin or roll back to a previous manifest revision.
- Zero-cost policy rejects missing, expired or non-explicit price evidence.
- SQLite persistence is not considered production durable until the actual persistent volume mount and restart recovery are verified.
- CI and CodeQL pass on the exact candidate SHA before merge; deployment is a separate approval.


## Live discovery intake

The admin-only `POST /api/admin/discovery/search` endpoint is the bounded first live source adapter. It queries only the fixed GitHub public Search API host, rejects unsafe returned URLs, and returns candidate scores plus missing evidence. Discovery is deliberately separated from extension registration: every candidate requires administrator review, license review, official pricing verification, and explicit tenant/repository scope assignment. It does not clone, install, execute, or sync external code.
