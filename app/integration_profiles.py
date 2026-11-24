"""Static, non-executable integration profiles for downstream repositories.

Profiles document intended scopes and safety boundaries. They do not grant
tenant permissions, connect external accounts, or enable domain actions.
"""
from __future__ import annotations

from copy import deepcopy


INTEGRATION_PROFILE_VERSION = 1

_INTEGRATION_PROFILES = (
    {
        "id": "koroush.forex",
        "name": "Forex and market research",
        "status": "contract-only",
        "contract_version": INTEGRATION_PROFILE_VERSION,
        "shared_agents": ["koroush.text-summarizer", "koroush.text-classifier", "koroush.text-translator", "koroush.research-brief"],
        "required_scopes": ["jobs:enqueue", "jobs:read", "inference:chat"],
        "allowed_operations": ["research-summary", "scenario-classification", "market-news-translation"],
        "blocked_operations": ["live-order-execution", "broker-account-access", "credential-storage", "position-management"],
        "execution": "not-enabled",
        "notes": "Research and analysis contract only; no trading signal guarantee or broker connectivity.",
    },
    {
        "id": "koroush.youtube",
        "name": "YouTube content workflow",
        "status": "contract-only",
        "contract_version": INTEGRATION_PROFILE_VERSION,
        "shared_agents": ["koroush.text-summarizer", "koroush.text-translator", "koroush.text-classifier", "koroush.research-brief"],
        "required_scopes": ["jobs:enqueue", "jobs:read", "inference:chat"],
        "allowed_operations": ["topic-research-summary", "script-draft", "metadata-draft", "subtitle-translation"],
        "blocked_operations": ["public-video-publishing", "channel-settings-mutation", "oauth-token-exposure", "unlicensed-media-reuse"],
        "execution": "not-enabled",
        "notes": "Drafting contract only; public publishing and channel actions remain disabled.",
    },
    {
        "id": "koroush.ptc",
        "name": "PTC platform research",
        "status": "contract-only",
        "contract_version": INTEGRATION_PROFILE_VERSION,
        "shared_agents": ["koroush.text-summarizer", "koroush.text-classifier", "koroush.research-brief"],
        "required_scopes": ["jobs:enqueue", "jobs:read", "inference:chat"],
        "allowed_operations": ["site-review-summary", "offer-risk-classification", "earnings-data-analysis"],
        "blocked_operations": ["automated-clicking", "account-login", "captcha-bypass", "payout-actions"],
        "execution": "not-enabled",
        "notes": "Evidence-based research contract only; no automated earning activity or account actions.",
    },
    {
        "id": "koroush.nft",
        "name": "NFT research and valuation",
        "status": "contract-only",
        "contract_version": INTEGRATION_PROFILE_VERSION,
        "shared_agents": ["koroush.text-summarizer", "koroush.text-classifier", "koroush.research-brief"],
        "required_scopes": ["jobs:enqueue", "jobs:read", "inference:chat"],
        "allowed_operations": ["collection-research-summary", "metadata-review", "valuation-report-draft"],
        "blocked_operations": ["wallet-signing", "onchain-transactions", "marketplace-listing", "custody-of-assets"],
        "execution": "not-enabled",
        "notes": "Research and draft reports only; no wallet access, signing, or transactions.",
    },
)


def list_integration_profiles() -> list[dict]:
    """Return defensive copies of non-executable integration contracts."""
    return [deepcopy(profile) for profile in _INTEGRATION_PROFILES]


def get_integration_profile(profile_id: str) -> dict | None:
    for profile in _INTEGRATION_PROFILES:
        if profile["id"] == profile_id:
            return deepcopy(profile)
    return None
