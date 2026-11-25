"""Central catalog of AI agents and API capabilities.

This registry describes real routes already implemented by the service and
labels incomplete transports explicitly. It does not dynamically import or
execute code supplied by tenant repositories.
"""
from __future__ import annotations

from copy import deepcopy

from .integration_profiles import list_integration_profiles
from .source_connector_catalog import list_connectors

PLATFORM_VERSION = "0.4.0"
MANIFEST_VERSION = "1.0"

_AGENTS = (
    {
        "id": "koroush.model-router",
        "name": "Central Model Router",
        "category": "orchestration",
        "description": "Selects an eligible model under provider, repository and cost policy.",
        "status": "limited",
        "execution": "embedded",
        "required_scopes": ["inference:chat"],
        "api": "POST /api/avalai/execute/{surface}",
        "capabilities": ["model-selection", "cost-policy", "provider-catalog"],
    },
    {
        "id": "koroush.resource-discovery",
        "name": "Evidence-Aware Resource Discovery",
        "category": "discovery",
        "description": "Searches public GitHub repository metadata with bounded queries and routes candidates to admin review.",
        "status": "limited",
        "execution": "admin-http",
        "required_scopes": ["operator"],
        "api": "POST /api/admin/discovery/search",
        "capabilities": ["live-github-search", "bounded-results", "recency-ranking", "pricing-evidence-gap-reporting"],
    },
    {
        "id": "koroush.provider-gateway",
        "name": "Provider API Gateway",
        "category": "integration",
        "description": "Exposes allow-listed provider capabilities; transport support is capability-specific.",
        "status": "limited",
        "execution": "synchronous",
        "required_scopes": ["inference:chat"],
        "api": "POST /api/avalai/execute/{surface}",
        "capabilities": ["text", "reasoning", "embeddings", "image-generation", "speech-output", "moderation"],
    },
    {
        "id": "koroush.github-auditor",
        "name": "GitHub Repository Auditor",
        "category": "engineering",
        "description": "Read-only repository inventory and AI-assisted audit.",
        "status": "available",
        "execution": "synchronous",
        "required_scopes": ["operator"],
        "api": "GET /api/audit/{owner}/{repo}",
        "capabilities": ["repository-audit", "read-only"],
    },
    {
        "id": "koroush.github-repair",
        "name": "GitHub Repair Agent",
        "category": "engineering",
        "description": "Prepares version-bound repair previews and publishes only explicitly approved drafts.",
        "status": "available",
        "execution": "synchronous",
        "required_scopes": ["operator"],
        "api": "POST /api/fix-preview/{owner}/{repo}; POST /api/fix-apply/{owner}/{repo}",
        "capabilities": ["repair-preview", "approval-digest", "draft-pull-request"],
    },
    {
        "id": "koroush.text-summarizer",
        "name": "Text Summarization Agent",
        "category": "content",
        "description": "Summarizes bounded text through the central model router and zero-cost policy.",
        "status": "limited",
        "contract_version": 1,
        "execution": "durable-job",
        "required_scopes": ["jobs:enqueue", "inference:chat"],
        "api": "POST /api/jobs (job_type=agent.execute)",
        "job_type": "agent.execute",
        "agent_id": "koroush.text-summarizer",
        "capabilities": ["summarization", "source-text-untrusted", "bounded-input"],
    },
    {
        "id": "koroush.text-translator",
        "name": "Text Translation Agent",
        "category": "content",
        "description": "Translates bounded text to a caller-specified language through the central model router.",
        "status": "limited",
        "contract_version": 1,
        "execution": "durable-job",
        "required_scopes": ["jobs:enqueue", "inference:chat"],
        "api": "POST /api/jobs (job_type=agent.execute)",
        "job_type": "agent.execute",
        "agent_id": "koroush.text-translator",
        "capabilities": ["translation", "language-target", "bounded-input"],
    },
    {
        "id": "koroush.text-classifier",
        "name": "Text Classification Agent",
        "category": "analysis",
        "description": "Classifies bounded text against a caller-provided finite label set.",
        "status": "limited",
        "contract_version": 1,
        "execution": "durable-job",
        "required_scopes": ["jobs:enqueue", "inference:chat"],
        "api": "POST /api/jobs (job_type=agent.execute)",
        "job_type": "agent.execute",
        "agent_id": "koroush.text-classifier",
        "capabilities": ["classification", "finite-label-set", "bounded-input"],
    },
    {
        "id": "koroush.research-brief",
        "name": "Evidence-Grounded Domain Research Agent",
        "category": "research",
        "description": "Builds bounded research briefs from caller-supplied evidence for Forex, YouTube, PTC, and NFT domains.",
        "status": "limited",
        "contract_version": 1,
        "execution": "durable-job",
        "required_scopes": ["jobs:enqueue", "inference:chat"],
        "api": "POST /api/jobs (job_type=agent.execute)",
        "job_type": "agent.execute",
        "agent_id": "koroush.research-brief",
        "capabilities": ["evidence-grounded-research", "source-attribution", "bounded-input", "no-external-fetch"],
    },
    {
        "id": "koroush.durable-jobs",
        "name": "Durable Job Orchestrator",
        "category": "orchestration",
        "description": "Accepts tenant-bound encrypted jobs and exposes tenant-scoped status.",
        "status": "available",
        "execution": "asynchronous",
        "required_scopes": ["jobs:enqueue", "jobs:read"],
        "api": "POST /api/jobs; GET /api/jobs/{job_id}",
        "capabilities": ["durable-queue", "idempotency", "lease-recovery", "tenant-isolation"],
    },
    {
        "id": "koroush.operations",
        "name": "Operations and Alert Agent",
        "category": "operations",
        "description": "Exposes readiness, worker heartbeat and operational notification workflows.",
        "status": "limited",
        "execution": "background",
        "required_scopes": ["operator"],
        "api": "GET /readyz; GET /api/admin/jobs/summary",
        "capabilities": ["readiness", "worker-heartbeat", "queue-observability", "alerts"],
    },
)

