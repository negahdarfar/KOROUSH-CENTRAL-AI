"""Multi-tenant workflow policy registry.

Policies are loaded from KOROUSH_WORKFLOW_POLICIES as JSON. Repository rules
override team rules; team rules override defaults. Secrets are never stored in
this registry: provider credentials stay in Railway environment variables.
"""
from __future__ import annotations

import json
import os
from copy import deepcopy

_DEFAULTS = {
    "provider_order": ["avalai"],
    "free_first": True,
    "free_only": True,
    "allow_unknown_cost": False,
    "allow_paid": False,
    "max_retries": 1,
    "task": "general",
}


def _clean_policy(raw: object) -> dict:
    if not isinstance(raw, dict):
        return {}
    result = {}
    if isinstance(raw.get("provider_order"), list):
        providers = [x.strip().lower() for x in raw["provider_order"] if isinstance(x, str) and x.strip()]
        result["provider_order"] = list(dict.fromkeys(providers))[:8]
    for key in ("free_first", "free_only", "allow_unknown_cost", "allow_paid"):
        if isinstance(raw.get(key), bool):
            result[key] = raw[key]
    if isinstance(raw.get("max_retries"), int):
        result["max_retries"] = max(0, min(raw["max_retries"], 3))
    if isinstance(raw.get("task"), str) and raw["task"] in {"general", "coding", "vision", "fast", "reasoning", "research"}:
        result["task"] = raw["task"]
    # Global hard guard: monthly budget is USD 0.00; repo/team policies cannot loosen it.
    result["free_only"] = True
    result["allow_unknown_cost"] = False
    result["allow_paid"] = False
    return result


def load_workflow_policies(raw_json: str | None = None) -> dict:
    """Parse policy JSON without failing application startup on bad optional config."""
    raw_json = os.getenv("KOROUSH_WORKFLOW_POLICIES", "") if raw_json is None else raw_json
    if not raw_json:
        return {"defaults": {}, "teams": {}, "repositories": {}}
    try:
        data = json.loads(raw_json)
    except (TypeError, json.JSONDecodeError):
        return {"defaults": {}, "teams": {}, "repositories": {}, "config_warning": "invalid_json"}
    if not isinstance(data, dict):
        return {"defaults": {}, "teams": {}, "repositories": {}, "config_warning": "invalid_shape"}
    cleaned = {"defaults": _clean_policy(data.get("defaults")), "teams": {}, "repositories": {}}
    for section in ("teams", "repositories"):
        values = data.get(section, {})
        if isinstance(values, dict):
            cleaned[section] = {str(key).strip(): _clean_policy(value) for key, value in values.items() if str(key).strip()}
    return cleaned


def resolve_workflow_policy(repository: str | None = None, team: str | None = None, policies: dict | None = None) -> dict:
    """Resolve defaults -> team -> exact repository, returning an isolated policy."""
    registry = policies if isinstance(policies, dict) else load_workflow_policies()
    result = deepcopy(_DEFAULTS)
    for layer in (
        registry.get("defaults", {}),
        registry.get("teams", {}).get(team, {}) if team else {},
        registry.get("repositories", {}).get(repository, {}) if repository else {},
    ):
        result.update(_clean_policy(layer))
    return result
