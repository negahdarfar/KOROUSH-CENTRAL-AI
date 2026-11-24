# Runtime Schema Contracts v1

A bounded JSON Schema subset validates versioned extension and event payload contracts before future dispatch integration.

Supported types: object, array, string, integer, number, boolean, null. Supported keywords: properties, required, additionalProperties, items, enum, minLength, maxLength, minItems, maxItems, minimum, maximum and description.

Unknown keywords are rejected. Schemas are limited to 16 KiB, 256 nodes and depth 12. Values are recursively checked with bounded nesting.

The compatibility report is conservative. It flags newly required fields, tightened bounds, narrowed enums/types, newly forbidden additional properties and incompatible nested changes. It is a screening result, not proof of full JSON Schema equivalence. Breaking changes require a new major contract version and migration plan.

No third-party validator is dynamically loaded. No schema code or remote reference is executed or fetched. This PR adds a library capability only; existing endpoints are not yet wired to it. Trust, source provenance and pricing remain unverified. No downstream repositories, secrets, deployments or high-impact operations are changed.