_CAPABILITIES = (
    {"id": "chat.completion", "status": "available", "transport": "json", "job_type": "chat.completion"},
    {"id": "agent.execute", "status": "limited", "transport": "durable-job", "job_type": "agent.execute", "agents": ["koroush.text-summarizer", "koroush.text-translator", "koroush.text-classifier", "koroush.research-brief"]},
    {"id": "github.repository.audit", "status": "available", "transport": "http", "job_type": None},
    {"id": "github.repair.preview", "status": "available", "transport": "http", "job_type": None},
    {"id": "provider.avalai.json", "status": "limited", "transport": "json", "job_type": None},
    {"id": "audio.transcription", "status": "planned", "transport": "multipart", "job_type": None},
    {"id": "realtime.session", "status": "planned", "transport": "realtime", "job_type": None},
    {"id": "repository.custom_agent", "status": "planned", "transport": "signed-plugin", "job_type": None},
)



_PROVIDER_CATALOG = (
    {"id": "avalai", "status": "limited", "adapter": "app/avalai.py", "note": "Authenticated catalog and allow-listed JSON gateway; account access and route support vary."},
    {"id": "openrouter", "status": "planned", "adapter": None, "note": "Must use exact model/provider price evidence and enforce the global zero-cost guard."},
    {"id": "freellmapi", "status": "planned", "adapter": None, "note": "Must verify upstream model/provider pricing; a free endpoint label alone is not proof."},
    {"id": "gemini", "status": "planned", "adapter": None, "note": "Dedicated adapter, quota policy, and evidence-backed price/capability metadata are required."},
)

