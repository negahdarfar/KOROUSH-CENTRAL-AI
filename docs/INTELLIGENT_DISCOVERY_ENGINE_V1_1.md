# Intelligent Discovery v1.1

## Live discovery

The admin-only endpoint `POST /api/admin/discovery/search` performs a bounded search against the fixed official GitHub Search API endpoint. It accepts a resource kind, 1–8 search terms, a maximum result count of 50, and a recency window. An optional GitHub token is read only from the server environment; it is never returned.

Example request:

```json
{
  "kind": "repository",
  "terms": ["open source agent framework"],
  "limit": 20,
  "require_recent_days": 730
}
```

Use the `X-Admin-Key` header. Results include repository metadata, a transparent score, missing-evidence flags, and `registration: requires_admin_review`.

## Security and evidence

- Only `https://api.github.com/search/repositories` is contacted; caller-supplied URLs are never fetched.
- HTTPS, fixed host, no redirects, bounded timeout, 1 MB response cap, 50-result cap, and bounded search terms.
- Search metadata is untrusted. Stars, recency, description, and license are ranking hints, not security certification.
- A submitted pricing URL is only a lead. This version does not fetch pricing pages or prove publisher ownership; every result remains `free_status=unverified`.
- Open-source license metadata is not a legal compatibility determination.
- No cloning, installation, importing, execution, deployment, tenant assignment, or registry writes occur.
- Registry admission remains a separate admin action after review and explicit tenant/repository scope assignment.

## Next adapters

Add additional providers only through exact-host allowlists, DNS-rebinding protections, no-redirect transport, bounded response bodies, explicit rate limits, source timestamps, and source-specific official-evidence verification.
