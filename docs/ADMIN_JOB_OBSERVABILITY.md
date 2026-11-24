# Admin job queue observability

The operator-only endpoint GET /api/admin/jobs/summary reports aggregate counts for queued, running, succeeded, failed, and dead-letter jobs, the age of the oldest queued job, and the worker heartbeat state. An optional exact repository filter is supported.

Access requires the configured ADMIN_API_KEY in X-Admin-Key. Tenant API keys do not grant access. Responses intentionally omit job IDs, tenant IDs, user IDs, prompts, encrypted payload references, provider credentials, and filesystem paths.

This is an API endpoint, not a graphical dashboard. It reads the configured SQLite queue database and does not prove that the database is backed by a persistent Railway Volume.
