# Intelligent Discovery Engine v1

The discovery engine is the central catalog's evidence-aware intake layer for repositories,
agents, models, APIs, tools, datasets, and connectors.

## Flow

1. Build a bounded discovery query for a supported resource kind.
2. A configured search backend retrieves public metadata (the v1 module defines an adapter
   contract; it does not make network requests itself).
3. Normalize each result as a ResourceCandidate.
4. Reject archived projects and unsafe/non-HTTPS URLs.
5. Rank candidates using transparent signals: activity recency, stars, forks, description,
   and supplied license metadata.
6. Keep free pricing **unverified** unless evidence links point to official pricing or
   official free-tier documentation. A GitHub topic, README claim, or model name is not proof.
7. Send candidates to human/admin review and only then permit registration in the extension
   registry with explicit tenant/repository assignment and scopes.

## Safety and limitations

- Never clones, installs, imports, executes, or deploys discovered code.
- Does not grant credentials, secrets, repository permissions, or scopes.
- Does not equate open source with free hosted inference, nor a free tier with unlimited use.
- License identifiers are metadata; legal compatibility requires review.
- The backend is injected so GitHub Search API, curated catalogs, and other approved sources
  can be added independently under the source-connector egress policy.
- v1 ranks and reports evidence gaps; it does not automatically certify trust, pricing,
  security, uptime, or production readiness.
- Persisted registration and downstream synchronization remain separate, opt-in operations.

## Integration contract

Implement SearchBackend.search(DiscoveryQuery) using an approved outbound connector.
Return only bounded ResourceCandidate records. Persist assessments in the central registry
with source URL, retrieval timestamp, source type, evidence URLs, and review status. Keep
credentials in the secret manager; never include secret values in candidate records.
