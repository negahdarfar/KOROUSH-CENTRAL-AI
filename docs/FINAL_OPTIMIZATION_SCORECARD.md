# KOROUSH CENTRAL AI — Final Optimization Scorecard

Date: 2026-11-24

## Current engineering assessment

**Provisional score: 7.4/10 for the current feature set; not a production-readiness certification.**

| Area | Score | Evidence / remaining work |
|---|---:|---|
| Zero-cost safety | 8.5/10 | Fail-closed model evidence and internal quotas exist; provider free tiers can change and are not guaranteed. |
| Repository isolation | 8/10 | Tenant API keys bind exact repositories and chat scope; operator allowlist remains a separate required boundary. |
| Secret handling | 8/10 | Tenant keys are HMAC-digested and shown once; pepper rotation requires key re-issuance. |
| Notification reliability | 7/10 | SQLite delivery ledger and retries exist; delivery is best-effort and can be at-least-once around process crashes. |
| Notification transport security | 8.5/10 | This hardening branch rejects authenticated SMTP without STARTTLS and rejects malformed ports or incomplete credentials. |
| Provider orchestration | 4/10 | Adapter registry/evidence checks exist; real cross-provider request dispatch and end-to-end failover are not complete. |
| Runtime durability | 5/10 | SQLite is only durable across restarts when Railway Volume is mounted at /data and USAGE_DB_PATH points there. |
| Operations/observability | 6/10 | Health/version endpoints and quota alerts exist; add readiness checks, structured correlation IDs, metrics and outage alerts. |
| Identity and administration | 5/10 | API-key tenant access exists; interactive login, MFA, SSO/OIDC, invitations and granular RBAC are not implemented. |
| Automated validation | 8/10 | The parent PR recorded 111 passing tests and successful CodeQL; this branch must receive its own CI/CodeQL run. |

## Architecture priorities

1. Keep the USD 0.00 global policy as the final, non-overridable gate. Never trust provider self-declared free flags.
2. Require exact owner/repository identity, tenant authorization, operator allowlist approval, and atomic quota reservation before every inference.
3. Keep non-chat capabilities blocked until their own zero-price evidence, quota accounting and security tests exist.
4. Implement provider dispatch as a separate adapter contract with provider-specific request/response normalization, bounded retries, circuit breakers and end-to-end tests. Never enable a provider merely because its environment variables are present.
5. Use a persistent SQLite volume or move to managed PostgreSQL before multi-instance horizontal scaling. SQLite on ephemeral storage is not production durable.
6. Run notification delivery from a single worker or use a shared durable queue with leases. Treat email/Telegram as best-effort notifications, not emergency paging.
7. Add readiness checks for database writable/persistent state, provider catalog freshness, and required secrets without ever returning secret values.
8. Add audit events for key creation/revocation, quota denials, provider selection, and admin actions; redact tokens, prompts and credentials from logs.
9. Add per-tenant rate limits and key expiry/rotation policy. Current tenant keys do not yet have expiration or self-service rotation.
10. Add integration tests against mocked provider transports and concurrent quota reservations before production activation.

## Production activation checklist

- Merge PR21 only after explicit operator approval and fresh CI/CodeQL review.
- Rebase/re-target PR22 onto main, then review and approve it separately.
- Mount Railway Volume at /data; set USAGE_DB_PATH=/data/koroush_usage.sqlite3.
- Configure ALLOWED_REPOS explicitly; an empty allowlist must remain fail-closed.
- Set ADMIN_API_KEY and a high-entropy TENANT_AUTH_PEPPER (32+ characters) in Railway secrets.
- Configure Telegram and/or SMTP only after validating delivery to a controlled test destination. Authenticated SMTP must use STARTTLS.
- Test restart persistence, tenant isolation, quota denial, key revocation, and notification retry in a staging deployment.
- Confirm the runtime version SHA after deployment. Do not infer production activation from a green GitHub workflow.

## Important scope boundaries

- ALLOWED_REPOS is an operator approval boundary, not a complete user identity system.
- Quota values are internal project guardrails, not provider-published free-tier entitlements.
- A catalog price of zero is evidence at inspection time, not a promise that the provider will remain free.
- The current provider router is not yet a fully implemented cross-provider failover engine.
- Telegram/email currently cover quota threshold alerts, not all security events, outages or provider failures.
- No production deployment or Railway environment change is included in this branch.
