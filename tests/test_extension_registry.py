import pytest

from app.extension_registry import (
    ExtensionRegistryError,
    _validate,
    list_extensions,
    register_extension,
)


def manifest(**overrides):
    item = {
        "extension_id": "community.text-summarizer",
        "version": "1.0.0",
        "kind": "agent",
        "name": "Community Summarizer",
        "protocol": "koroush-agent-v1",
        "endpoint": "https://agent.example.org/v1/run",
        "capabilities": ["summarize"],
        "domains": ["general", "youtube"],
        "repositories": ["negahdarfar/demo"],
        "description": "External summarization service",
        "input_schema": {"type": "object"},
        "output_schema": {"type": "object"},
        "pricing": {"model": "unverified"},
    }
    item.update(overrides)
    return item


def test_manifest_is_normalized_and_never_claims_verified_free_execution():
    item = _validate(manifest())
    assert item["execution"] == "external-contract-only"
    assert item["trust"] == "unverified"
    assert item["pricing_status"] == "unverified"


@pytest.mark.parametrize("changes", [
    {"endpoint": "http://agent.example.org/run"},
    {"endpoint": "https://user:pass@agent.example.org/run"},
    {"endpoint": "https://agent.example.org:9443/run"},
    {"version": "latest"},
    {"kind": "python_code"},
    {"status": "running"},
    {"surprise": "field"},
    {"repositories": ["not a repo"]},
])
def test_manifest_rejects_unsafe_or_unknown_values(changes):
    with pytest.raises(ExtensionRegistryError):
        _validate(manifest(**changes))


def test_manifest_rejects_oversized_schemas():
    with pytest.raises(ExtensionRegistryError):
        _validate(manifest(input_schema={"blob": "x" * 9000}))


def test_registry_persists_versioned_manifests_and_filters_repository(tmp_path, monkeypatch):
    from app import extension_registry
    monkeypatch.setattr(extension_registry, "_db_path", lambda: tmp_path / "registry.sqlite3")
    first = register_extension(manifest())
    second = register_extension(manifest(version="1.1.0"))
    visible = list_extensions(repository="negahdarfar/demo")
    hidden = list_extensions(repository="other/project")
    assert first["version"] == "1.0.0"
    assert second["version"] == "1.1.0"
    assert len(visible) == 2
    assert hidden == []


def test_disabled_extension_is_hidden_from_tenants(tmp_path, monkeypatch):
    from app import extension_registry
    monkeypatch.setattr(extension_registry, "_db_path", lambda: tmp_path / "registry.sqlite3")
    register_extension(manifest(status="disabled"))
    assert list_extensions(repository="negahdarfar/demo") == []
    assert len(list_extensions(include_disabled=True)) == 1


def test_published_version_is_immutable_and_new_version_is_required(tmp_path, monkeypatch):
    from app import extension_registry
    monkeypatch.setattr(extension_registry, "_db_path", lambda: tmp_path / "immutable.sqlite3")
    register_extension(manifest())
    with pytest.raises(ExtensionRegistryError, match="immutable"):
        register_extension(manifest(name="Changed without version bump"))
    assert register_extension(manifest(version="1.0.1", name="Changed in a new version"))["version"] == "1.0.1"


def test_manifest_validates_nested_json_schemas_and_rejects_invalid_contracts():
    valid = {
        "type": "object",
        "properties": {
            "text": {"type": "string", "minLength": 1, "maxLength": 12000}
        },
        "required": ["text"],
        "additionalProperties": False,
    }
    assert _validate(manifest(input_schema=valid, output_schema={"type": "object"}))["input_schema"] == valid

    invalid_cases = [
        {"type": "object", "required": ["missing"]},
        {"type": "array"},
        {"type": "object", "properties": {"code": {"type": "python"}}},
        {"type": "string", "minimum": 0},
    ]
    for schema in invalid_cases:
        with pytest.raises(ExtensionRegistryError, match="supported bounded JSON Schema"):
            _validate(manifest(input_schema=schema))



def test_future_repository_connector_can_register_generic_research_capability(tmp_path, monkeypatch):
    from app import extension_registry
    monkeypatch.setattr(extension_registry, "_db_path", lambda: tmp_path / "future.sqlite3")
    item = register_extension(manifest(
        extension_id="acme.future-project",
        kind="connector",
        name="Future Project Adapter",
        protocol="koroush-research-v1",
        capabilities=["research.workflow.v1"],
        domains=["general"],
        repositories=["acme/future-project"],
    ))
    visible = list_extensions(repository="acme/future-project", kind="connector")
    assert item["extension_id"] == "acme.future-project"
    assert len(visible) == 1
    assert visible[0]["capabilities"] == ["research.workflow.v1"]
    assert visible[0]["execution"] == "external-contract-only"
    assert visible[0]["trust"] == "unverified"


def test_admin_can_register_versioned_forex_data_source_for_tenant_discovery(tmp_path, monkeypatch):
    from app import extension_registry
    monkeypatch.setattr(extension_registry, "_db_path", lambda: tmp_path / "data-sources.sqlite3")
    item = register_extension(manifest(
        extension_id="provider.fx-public-feed",
        version="1.0.0",
        kind="data_source",
        name="Public FX OHLC Feed",
        protocol="koroush-market-data-v1",
        endpoint="https://prices.example.org/v1/ohlc",
        capabilities=["market.ohlc.v1"],
        domains=["forex"],
        repositories=["negahdarfar/daily-forex-analyze-"],
        pricing={"cost_usd": 0, "zero_cost_attested_by_admin": True, "source_reviewed_by_admin": True,
                 "terms_url": "https://prices.example.org/terms"},
    ))
    visible = list_extensions(
        repository="negahdarfar/daily-forex-analyze-", kind="data_source"
    )
    assert item["kind"] == "data_source"
    assert item["protocol"] == "koroush-market-data-v1"
    assert len(visible) == 1
    assert visible[0]["capabilities"] == ["market.ohlc.v1"]
    assert visible[0]["pricing_status"] == "unverified"
    assert visible[0]["trust"] == "unverified"
