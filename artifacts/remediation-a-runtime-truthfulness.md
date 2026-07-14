# Remediation Scenario A — truthful provider runtime

- Status: `PARTIAL`
- Baseline commit: `a7350f4e92c98f403e9df9814b2d3e9cb4a5249b`
- Evidence state: remediation worktree before the focused capability commit
- Environment: Windows host, Conda `anime-pilgrimage-agent`, project Docker Compose

## Product path

```text
Compose environment -> Settings aliases -> ProviderServices/MCP
-> Agent ToolOutcome -> workflow fallback/partial state -> persisted/API response
-> /api/runtime/diagnostics
```

## Executed evidence

| Check | Mode | Status | Evidence |
|---|---|---|---|
| Uppercase `PROVIDER_MODE=live` selects live implementations | fixture contract | PASS | `test_uppercase_live_mode_composes_real_provider_implementations` |
| Safe runtime provider diagnostics | fixture/Anitabi live | PASS | running Compose `/api/runtime/diagnostics` |
| ORS-style 429 reaches workflow fallback | injected rate-limit fixture | PASS | integrated LangGraph degradation test |
| Weather unavailability remains unknown | injected rate-limit fixture | PASS | integrated LangGraph degradation test |
| Geocode failure preserves a usable estimated base | injected rate-limit fixture | PASS | integrated LangGraph degradation test |
| Reusable engine, MCP discovery, LLM client and checkpointer | local Compose | PASS | created a workflow to its interrupt, then restored the same persisted trip through the running API |
| Credentialed Bangumi/ORS/Open-Meteo live product call | live | UNVERIFIED | no new external call was required for this slice |
| SearchAPI live call | live | UNVERIFIED | live smoke budget is disabled/exhausted; no request made |

## Provider mode matrix observed from the running stack

| Provider | Mode | Status | Notes |
|---|---|---|---|
| Bangumi | fixture | available | normalized fixture implementation |
| ORS | fixture | available | workflow fallback separately injected and tested |
| Open-Meteo | fixture | available | unknown-state degradation separately tested |
| SearchAPI | fixture | available | live remains UNVERIFIED |
| Anitabi | live | available | legal read-only API with imported fallback policy |

## Commands

- `make lint`
- `make typecheck`
- `make test`
- focused provider outcome and integrated graph tests
- `docker compose up -d --build` with explicit fixture provider mode and Anitabi mode
- bounded four-service health/database/diagnostics probe
- running API workflow create/restore probe that initialized the lazy checkpoint once

## Limitations

This report does not label credentialed external providers PASS. It proves configuration selection,
actual implementation composition, safe diagnostics, typed failures, explicit fallback behavior and
the rebuilt local product stack. Live provider evidence remains separate and UNVERIFIED where no
bounded call was made.
