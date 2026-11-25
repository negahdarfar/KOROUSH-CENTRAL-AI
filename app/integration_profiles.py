"""Executable research-only profiles for the four downstream repositories.

Each profile submits to the shared encrypted durable queue and fixed agent
workflow. Account actions, trading, publishing and custody remain disabled.
"""
from __future__ import annotations

from copy import deepcopy


INTEGRATION_PROFILE_VERSION = 1

_INTEGRATION_PROFILES = (
    {
        "id": "koroush.forex",
        "name": "Forex and market research",
        "status": "enabled-research",
        "contract_version": INTEGRATION_PROFILE_VERSION,
        "api": "POST /api/integrations/forex/research",
        "job_type": "agent.workflow",
        "shared_agents": ["koroush.research-brief", "koroush.text-classifier", "koroush.text-summarizer", "koroush.text-translator"],
        "required_scopes": ["jobs:enqueue", "jobs:read", "inference:chat"],
        "allowed_operations": ["research-summary", "scenario-classification", "market-news-translation"],
        "blocked_operations": ["live-order-execution", "broker-account-access", "credential-storage", "position-management"],
        "execution": "durable-job",
        "notes": "Evidence-grounded analysis only; no executable trade instructions or broker connectivity.",
    },
    {
        "id": "koroush.youtube",
        "name": "YouTube content workflow",
        "status": "enabled-research",
        "contract_version": INTEGRATION_PROFILE_VERSION,
        "api": "POST /api/integrations/youtube/research",
        "job_type": "agent.workflow",
        "shared_agents": ["koroush.research-brief", "koroush.text-classifier", "koroush.text-summarizer", "koroush.text-translator"],
        "required_scopes": ["jobs:enqueue", "jobs:read", "inference:chat"],
        "allowed_operations": ["topic-research-summary", "script-draft", "metadata-draft", "subtitle-translation"],
        "blocked_operations": ["public-video-publishing", "channel-settings-mutation", "oauth-token-exposure", "unlicensed-media-reuse"],
        "execution": "durable-job",
        "notes": "Topic research, classification, synthesis and optional translation; publishing and channel actions remain disabled.",
    },
    {
        "id": "koroush.ptc",
        "name": "PTC platform research",
        "status": "enabled-research",
        "contract_version": INTEGRATION_PROFILE_VERSION,
        "api": "POST /api/integrations/ptc/research",
        "job_type": "agent.workflow",
        "shared_agents": ["koroush.research-brief", "koroush.text-classifier", "koroush.text-summarizer"],
        "required_scopes": ["jobs:enqueue", "jobs:read", "inference:chat"],
        "allowed_operations": ["site-review-summary", "offer-risk-classification", "earnings-data-analysis"],
        "blocked_operations": ["automated-clicking", "account-login", "captcha-bypass", "payout-actions"],
        "execution": "durable-job",
        "notes": "Evidence-based platform and offer research; no automated earning activity or account actions.",
    },
    {
        "id": "koroush.nft",
        "name": "NFT research and valuation",
        "status": "enabled-research",
        "contract_version": INTEGRATION_PROFILE_VERSION,
        "api": "POST /api/integrations/nft/research",
        "job_type": "agent.workflow",
        "shared_agents": ["koroush.research-brief", "koroush.text-classifier", "koroush.text-summarizer"],
        "required_scopes": ["jobs:enqueue", "jobs:read", "inference:chat"],
        "allowed_operations": ["collection-research-summary", "metadata-review", "valuation-report-draft"],
        "blocked_operations": ["wallet-signing", "onchain-transactions", "marketplace-listing", "custody-of-assets"],
        "execution": "durable-job",
        "notes": "Metadata and market-evidence research; no wallet access, signing, or transactions.",
    },
)


def list_integration_profiles() -> list[dict]:
    """Return defensive copies; callers cannot mutate the process registry."""
    return [deepcopy(profile) for profile in _INTEGRATION_PROFILES]


def get_integration_profile(profile_id: str) -> dict | None:
    for profile in _INTEGRATION_PROFILES:
        if profile["id"] == profile_id:
            return deepcopy(profile)
    return None
