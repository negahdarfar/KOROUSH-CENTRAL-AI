from app.model_router import rank_avalai_models
from app.workflow_registry import resolve_workflow_policy


def test_zero_budget_policy_cannot_be_relaxed_by_repository_or_team():
    policies = {
        "defaults": {"free_only": False, "allow_unknown_cost": True, "allow_paid": True},
        "teams": {"engineering": {"free_only": False, "allow_paid": True}},
        "repositories": {"negahdarfar/demo": {"free_only": False, "allow_unknown_cost": True, "allow_paid": True}},
    }
    policy = resolve_workflow_policy(repository="negahdarfar/demo", team="engineering", policies=policies)
    assert policy["free_only"] is True
    assert policy["allow_unknown_cost"] is False
    assert policy["allow_paid"] is False


def test_zero_budget_router_only_returns_catalog_confirmed_free_chat_models():
    catalog = [
        {"id": "known-free", "mode": "chat", "pricing": {"input": 0, "output": 0}},
        {"id": "unknown-price", "mode": "chat"},
        {"id": "paid-model", "mode": "chat", "pricing": {"input": 0.1, "output": 0.2}},
    ]
    eligible = rank_avalai_models(catalog, free_only=True, allow_unknown_cost=False, allow_paid=False)
    assert [item["id"] for item in eligible] == ["known-free"]


def test_zero_budget_router_returns_no_model_if_price_is_unknown_or_paid():
    catalog = [
        {"id": "unknown-price", "mode": "chat"},
        {"id": "paid-model", "mode": "chat", "pricing": {"input": 0.1, "output": 0.2}},
    ]
    assert rank_avalai_models(catalog, free_only=True, allow_unknown_cost=False, allow_paid=False) == []
