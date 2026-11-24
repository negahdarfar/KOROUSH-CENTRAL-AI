import json

from app.model_router import infer_task, rank_avalai_models, select_avalai_model
from app.workflow_registry import load_workflow_policies, resolve_workflow_policy


def test_free_models_rank_before_unknown_and_paid():
    catalog = [
        {"id": "paid-chat", "mode": "chat", "pricing": {"input": "0.01"}},
        {"id": "unknown-chat", "mode": "chat"},
        {"id": "free-chat", "mode": "chat", "pricing": {"input": 0, "output": 0}},
    ]
    ranked = rank_avalai_models(catalog)
    assert [x["id"] for x in ranked] == ["free-chat", "unknown-chat", "paid-chat"]


def test_free_only_never_treats_unknown_price_as_free():
    catalog = [
        {"id": "unknown-chat", "mode": "chat"},
        {"id": "free-chat", "mode": "chat", "pricing": {"input": 0}},
    ]
    assert select_avalai_model(catalog, free_only=True) == "free-chat"


def test_cost_policy_can_block_unknown_and_paid():
    catalog = [
        {"id": "unknown-chat", "mode": "chat"},
        {"id": "paid-chat", "mode": "chat", "pricing": {"input": 0.1}},
    ]
    try:
        select_avalai_model(catalog, allow_unknown_cost=False, allow_paid=False)
    except RuntimeError:
        pass
    else:
        raise AssertionError("No-cost policy must reject unknown and paid models")


def test_task_inference_supports_workflow_descriptions():
    assert infer_task("repository audit", "debug and refactor code") == "coding"
    assert infer_task("market report", "تحلیل بازار") == "research"


def test_repository_policy_overrides_team_and_defaults():
    config = {
        "defaults": {"allow_paid": False, "task": "general"},
        "teams": {"quant": {"task": "research", "allow_unknown_cost": False}},
        "repositories": {"owner/private": {"task": "coding", "allow_paid": True}},
    }
    policies = load_workflow_policies(json.dumps(config))
    resolved = resolve_workflow_policy("owner/private", "quant", policies)
    assert resolved["task"] == "coding"
    assert resolved["allow_unknown_cost"] is False
    # The global USD 0.00 hard guard overrides repository-level paid opt-ins.
    assert resolved["allow_paid"] is False
    assert resolved["free_only"] is True
    assert resolved["allow_unknown_cost"] is False


def test_invalid_policy_json_fails_closed_to_defaults():
    assert load_workflow_policies("{")["config_warning"] == "invalid_json"
