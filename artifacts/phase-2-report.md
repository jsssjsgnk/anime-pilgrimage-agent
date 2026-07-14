# Phase 2 verification

Generated: 2026-07-14T16:54:36.400407+00:00

## Summary

| Check | Category | Result |
|---|---|---|
| Python lint | static | PASS |
| Python strict types | static | PASS |
| Web lint | static | PASS |
| Web strict types | static | PASS |
| Provider fixture and failure contracts | fixture | PASS |
| Web unit tests | fixture | PASS |
| Repository secret scan | security | PASS |
| Build and start full stack | compose | PASS |
| Four-service health | compose | PASS |
| MCP initialize, allowlist, and schemas | integration | PASS |
| MCP schema snapshot | integration | PASS |
| Subject confirmation and Route A | integration | PASS |
| Live read-only provider smoke | live | PASS |
| Subject confirmation map E2E | e2e | PASS |

## Failure details

None.

## Evidence separation

- Fixture/unit evidence: Python and Web unit/contract checks above.
- Browser E2E evidence: Playwright report and desktop/mobile screenshots under `artifacts/`.
- Live external API evidence: the separately labelled live smoke row; each configured provider is called at most once and SearchAPI at most once.
