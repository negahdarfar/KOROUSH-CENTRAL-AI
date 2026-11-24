# Controlled durable inference worker

## Scope
The worker is opt-in and currently registers exactly one handler: `chat.completion`. The handler accepts 1–20 messages, only system/user/assistant roles, 12,000 characters per message, 30,000 combined characters, temperature 0–1 and output cap 2,048 tokens. It does not execute repository code, shell commands or arbitrary Python.

Every inference attempt is delegated to the existing central `_chat_completion_with_free_failover` path. That path rechecks the operator repository allowlist, authenticated AvalAI model catalog, explicit zero input/output pricing, chat capability, and internal per-repository request/token reservations. No unknown-price or paid fallback is enabled.

## Worker lifecycle
The FastAPI lifespan starts one polling worker in the same process only when `JOB_WORKER_ENABLED=true`. Default is disabled. Poll interval is `JOB_WORKER_POLL_SECONDS` (bounded to 0.5–30 seconds; default 2). The worker also requires `JOB_PAYLOAD_ENCRYPTION_KEY`; if absent it logs a safe configuration error and does not start.

This is a single-process worker, not a horizontally scalable worker pool. Run one application replica for this SQLite queue unless a separate coordination/storage architecture is implemented and tested. The queue, payloads and result ciphertext share the configured SQLite database.

## Submission
`POST /api/jobs` accepts only `job_type=chat.completion`. It returns 503 while the worker is disabled, preventing silent accumulation of jobs that cannot run. Requests require a valid tenant key with the exact repository assignment and `jobs:enqueue` scope.

Example payload:
```json
{
  "repository": "owner/repository",
  "job_type": "chat.completion",
  "idempotency_key": "client-operation-unique-id",
  "payload": {
    "task": "general",
    "messages": [{"role": "user", "content": "Summarize this topic"}],
    "temperature": 0.2,
    "max_tokens": 1200
  },
  "max_attempts": 3
}
```

## Results and failure behavior
Successful handler output is encrypted with the same Fernet key and stored as an expiring payload. Tenant-scoped status retrieval decrypts and returns the result while it remains available (default payload TTL 24 hours). Expired results are marked unavailable. Completion is fenced by worker ID and a non-expired lease; a late worker cannot mark a reclaimed job successful.

Invalid job input and unavailable/tampered payloads are terminal. Transient handler failures use bounded retry/backoff. A worker crash leaves the lease to expire for safe reclamation. As with any external inference, a crash after provider success but before result commit can cause a retry; upstream exactly-once execution is not guaranteed.

## Required runtime configuration
- `JOB_WORKER_ENABLED=true` — explicit opt-in.
- `JOB_PAYLOAD_ENCRYPTION_KEY` — Fernet URL-safe base64 key; keep as a secret.
- `TENANT_AUTH_PEPPER` — at least 32 characters for tenant API key authentication.
- `ALLOWED_REPOS` — operator allowlist; tenant assignment does not replace it.
- `LLM_PROVIDER=avalai` and `AVALAI_API_KEY` — authenticated catalog access used for free-price evidence.
- `USAGE_DB_PATH=/data/koroush_usage.sqlite3` with a persistent Railway Volume mounted at `/data`.

Internal quota defaults are application safeguards, not a guarantee of a provider's free tier. No Railway variables, secrets, volumes, or deployment are changed by this PR.