_API_CATALOG = (
    {"id": "health.status", "method": "GET", "path": "/health", "auth": "public-health", "status": "available"},
    {"id": "runtime.version", "method": "GET", "path": "/api/version", "auth": "public-health", "status": "available"},
    {"id": "tenant.keys.create", "method": "POST", "path": "/api/admin/tenant-keys", "auth": "admin", "status": "available"},
    {"id": "tenant.keys.list", "method": "GET", "path": "/api/admin/tenant-keys", "auth": "admin", "status": "available"},
    {"id": "tenant.keys.revoke", "method": "POST", "path": "/api/admin/tenant-keys/{key_id}/revoke", "auth": "admin", "status": "available"},
    {"id": "admin.diagnostics", "method": "GET", "path": "/api/diagnostics", "auth": "admin", "status": "available"},
    {"id": "admin.github.repositories", "method": "GET", "path": "/api/github/repos", "auth": "admin", "status": "available"},
    {"id": "usage.alerts.dispatch", "method": "POST", "path": "/api/usage/alerts/dispatch", "auth": "admin", "status": "available"},
    {"id": "admin.panel", "method": "GET", "path": "/panel", "auth": "public-ui", "status": "available"},
    {"id": "apis.catalog", "method": "GET", "path": "/api/apis", "auth": "tenant-or-admin", "status": "available"},
    {"id": "provider.avalai.capabilities", "method": "GET", "path": "/api/avalai/capabilities", "auth": "admin", "status": "available"},
    {"id": "provider.avalai.models.inspect", "method": "POST", "path": "/api/avalai/models/inspect", "auth": "admin", "status": "available"},
    {"id": "platform.manifest", "method": "GET", "path": "/api/platform/manifest", "auth": "public", "status": "available"},
    {"id": "discovery.github.search", "method": "POST", "path": "/api/admin/discovery/search", "auth": "admin", "status": "limited", "side_effects": "read-only-public-metadata"},
    {"id": "agents.catalog", "method": "GET", "path": "/api/agents", "auth": "tenant-or-admin", "status": "available"},
    {"id": "agents.detail", "method": "GET", "path": "/api/agents/{agent_id}", "auth": "tenant-or-admin", "status": "available"},
    {"id": "jobs.enqueue", "method": "POST", "path": "/api/jobs", "auth": "tenant:jobs:enqueue+inference:chat", "status": "available"},
    {"id": "integrations.catalog", "method": "GET", "path": "/api/integrations", "auth": "public", "status": "available"},
    {"id": "integrations.domain.research", "method": "POST", "path": "/api/integrations/{domain}/research", "auth": "tenant:jobs:enqueue+inference:chat", "status": "available", "execution": "durable-job", "domains": ["forex", "youtube", "ptc", "nft"]},
    {"id": "jobs.status", "method": "GET", "path": "/api/jobs/{job_id}", "auth": "tenant:jobs:read", "status": "available"},
    {"id": "evidence.register", "method": "POST", "path": "/api/evidence", "auth": "tenant:evidence:write", "status": "available", "stores": "metadata-only"},
    {"id": "evidence.list", "method": "GET", "path": "/api/evidence", "auth": "tenant:evidence:read", "status": "available", "stores": "metadata-only"},
    {"id": "extensions.register", "method": "POST", "path": "/api/extensions", "auth": "admin", "status": "available"},
    {"id": "extensions.discover", "method": "GET", "path": "/api/extensions", "auth": "tenant:registry:read", "status": "available"},
    {"id": "events.publish", "method": "POST", "path": "/api/events", "auth": "tenant:events:publish", "status": "available", "payload": "encrypted-vault-reference"},
    {"id": "events.claim", "method": "POST", "path": "/api/events/claim", "auth": "tenant:events:consume", "status": "available"},
    {"id": "events.settle", "method": "POST", "path": "/api/events/{event_id}/settle", "auth": "tenant:events:consume", "status": "available"},
    {"id": "events.list", "method": "GET", "path": "/api/events", "auth": "tenant:events:read", "status": "available", "stores": "metadata-only"},
    {"id": "provider.avalai.execute", "method": "POST", "path": "/api/avalai/execute/{surface}", "auth": "tenant-or-admin", "status": "limited"},
    {"id": "provider.avalai.models", "method": "GET", "path": "/api/avalai/models", "auth": "admin", "status": "available"},
    {"id": "provider.avalai.inspect", "method": "POST", "path": "/api/avalai/models/inspect", "auth": "admin", "status": "available"},
    {"id": "provider.avalai.capabilities", "method": "GET", "path": "/api/avalai/capabilities", "auth": "admin", "status": "available"},
    {"id": "github.audit", "method": "GET", "path": "/api/audit/{owner}/{repo}", "auth": "admin", "status": "available"},
    {"id": "github.repair.proposal", "method": "POST", "path": "/api/fix-proposal/{owner}/{repo}", "auth": "admin", "status": "available"},
    {"id": "github.repair.preview", "method": "POST", "path": "/api/fix-preview/{owner}/{repo}", "auth": "admin", "status": "available"},
    {"id": "github.repair.apply", "method": "POST", "path": "/api/fix-apply/{owner}/{repo}", "auth": "admin+explicit-confirmation", "status": "available"},
    {"id": "usage.summary", "method": "GET", "path": "/api/usage", "auth": "admin", "status": "available"},
    {"id": "usage.alerts", "method": "GET", "path": "/api/usage/alerts", "auth": "admin", "status": "available"},
    {"id": "operations.ready", "method": "GET", "path": "/readyz", "auth": "public-health", "status": "available"},
    {"id": "operations.jobs.summary", "method": "GET", "path": "/api/admin/jobs/summary", "auth": "admin", "status": "available"},
    {"id": "operations.jobs.recovery", "method": "POST", "path": "/api/admin/jobs/{job_id}/requeue", "auth": "admin+explicit-confirmation", "status": "available"},
    {"id": "operations.recovery.audit", "method": "GET", "path": "/api/admin/jobs/recovery-audit", "auth": "admin", "status": "available"},
)


