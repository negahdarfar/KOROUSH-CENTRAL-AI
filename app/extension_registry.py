"""Versioned, metadata-only registry for runtime-discoverable extensions."""
from __future__ import annotations

import json
import re
import sqlite3
from datetime import datetime, timezone
from urllib.parse import urlsplit

from .quota_guard import _db_path
from .schema_registry import SchemaValidationError, validate_schema

_ID = re.compile(r"^[a-z][a-z0-9]*(?:[.-][a-z0-9]+){1,7}$")
_KINDS = {"agent", "model", "tool", "api", "data_source", "connector"}
_DOMAINS = {"forex", "youtube", "ptc", "nft", "general"}


class ExtensionRegistryError(ValueError):
    pass


def _connect():
    path = _db_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(path), timeout=10, isolation_level=None)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA busy_timeout=10000")
    conn.execute("""
        CREATE TABLE IF NOT EXISTS extension_registry (
            extension_id TEXT NOT NULL,
            version TEXT NOT NULL,
            kind TEXT NOT NULL,
            name TEXT NOT NULL,
            protocol TEXT NOT NULL,
            endpoint TEXT,
            capabilities_json TEXT NOT NULL,
            domains_json TEXT NOT NULL,
            repositories_json TEXT NOT NULL,
            manifest_json TEXT NOT NULL,
            status TEXT NOT NULL,
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL,
            PRIMARY KEY(extension_id, version)
        )
    """)
    conn.execute("CREATE INDEX IF NOT EXISTS ix_extension_status_kind ON extension_registry(status, kind, extension_id)")
    return conn


def _validate(manifest: dict) -> dict:
    if not isinstance(manifest, dict):
        raise ExtensionRegistryError("manifest must be a JSON object")
    allowed = {"extension_id", "version", "kind", "name", "protocol", "endpoint", "capabilities", "domains", "repositories", "description", "status", "input_schema", "output_schema", "pricing"}
    unknown = set(manifest) - allowed
    if unknown:
        raise ExtensionRegistryError("unknown manifest fields: " + ", ".join(sorted(unknown)))
    item = dict(manifest)
    extension_id = item.get("extension_id")
    if not isinstance(extension_id, str) or not _ID.fullmatch(extension_id) or len(extension_id) > 100:
        raise ExtensionRegistryError("extension_id must be a stable lowercase dotted or hyphenated identifier")
    version = item.get("version")
    if not isinstance(version, str) or not re.fullmatch(r"[0-9]+\.[0-9]+\.[0-9]+", version):
        raise ExtensionRegistryError("version must use numeric MAJOR.MINOR.PATCH")
    if item.get("kind") not in _KINDS:
        raise ExtensionRegistryError("unsupported extension kind")
    for field, maximum in (("name", 120), ("protocol", 60), ("description", 1000)):
        value = item.get(field, "")
        if not isinstance(value, str) or not value.strip() or len(value) > maximum:
            raise ExtensionRegistryError(f"{field} is required and must be at most {maximum} characters")
        item[field] = value.strip()
    endpoint = item.get("endpoint")
    if endpoint is not None:
        if not isinstance(endpoint, str) or len(endpoint) > 2048:
            raise ExtensionRegistryError("endpoint must be an HTTPS URL of at most 2048 characters")
        try:
            parsed = urlsplit(endpoint)
            port = parsed.port
        except ValueError as exc:
            raise ExtensionRegistryError("endpoint URL is malformed") from exc
        if parsed.scheme != "https" or not parsed.hostname or parsed.username or parsed.password or port not in (None, 443):
            raise ExtensionRegistryError("endpoint must use HTTPS, default port, and contain no credentials")
    for field in ("capabilities", "domains", "repositories"):
        values = item.get(field, [])
        if not isinstance(values, list) or len(values) > 30 or any(not isinstance(v, str) or not v.strip() or len(v) > 100 for v in values):
            raise ExtensionRegistryError(f"{field} must be a bounded list of strings")
        if len(set(values)) != len(values):
            raise ExtensionRegistryError(f"{field} must not contain duplicates")
        item[field] = sorted(values)
    if not set(item["domains"]).issubset(_DOMAINS):
        raise ExtensionRegistryError("unsupported domain")
    for repo in item["repositories"]:
        if not re.fullmatch(r"[a-z0-9][a-z0-9-]{0,38}/[a-z0-9][a-z0-9._-]{0,99}", repo.lower()):
            raise ExtensionRegistryError("repositories must use owner/repository identities")
    for field in ("input_schema", "output_schema"):
        value = item.get(field, {})
        if not isinstance(value, dict) or len(json.dumps(value, ensure_ascii=True)) > 8000:
            raise ExtensionRegistryError(f"{field} must be a JSON object no larger than 8 KB")
        try:
            validate_schema(value)
        except SchemaValidationError as exc:
            raise ExtensionRegistryError(f"{field} is not a supported bounded JSON Schema: {exc}") from exc
    value = item.get("pricing", {})
    if not isinstance(value, dict) or len(json.dumps(value, ensure_ascii=True)) > 8000:
        raise ExtensionRegistryError("pricing must be a JSON object no larger than 8 KB")
    item["status"] = item.get("status", "active")
    if not isinstance(item["status"], str) or item["status"] not in {"active", "disabled"}:
        raise ExtensionRegistryError("status must be active or disabled")
    # Catalog entries never authorize code execution or imply verified free pricing.
    item["execution"] = "external-contract-only" if endpoint else "catalog-only"
    item["trust"] = "unverified"
    item["pricing_status"] = "unverified"
    return item


def register_extension(manifest: dict) -> dict:
    item = _validate(manifest)
    now = datetime.now(timezone.utc).isoformat()
    conn = _connect()
    try:
        conn.execute("BEGIN IMMEDIATE")
        existing = conn.execute(
            "SELECT manifest_json FROM extension_registry WHERE extension_id=? AND version=?",
            (item["extension_id"], item["version"]),
        ).fetchone()
        serialized = json.dumps(item, sort_keys=True)
        if existing:
            if existing["manifest_json"] != serialized:
                raise ExtensionRegistryError("published extension versions are immutable; register a new version")
            conn.commit()
            return item
        conn.execute("""
            INSERT INTO extension_registry
            (extension_id,version,kind,name,protocol,endpoint,capabilities_json,domains_json,repositories_json,manifest_json,status,created_at,updated_at)
            VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?)
        """, (item["extension_id"], item["version"], item["kind"], item["name"], item["protocol"],
              item.get("endpoint"), json.dumps(item["capabilities"]), json.dumps(item["domains"]),
              json.dumps(item["repositories"]), serialized, item["status"], now, now))
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()
    return item


def list_extensions(*, repository: str | None = None, kind: str | None = None, include_disabled: bool = False) -> list[dict]:
    if kind is not None and kind not in _KINDS:
        raise ExtensionRegistryError("unsupported extension kind")
    conn = _connect()
    try:
        clauses, params = [], []
        if not include_disabled:
            clauses.append("status='active'")
        if kind:
            clauses.append("kind=?")
            params.append(kind)
        rows = conn.execute("SELECT manifest_json FROM extension_registry" + (" WHERE " + " AND ".join(clauses) if clauses else "") + " ORDER BY kind,extension_id,version", params).fetchall()
        items = [json.loads(row["manifest_json"]) for row in rows]
        if repository is not None:
            repo = repository.strip().lower()
            items = [item for item in items if not item["repositories"] or repo in [value.lower() for value in item["repositories"]]]
        return items
    finally:
        conn.close()
