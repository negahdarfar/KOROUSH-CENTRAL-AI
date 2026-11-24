import asyncio
import sqlite3

import pytest
from fastapi import HTTPException

from app.evidence_routes import EvidenceRecordRequest, create_evidence_record, get_evidence_records
from app.quota_guard import _db_path
from app.tenant_auth import create_tenant_key


def _tenant(monkeypatch, tmp_path, user="analyst"):
    monkeypatch.setenv("USAGE_DB_PATH", str(tmp_path / "evidence-registry.sqlite3"))
    monkeypatch.setenv("TENANT_AUTH_PEPPER", "evidence-test-pepper-value-at-least-32-chars")
    return create_tenant_key(
        user_id=user,
        team_id="research-team",
        repositories=["org/research"],
        scopes=["evidence:write", "evidence:read"],
    )["api_key"]


def _request(source_id="feed-item-1", text="Supplied market evidence."):
    return EvidenceRecordRequest(
        repository="org/research",
        domain="forex",
        source_id=source_id,
        text=text,
        publisher="Example Research",
        source_url="https://example.org/reports/market",
        observed_at="2026-11-24T10:00:00Z",
    )


def test_evidence_registry_persists_metadata_not_source_text(monkeypatch, tmp_path):
    key = _tenant(monkeypatch, tmp_path)
    created = asyncio.run(create_evidence_record(_request(), x_tenant_key=key))
    assert created["content_stored"] is False
    assert len(created["content_sha256"]) == 64
    assert created["source_host"] == "example.org"
    assert created["freshness"] in {"fresh", "recent", "stale"}

    conn = sqlite3.connect(_db_path())
    try:
        columns = [row[1] for row in conn.execute("PRAGMA table_info(evidence_registry)")]
        assert "text" not in columns
        assert "content" not in columns
        assert conn.execute("SELECT COUNT(*) FROM evidence_registry").fetchone()[0] == 1
    finally:
        conn.close()


def test_evidence_registry_is_idempotent_and_rejects_changed_content(monkeypatch, tmp_path):
    key = _tenant(monkeypatch, tmp_path)
    first = asyncio.run(create_evidence_record(_request(), x_tenant_key=key))
    replay = asyncio.run(create_evidence_record(_request(), x_tenant_key=key))
    assert replay["evidence_id"] == first["evidence_id"]
    assert replay["idempotent_replay"] is True

    with pytest.raises(HTTPException) as exc:
        asyncio.run(create_evidence_record(_request(text="Different content"), x_tenant_key=key))
    assert exc.value.status_code == 409


def test_evidence_registry_list_is_tenant_scoped(monkeypatch, tmp_path):
    owner = _tenant(monkeypatch, tmp_path, user="owner")
    asyncio.run(create_evidence_record(_request(), x_tenant_key=owner))
    other = create_tenant_key(
        user_id="other", team_id="research-team", repositories=["org/research"],
        scopes=["evidence:read"],
    )["api_key"]
    result = asyncio.run(get_evidence_records(
        repository="org/research", domain="forex", limit=20, x_tenant_key=other,
    ))
    assert result["count"] == 0


def test_evidence_registry_requires_explicit_scope(monkeypatch, tmp_path):
    key = create_tenant_key(
        user_id="read-only", team_id="research-team", repositories=["org/research"],
        scopes=["inference:chat"],
    )["api_key"]
    monkeypatch.setenv("USAGE_DB_PATH", str(tmp_path / "evidence-registry.sqlite3"))
    monkeypatch.setenv("TENANT_AUTH_PEPPER", "evidence-test-pepper-value-at-least-32-chars")
    with pytest.raises(HTTPException) as exc:
        asyncio.run(create_evidence_record(_request(), x_tenant_key=key))
    assert exc.value.status_code == 403


def test_evidence_registry_rejects_unsafe_url(monkeypatch, tmp_path):
    key = _tenant(monkeypatch, tmp_path)
    request = EvidenceRecordRequest(
        repository="org/research", domain="nft", source_id="bad-url",
        text="Evidence", source_url="http://example.org/insecure",
    )
    with pytest.raises(HTTPException) as exc:
        asyncio.run(create_evidence_record(request, x_tenant_key=key))
    assert exc.value.status_code == 422