def list_apis(*, include_admin: bool = True) -> list[dict]:
    """Return API contract metadata without runtime credentials or request data."""
    return [
        deepcopy(item) for item in _API_CATALOG
        if include_admin or item["auth"] not in {"admin", "admin+explicit-confirmation"}
    ]


def list_agents(*, include_operator: bool = True) -> list[dict]:
    """Return defensive copies; callers cannot mutate the process registry."""
    return [
        deepcopy(agent) for agent in _AGENTS
        if include_operator or "operator" not in agent["required_scopes"]
    ]


def get_agent(agent_id: str) -> dict | None:
    for agent in _AGENTS:
        if agent["id"] == agent_id:
            return deepcopy(agent)
    return None


def platform_manifest() -> dict:
    return {
        "manifest_version": MANIFEST_VERSION,
        "platform": "KOROUSH-CENTRAL-AI",
        "platform_version": PLATFORM_VERSION,
        "integration_model": "central-control-plane",
        "agents": list_agents(),
        "integrations": list_integration_profiles(),
        "apis": list_apis(include_admin=False),
        "providers": [deepcopy(item) for item in _PROVIDER_CATALOG],
        "source_connectors": list_connectors(),
        "capabilities": [deepcopy(item) for item in _CAPABILITIES],
        "security": {
            "tenant_isolation": "repository-and-team-bound-api-keys",
            "secrets": "tenant-and-provider-secrets-stay-outside-repository-source",
            "plugin_execution": "no-remote-code-import",
            "writes": "github-repair-requires-explicit-preview-approval",
        },
        "contract": {
            "auth_header": "X-Tenant-Key",
            "repository_field": "owner/repository",
            "job_submission": "POST /api/jobs",
            "domain_workflow_submission": "POST /api/integrations/{domain}/research (forex|youtube|ptc|nft)",
            "job_status": "GET /api/jobs/{job_id}?repository=owner/repository",
            "catalog": "GET /api/agents",
            "resource_discovery": "POST /api/admin/discovery/search (admin; metadata-only; manual review required)",
            "api_catalog": "GET /api/apis",
            "extension_registration": "POST /api/extensions (admin)",
            "extension_discovery": "GET /api/extensions?repository=owner/repository (tenant:registry:read)",
            "event_publish": "POST /api/events (tenant:events:publish)",
            "event_claim": "POST /api/events/claim (tenant:events:consume)",
            "event_settle": "POST /api/events/{event_id}/settle (tenant:events:consume)",
            "sdks": ["sdk/python/koroush_central", "sdk/node/koroush-central.mjs"],
        },
    }
