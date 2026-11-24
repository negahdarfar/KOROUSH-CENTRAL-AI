# Controlled dead-letter recovery

Operators may requeue a single dead-letter job through POST /api/admin/jobs/{job_id}/requeue. The endpoint requires the operator ADMIN_API_KEY, an explicit confirm=true value, the exact repository, and the job's current updated_at value as an optimistic concurrency token.

Recovery is refused if the job is not dead-lettered, its row changed since it was inspected, its encrypted payload is missing or expired, or the job has already been manually requeued three times. A successful recovery resets the per-attempt counter, increments a separate manual_requeues counter, clears the prior error code, and makes the job eligible for normal worker claiming. Normal tenant authorization, model routing, quota reservation, provider price evidence, and worker lease fencing still apply during execution.

The endpoint does not expose payload contents or references. It returns only job metadata required to confirm the state transition. This is an operator recovery control, not an automatic retry bypass or a way to override tenant policy.

Every successful operator requeue writes a metadata-only `job_admin_events` row in the same SQLite transaction as the state change. The audit row records job ID, repository, action, event time, and manual requeue count; it never records admin credentials, payloads, prompts, or tenant secrets. The audit record and queue transition therefore commit or roll back together.

## Recovery audit endpoint

Administrators can inspect operator recovery events at GET /api/admin/jobs/recovery-audit. The endpoint requires the same ADMIN_API_KEY, supports an optional repository filter, and limits each page to 1–100 events. Use both `next_before_event_at` and `next_before_event_id` as the next request's cursor to avoid skipping events that share the same timestamp. The endpoint returns event metadata only and never reads encrypted job payloads.
