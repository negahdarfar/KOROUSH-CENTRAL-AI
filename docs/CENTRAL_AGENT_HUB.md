# KOROUSH CENTRAL AI — Central Agent Hub

## Role in the ecosystem

KOROUSH-CENTRAL-AI is the shared control plane for connected repositories. Repositories discover the central manifest and agent catalog, authenticate with a repository-bound tenant key, and submit supported work through the durable job API. They should not independently duplicate provider routing, policy enforcement, quota controls, agent discovery, or operational telemetry.

The control plane is not a shared data bucket. Repository identity, team identity, tenant scopes, job ownership, usage limits, and encrypted payloads remain isolated. Provider credentials are configured only in the central runtime's secret store; tenant repositories keep only their own tenant API key in their own secret manager.

## Current discovery endpoints

- `GET /api/platform/manifest`: public, non-secret platform and integration contract, including the central API catalog.
- `GET /api/apis?repository=owner/repository`: tenant-filtered API catalog; admins can inspect the complete catalog.
- `GET /api/agents?repository=owner/repository`: tenant-visible agent catalog. Send `X-Tenant-Key`. Admins may send `X-Admin-Key` to inspect the complete catalog.
- `GET /api/agents/{agent_id}?repository=owner/repository`: detail for one discoverable agent.
- `POST /api/jobs`: submit an encrypted durable job using a tenant key with `jobs:enqueue`.
- `GET /api/jobs/{job_id}?repository=owner/repository`: read job status with the tenant's read scope.

The registry distinguishes `available`, `limited`, and `planned` capability states. A catalog entry is discovery metadata, not a promise that every provider account, transport, or job handler is configured. In particular, arbitrary remote code execution and automatic plugin installation are not supported.

## Python SDK

The initial async SDK is under `sdk/python/koroush_central`. Install its dependency with `pip install -r sdk/python/requirements.txt`, add `sdk/python` to the consuming application's package path (or package it in a later release), and initialize it from environment variables:

```python
import os
from koroush_central import CentralAIClient

async with CentralAIClient(
    base_url=os.environ["KOROUSH_CENTRAL_URL"],
    tenant_key=os.environ["KOROUSH_TENANT_API_KEY"],
    repository="owner/repository",
) as central:
    catalog = await central.agents()
    job = await central.submit_job(
        job_type="chat.completion",
        payload={"task": "general", "messages": [{"role": "user", "content": "Summarize this example."}], "max_tokens": 500},
        idempotency_key="stable-operation-id",
    )
```

Never put a tenant key in source code, logs, workflow artifacts, or committed `.env` files. Use repository-level GitHub Actions secrets or the target platform's secret manager.

## Agent onboarding contract

A new agent must be added to the central registry with a stable ID, owner/team, version, declared scopes, execution mode, supported capabilities, and operational state. Its implementation must use a reviewed in-process adapter or a signed, isolated plugin runtime. It must not be loaded from an arbitrary repository URL or execute untrusted repository code inside the API process.

Before an agent is marked `available`, it needs:
1. explicit input/output schema and versioning;
2. tenant and repository authorization;
3. idempotency and bounded timeouts;
4. cost/quota policy enforcement before provider calls;
5. bounded retries and cancellation;
6. structured, secret-free audit events;
7. unit, integration, and isolation tests;
8. health and operational ownership.

## Migration strategy for other repositories

1. Keep each repository's product UI, domain data, and business rules in that repository.
2. Move shared model/provider selection, agent catalog, central task queue, and cross-repository policy to this control plane.
3. Replace local provider API calls with the central SDK only after a repository-specific integration PR and tenant key are ready.
4. Migrate one repository at a time; retain a rollback path until central health and usage are verified.
5. Do not delete old local integrations until equivalent central behavior is proven in production.

## Current limitations

The first iteration provides discovery and a Python integration client. It does not yet implement dynamic agent installation, a full plugin sandbox, universal API adapters, cross-repository user SSO, or a graphical control-plane dashboard. Existing synchronous GitHub operator endpoints remain operator-only. These gaps must be closed in separate reviewed increments.

## Provider consolidation status

The manifest exposes the current provider integration state. AvalAI is the only provider adapter represented as partially available in this hub branch. OpenRouter, FreeLLMAPI, and Gemini remain planned integrations until their adapters are reviewed, tested against real account metadata, and wired through the common routing and usage policy. A provider name, model label, or `free` suffix is never sufficient evidence of zero price. The global zero-cost policy must reject unknown or paid pricing unless a separately approved budget policy is introduced.


## Node.js SDK

For JavaScript/TypeScript repositories, a dependency-free Node.js client is provided at `sdk/node/koroush-central.mjs`. It uses native `fetch` (Node.js 18+), requires HTTPS for remote endpoints, and does not include tenant keys in thrown error messages.

```js
import { CentralAIClient } from "./sdk/node/koroush-central.mjs";

const central = new CentralAIClient({
  baseUrl: process.env.KOROUSH_CENTRAL_URL,
  tenantKey: process.env.KOROUSH_TENANT_API_KEY,
  repository: "owner/repository",
});

const agents = await central.agents();
const job = await central.submitJob({
  jobType: "chat.completion",
  idempotencyKey: "stable-operation-id",
  payload: {
    task: "general",
    messages: [{ role: "user", content: "Summarize this example." }],
    max_tokens: 500,
  },
});
```

The SDK does not create tenant keys. Provision each repository/team identity through the operator-controlled onboarding process and store the resulting key only in that repository's secret manager.
