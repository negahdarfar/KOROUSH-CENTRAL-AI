"""Central catalog of AI agents and API capabilities.

This registry describes real routes already implemented by the service and
labels incomplete transports explicitly. It does not dynamically import or
execute code supplied by tenant repositories.
"""
from __future__ import annotations

from copy import deepcopy

PLATFORM_VERSION = "0.4.0"
MANIFEST_VERSION = "1.0"

_AGENTS = (
    {
        "id": "koroush.model-router",
        "name": "Central Model Router",
        "category": "orchestration",
        "description": "Selects an eligible model under provider, repository and cost policy.",
        "status": "available",
        "execution": "synchronous",
        "required_scopes": ["inference:chat"],
        "api": "POST /api/avalai/execute/{surface}",
        "capabilities": ["model-selection", "cost-policy", "provider-catalog"],
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
    {"id": "github.repository.audit", "status": "available", "transport": "http", "job_type": None},
    {"id": "github.repair.preview", "status": "available", "transport": "http", "job_type": None},
    {"id": "provider.avalai.json", "status": "limited", "transport": "json", "job_type": None},
    {"id": "audio.transcription", "status": "planned", "transport": "multipart", "job_type": None},
    {"id": "realtime.session", "status": "planned", "transport": "realtime", "job_type": None},
    {"id": "repository.custom_agent", "status": "planned", "transport": "signed-plugin", "job_type": None},
)


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
            "job_status": "GET /api/jobs/{job_id}?repository=owner/repository",
            "catalog": "GET /api/agents",
        },
    }
