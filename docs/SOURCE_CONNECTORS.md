# Source Connector Policy v1

The central platform defines a bounded, deny-by-default contract for future read-only source connectors.

## Connector catalog

`app/source_connector_catalog.py` advertises protocol contracts for RSS/XML, HTTPS JSON, read-only HTML, market-data APIs, YouTube metadata, and read-only chain RPC. All descriptors are `contract-only`; none performs outbound requests or claims a provider is configured. Secret requirements are descriptive only and no credentials are stored here.

## Fetch policy

`app/source_connector_policy.py` validates:
- HTTPS only, exact hostname allowlists (no wildcard or suffix matching), no URL credentials, no IP-literal host, no nonstandard port, no fragments.
- Connect timeout at most 10 seconds, read timeout at most 15 seconds, response cap at most 1 MB.
- Automatic redirects are prohibited.
- Future transports must implement DNS rebinding protection and reject private, loopback, link-local, multicast, reserved, and otherwise non-public destination addresses after DNS resolution. They must connect to the validated address, not perform a second unconstrained resolution.
- Response content must be treated as untrusted input, parsed with format-specific limits, and passed through the existing evidence contract before agent use.

This PR does not implement HTTP retrieval, DNS resolution, API-key storage, crawling, or source verification. A policy validation result is not proof that a source was fetched or is trustworthy.
