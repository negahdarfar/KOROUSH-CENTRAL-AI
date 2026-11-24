# Universal Agent Event Bus v1

This release adds a tenant-scoped durable event transport for opt-in repository and agent coordination.

## API

- `POST /api/events` publishes an event and encrypts its JSON payload using the existing job payload vault.
- `POST /api/events/claim` claims the next event for an exact repository, consumer and authenticated tenant.
- `POST /api/events/{event_id}/settle` acknowledges delivery or schedules a bounded retry/dead-letter transition.
- `GET /api/events?repository=owner/repository` returns metadata only.

Each tenant key must be explicitly issued the required `events:publish`, `events:consume`, and/or `events:read` scopes. Existing keys are not upgraded automatically. Repository assignment is checked on every operation. Event records retain only a vault reference, never the payload body. Claim leases are fenced by worker identity and expiry; delivery is at-least-once, so consumers must implement idempotent processing.

## Compatibility and operational limits

The event bus does not execute code, fetch external endpoints, grant repository access, or synchronize downstream repositories by itself. Consumers must be separately deployed and explicitly authorized. The SQLite database must be on verified persistent storage for restart durability. The current service is single-process; multi-replica workers require a separately designed coordination layer. Payload access requires the existing `JOB_PAYLOAD_ENCRYPTION_KEY`. No existing downstream repository code is modified.
