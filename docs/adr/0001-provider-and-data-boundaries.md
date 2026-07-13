# ADR 0001: Provider and data boundaries

Status: Accepted

## Context

Travel planning mixes stable identifiers, live estimates, community point data, and user-authored knowledge. Treating them as one model context would erase provenance and allow stale or untrusted text to override structured facts.

## Decision

Use strict provider protocols for Bangumi, imported pilgrimage points, ORS, Open-Meteo, and SearchAPI. Every provider has a real and fixture implementation, bounded timeouts/retries, normalized errors, provenance, and cache policy. Route A accepts only sourced, coordinate-valid, deduplicated points. RAG is limited to unstructured guidance and may not override IDs, coordinates, prices, weather, matrices, or deterministic constraints.

MCP exposes only the nine read-only normalized provider operations. Anitabi scraping, booking/payment, arbitrary URLs, shell/filesystem access, and raw database queries are outside the runtime boundary.

## Consequences

- Live failures degrade to explicit partial/unknown states instead of invented data.
- Tests can be deterministic and quota-bounded while live smokes remain separately visible.
- Adding a provider requires more contract work but keeps external schema drift out of the planner.
