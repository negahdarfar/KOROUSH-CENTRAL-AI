# Dynamic Extension Registry v1

The central hub supports registering and discovering new agent, model, tool, API, data-source, and connector manifests without changing the central application code for each catalog entry.

## Admin registration

`POST /api/extensions` requires `X-Admin-Key` and accepts a versioned JSON manifest. The registry stores metadata in the same SQLite database path selected by `USAGE_DB_PATH`. Re-registering the same extension ID and version updates that exact version; publishing a new version creates a separate record.

## Tenant discovery

`GET /api/extensions?repository=owner/repository&kind=agent` requires a tenant key assigned to that repository and the explicit `registry:read` scope. Manifests with an empty repository list are shared catalog entries; otherwise only matching repositories see them. Disabled entries are hidden from tenants.

## Manifest contract

Kinds: `agent`, `model`, `tool`, `api`, `data_source`, `connector`. Versions use numeric `MAJOR.MINOR.PATCH`. Manifests may describe capabilities, domains, HTTPS endpoint, input/output JSON schemas, and pricing metadata.

## Security and compatibility boundaries

- Registry records are data, never executable code. No dynamic Python imports, shell execution, plugin installation, or arbitrary code loading occurs.
- An endpoint is a declaration only. This release does not call it, validate its TLS certificate, verify ownership, or establish its trustworthiness.
- Trust and pricing are always labeled unverified; a `pricing` object is descriptive and cannot bypass the zero-cost guard.
- Existing tenant keys do not receive `registry:read` automatically. An administrator must explicitly issue/update access through the existing tenant-key management process.
- Schema documents are stored as metadata only; this version does not yet execute JSON Schema validation or dispatch external agents.
- SQLite is the persistence backend; production durability still depends on verifying the mounted persistent volume and restart behavior.

This registry makes discovery and catalog synchronization data-driven. Execution adapters, event delivery, and cross-repository orchestration remain separate phases and must be enabled with their own scoped contracts.
