# Durable job queue

The queue in `app.durable_jobs` is a persistence primitive, not an enabled background execution service.

## Guarantees
- SQLite transactions use `BEGIN IMMEDIATE` for atomic enqueue and claim.
- `(repository, idempotency_key)` is unique, so repeated enqueue calls return the same job.
- Worker leases are time-bounded. An expired lease can be reclaimed by another worker.
- Completion and failure are fenced by the current lease owner.
- Retryable failures use bounded exponential backoff; exhausted or non-retryable jobs enter `dead_letter`.
- Status lookup is repository-scoped and does not expose payload references.

## Data handling boundary
Only a constrained opaque `payload_ref` is persisted. Do not put prompts, source files, access tokens, API keys, personal data, or other secret-bearing content in this field. The referenced payload store must independently provide access control, encryption at rest, retention, and deletion. No payload store or worker-to-provider dispatch is wired by this PR.

## Production prerequisites
- Mount a persistent Railway Volume at `/data`.
- Set `USAGE_DB_PATH=/data/koroush_usage.sqlite3`.
- Verify volume write access and persistence across a controlled restart before relying on jobs.
- Do not run multiple independent SQLite writers across hosts or network filesystems. For multi-instance scale, migrate the queue to PostgreSQL with row-level locking and equivalent lease fencing.
- A queue worker must apply tenant authorization, repository allowlist, verified zero-price policy, quota reservation, and usage accounting at execution time. Enqueue alone is not authorization to call a provider.

## Current scope
The queue is not exposed as an HTTP API, not started as a worker, and does not yet execute jobs. This is deliberate: payload storage, tenant-bound enqueue authorization, and execution-time policy checks must be implemented and tested before activating background inference.
