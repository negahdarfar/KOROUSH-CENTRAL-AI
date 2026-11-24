import pytest
import hashlib

from app.event_bus import EventBusError, claim_event, list_events, publish_event, settle_event


def identity(key="11111111-1111-4111-8111-111111111111", repo="negahdarfar/demo"):
    return {"key_id": key, "team_id": "team-a", "user_id": "user-a",
            "repositories": [repo], "scopes": ["events:publish", "events:consume", "events:read"]}


def publish(identity_value, key="evt-1", ref="vault:11111111-1111-4111-8111-111111111111"):
    return publish_event(identity=identity_value, repository="negahdarfar/demo",
        event_type="repo.sync.requested", schema_version=1, producer="hub",
        consumer="youtube-worker", idempotency_key=key, payload_ref=ref,
        payload_hash=hashlib.sha256(b"{}").hexdigest())


def test_publish_is_idempotent_and_metadata_only(tmp_path, monkeypatch):
    from app import event_bus
    monkeypatch.setattr(event_bus, "_db_path", lambda: tmp_path / "events.sqlite3")
    first = publish(identity())
    replay = publish(identity())
    assert first["event_id"] == replay["event_id"]
    assert replay["idempotent_replay"] is True
    rows = list_events(identity=identity(), repository="negahdarfar/demo")
    assert rows[0]["event_type"] == "repo.sync.requested"
    assert "payload_ref" not in rows[0]


def test_event_delivery_reclaims_expired_lease_and_fences_old_worker(tmp_path, monkeypatch):
    from app import event_bus
    monkeypatch.setattr(event_bus, "_db_path", lambda: tmp_path / "events.sqlite3")
    publish(identity())
    first = claim_event(identity=identity(), repository="negahdarfar/demo",
                        consumer="youtube-worker", worker_id="worker-a", lease_seconds=10)
    assert first
    conn = event_bus._connect()
    conn.execute("UPDATE platform_events SET lease_until='2000-01-01T00:00:00+00:00' WHERE event_id=?",
                 (first["event_id"],))
    conn.close()
    second = claim_event(identity=identity(), repository="negahdarfar/demo",
                         consumer="youtube-worker", worker_id="worker-b", lease_seconds=30)
    assert second["event_id"] == first["event_id"]
    with pytest.raises(EventBusError, match="lease"):
        settle_event(identity=identity(), repository="negahdarfar/demo",
                     event_id=first["event_id"], worker_id="worker-a", success=True)
    assert settle_event(identity=identity(), repository="negahdarfar/demo",
        event_id=second["event_id"], worker_id="worker-b", success=True)["status"] == "delivered"


def test_retry_and_dead_letter_are_bounded(tmp_path, monkeypatch):
    from app import event_bus
    monkeypatch.setattr(event_bus, "_db_path", lambda: tmp_path / "events.sqlite3")
    publish(identity())
    claimed = claim_event(identity=identity(), repository="negahdarfar/demo",
        consumer="youtube-worker", worker_id="worker-a", lease_seconds=30)
    # Force attempts to the configured maximum to exercise terminal failure.
    conn = event_bus._connect()
    conn.execute("UPDATE platform_events SET attempts=max_attempts WHERE event_id=?", (claimed["event_id"],))
    conn.close()
    result = settle_event(identity=identity(), repository="negahdarfar/demo",
        event_id=claimed["event_id"], worker_id="worker-a", success=False)
    assert result["status"] == "dead_letter"


def test_tenant_and_scope_isolation(tmp_path, monkeypatch):
    from app import event_bus
    monkeypatch.setattr(event_bus, "_db_path", lambda: tmp_path / "events.sqlite3")
    with pytest.raises(EventBusError, match="scope"):
        publish_event(identity={"key_id":"x","team_id":"t","repositories":["negahdarfar/demo"],"scopes":[]},
            repository="negahdarfar/demo", event_type="repo.sync.requested", schema_version=1,
            producer="hub", consumer="youtube-worker", idempotency_key="x",
            payload_ref="vault:11111111-1111-4111-8111-111111111111",\n            payload_hash=hashlib.sha256(b"{}").hexdigest())
    publish(identity())
    other = identity(key="22222222-2222-4222-8222-222222222222")
    assert list_events(identity=other, repository="negahdarfar/demo") == []
