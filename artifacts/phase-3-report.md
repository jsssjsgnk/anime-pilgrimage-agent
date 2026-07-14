# Phase 3 verification

Generated: 2026-07-14T17:33:00.772638+00:00

## Summary

| Check | Category | Result |
|---|---|---|
| Python lint | static | PASS |
| Python strict types | static | PASS |
| Web lint | static | PASS |
| Web strict types | static | PASS |
| Route B properties and three-day scenario | fixture | PASS |
| Web unit tests | fixture | PASS |
| Repository secret scan | security | PASS |
| Build and start full stack | compose | PASS |
| Four-service health | compose | PASS |
| Kyoto-to-Tokyo Route B API scenario | integration | PASS |
| Access, map, and timeline E2E | e2e | PASS |

## Failure details

None.

## Evidence separation

- Fixture/unit evidence: Python and Web unit/contract checks above.
- Browser E2E evidence: Playwright report and desktop/mobile screenshots under `artifacts/`.
- Live external API evidence: no additional live calls were required for this phase; provider behavior is covered by the prior live gate plus current fixtures.
