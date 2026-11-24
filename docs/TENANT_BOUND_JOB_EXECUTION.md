# Tenant-bound job execution framework

## What this change provides
- Jobs can be bound to a tenant key ID, team ID and user ID.
- Enqueue requires a tenant identity with the explicit `jobs:enqueue` scope and exact repository membership.
- Existing SQLite tables are migrated additively; no destructive migration is performed.
- Before a registered handler runs, the worker rechecks that the key is still active and that repository/team membership still matches.
- A revoked or mismatched key is rejected before handler execution.
- The worker uses the queue's owner-fenced completion and bounded retry behavior.

## Deliberate non-activation
This PR does **not** start a worker in the web process and registers no default handlers. It does not expose a public job enqueue route. A job handler is executable only when an operator wires an explicit handler registry into a separately managed worker process.

No inference handler is included. Before adding one, the implementation must resolve payload references from an authenticated, encrypted payload store and apply, immediately before every provider attempt:
1. tenant key and repository authorization;
2. operator repository allowlist;
3. trusted exact-model zero-price evidence;
4. atomic quota reservation;
5. provider-specific timeout/retry classification;
6. usage finalization and redacted audit logging.

The existing opaque payload reference is not a payload store. Do not place prompts, personal data, source code or credentials in it.

## Deployment boundary
No Railway environment variables, secrets, volume, or deployment are changed by this PR. SQLite persistence still requires a Railway Volume mounted at `/data` and a controlled restart-persistence test. The worker is a single-host SQLite design; multi-instance execution requires PostgreSQL and distributed lease fencing.
