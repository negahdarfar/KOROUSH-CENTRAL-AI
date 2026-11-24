# Tenant job idempotency and read authorization

Tenant job submission now stores a SHA-256 digest of canonical JSON payload content alongside the opaque encrypted payload reference. Reusing the same (repository, idempotency_key) is accepted only when tenant key, team, user, job type, and payload digest match. A changed or legacy-unverifiable payload returns HTTP 409; the newly encrypted retry payload is deleted.

The digest is one-way metadata and does not replace encryption. It is used only to compare retries and is not returned by API responses.

Job submission requires jobs:enqueue. Reading job status and result requires the separate jobs:read scope and exact creating key/user/team/repository binding. A caller without read scope receives the same 404 as a non-existent or unauthorized job to avoid disclosing job existence.

Existing tenant keys are not silently granted the new scope. Operators must explicitly issue a replacement key with jobs:read if status/result access is intended.