# Phase 5 verification

Generated: 2026-07-14T17:35:27.295406+00:00

## Summary

| Check | Category | Result |
|---|---|---|
| Python lint | static | PASS |
| Python strict types | static | PASS |
| Web lint | static | PASS |
| Web strict types | static | PASS |
| RAG ingestion, retrieval, conflicts, persistence, and exports | fixture | PASS |
| Golden metrics and versioned export schemas | fixture | PASS |
| All Python regressions with coverage | fixture | PASS |
| Web unit regression | fixture | PASS |
| Repository secret scan | security | PASS |
| Real multilingual E5 dimension and normalization | model | PASS |
| Build and start full stack | compose | PASS |
| Four-service health | compose | PASS |
| RAG migration is current | integration | PASS |
| Exact pgvector and persistent BM25/RRF | integration | PASS |
| Knowledge API isolation, dedupe, metrics, and deletion | integration | PASS |
| Complete revision and export browser flow | e2e | PASS |
| Remove fixed RAG corpus from PostgreSQL | integration | PASS |

## Failure details

None.

## Evidence separation

- Fixture/unit evidence: Python and Web unit/contract checks above.
- Browser E2E evidence: Playwright report and desktop/mobile screenshots under `artifacts/`.
- Live external API evidence: no additional live calls were required for this phase; provider behavior is covered by the prior live gate plus current fixtures.
