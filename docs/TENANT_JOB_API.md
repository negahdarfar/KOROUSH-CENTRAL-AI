# Tenant durable job API

## Endpoints

### Submit
`POST /api/jobs`

Headers:
- `X-Tenant-Key: kor_...`
- `Content-Type: application/json`

Body:
```json
{
  "repository": "owner/repository",
  "job_type": "audit.run",
  "idempotency_key": "client-generated-unique-operation-id",
  "payload": {"task": "bounded job input"},
  "max_attempts": 5
}
```

The API requires a valid, non-revoked tenant key, exact repository assignment and the `jobs:enqueue` scope. It encrypts the payload before persistence and returns only job metadata. The raw payload and opaque vault reference are not returned.

### Status
`GET /api/jobs/{job_id}?repository=owner/repository`

The response is restricted to the exact tenant key, team and user identity that submitted the job. Other tenants receive 404 to avoid confirming another tenant's job existence.

## Idempotency
The unique key is scoped to repository and atomically bound to tenant key, team, user and job type. A retry with the same identity and job type returns the original job; the first payload wins. The newly encrypted retry payload is deleted. Reuse by another tenant or for another job type is rejected.

## Execution boundary
This API persists and exposes job status. It does not start a worker, register inference handlers, or promise that a queued job will execute. Worker activation remains a separate controlled step and requires a registered handler with execution-time tenant authorization, zero-price evidence and quota enforcement. The existing default worker registry is empty.
