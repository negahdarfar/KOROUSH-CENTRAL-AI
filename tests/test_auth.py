import pytest
from fastapi import HTTPException

from app import main


def test_admin_key_accepts_exact_match(monkeypatch):
    monkeypatch.setattr(main.settings, "admin_api_key", "test-secret")
    assert main.require_admin("test-secret") is None


@pytest.mark.parametrize("candidate", [None, "", "wrong-secret", " test-secret", "test-secret "])
def test_admin_key_rejects_invalid_values(monkeypatch, candidate):
    monkeypatch.setattr(main.settings, "admin_api_key", "test-secret")
    with pytest.raises(HTTPException) as exc:
        main.require_admin(candidate)
    assert exc.value.status_code == 401


def test_admin_key_fails_closed_when_not_configured(monkeypatch):
    monkeypatch.setattr(main.settings, "admin_api_key", "")
    with pytest.raises(HTTPException) as exc:
        main.require_admin("anything")
    assert exc.value.status_code == 503
