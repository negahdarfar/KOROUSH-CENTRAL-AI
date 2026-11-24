import pytest

from app.tenant_auth import (
    TenantAuthError,
    authenticate_tenant_key,
    authorize_tenant_inference,
    create_tenant_key,
    list_tenant_keys,
    revoke_tenant_key,
)


def setup_auth(tmp_path, monkeypatch):
    monkeypatch.setenv("USAGE_DB_PATH", str(tmp_path / "tenant.sqlite3"))
    monkeypatch.setenv("TENANT_AUTH_PEPPER", "test-only-pepper-with-at-least-32-chars")


def test_key_is_hashed_and_authentication_is_team_repository_scoped(tmp_path, monkeypatch):
    setup_auth(tmp_path, monkeypatch)
    created = create_tenant_key(
        user_id="alice", team_id="youtube",
        repositories=["Org/Shorts"], scopes=["inference:chat"],
    )
    identity = authenticate_tenant_key(created["api_key"])
    assert identity["user_id"] == "alice"
    assert identity["team_id"] == "youtube"
    assert identity["repositories"] == ["org/shorts"]
    assert authorize_tenant_inference(created["api_key"], "ORG/SHORTS")["team_id"] == "youtube"
    with pytest.raises(TenantAuthError, match="not assigned"):
        authorize_tenant_inference(created["api_key"], "org/trading")
    assert created["api_key"] not in str(list_tenant_keys())


def test_jobs_read_scope_is_allowlisted(tmp_path, monkeypatch):
    setup_auth(tmp_path, monkeypatch)
    created = create_tenant_key(user_id="alice", team_id="youtube", repositories=["org/shorts"], scopes=["jobs:read"])
    assert authenticate_tenant_key(created["api_key"])["scopes"] == ["jobs:read"]


def test_revoked_key_is_rejected(tmp_path, monkeypatch):
    setup_auth(tmp_path, monkeypatch)
    created = create_tenant_key(user_id="bob", team_id="trading", repositories=["org/fx"])
    assert revoke_tenant_key(created["key_id"]) is True
    assert authenticate_tenant_key(created["api_key"]) is None
    assert revoke_tenant_key(created["key_id"]) is False


def test_repository_cannot_be_assigned_to_two_teams(tmp_path, monkeypatch):
    setup_auth(tmp_path, monkeypatch)
    create_tenant_key(user_id="alice", team_id="youtube", repositories=["org/project"])
    with pytest.raises(TenantAuthError, match="another team"):
        create_tenant_key(user_id="bob", team_id="trading", repositories=["org/project"])


def test_auth_fails_closed_without_pepper(tmp_path, monkeypatch):
    monkeypatch.setenv("USAGE_DB_PATH", str(tmp_path / "tenant.sqlite3"))
    monkeypatch.delenv("TENANT_AUTH_PEPPER", raising=False)
    with pytest.raises(RuntimeError, match="TENANT_AUTH_PEPPER"):
        create_tenant_key(user_id="alice", team_id="youtube", repositories=["org/shorts"])


def test_scopes_are_allowlisted(tmp_path, monkeypatch):
    setup_auth(tmp_path, monkeypatch)
    with pytest.raises(TenantAuthError, match="Unsupported"):
        create_tenant_key(user_id="alice", team_id="youtube", repositories=["org/shorts"], scopes=["admin:*"])



@pytest.mark.parametrize(
    "repository",
    [
        "org/repo/extra",
        "org name/repo",
        "org/repo name",
        "https://github.com/org/repo",
        "../repo",
        "org/..",
        "org/repo.git",
        "org/repo?admin=true",
    ],
)
def test_invalid_github_repository_identity_is_rejected(tmp_path, monkeypatch, repository):
    setup_auth(tmp_path, monkeypatch)
    with pytest.raises(TenantAuthError, match="valid exact GitHub"):
        create_tenant_key(
            user_id="alice",
            team_id="youtube",
            repositories=[repository],
        )
