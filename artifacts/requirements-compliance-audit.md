# Requirements compliance and simplification audit

Generated: 2026-07-14 after integrated-Agent remediation

## Outcome

The handoff is tracked as 47 independently verifiable capability groups.

| Classification | Count |
|---|---:|
| Satisfied | 46 |
| Authorized conditional fallback | 0 |
| Partial / externally limited | 1 |
| Unmet | 0 |
| **Total** | **47** |

The one remaining partial item is an upstream data-coverage limitation, not an undisclosed implementation shortcut: for Bangumi subject `328609`, Anitabi `/lite` currently advertises 414 map points (and reports `imagesLength=414`), while the documented `/points/detail` endpoint returns 74 records and documents no pagination parameter. The product exposes all returned sourced details, sets `is_complete=false`, names the limitation, and does not scrape or invent the missing remainder.

## Anitabi decision

The official Open API documentation at `https://navi.anitabi.cn/docs/api/` designates `https://api.anitabi.cn/` as the stable read-only data host and documents attribution terms. Anitabi is the primary pilgrimage-point Provider. Configurable legal JSON/GeoJSON import remains an explicit fallback only.

## Capability matrix

| # | Capability group | Status | Current evidence |
|---:|---|---|---|
| 1 | Conda, uv, Make and four-service Compose foundation | Satisfied | Dedicated environment, locked dependencies, required Make targets and healthy Compose stack. |
| 2 | Secret isolation and no booking/payment/write actions | Satisfied | Server-only secrets, scanners, read-only runtime, and no forbidden MCP actions. |
| 3 | Fixture, browser and live evidence separation | Satisfied | Deterministic fixture/contracts, serialized browser acceptance, and separately labelled read-only smokes. |
| 4 | Bangumi real/fixture Provider and explicit subject confirmation | Satisfied | Provider contracts plus workflow interrupt and Web confirmation. |
| 5 | Anitabi Open API Provider with legal import fallback | Satisfied | `AnitabiProvider`, cache/contracts/normalized errors, MCP wiring, attribution and fallback composition. |
| 6 | Deployable point import and complete-corpus semantics | Partial | Import is configurable and semantics are correct, but the documented Anitabi detail endpoint currently exposes only 74 of 414 advertised total points. |
| 7 | ORS real/fixture Provider, normalized errors and fallback utility | Satisfied | Geocode/directions/matrix contracts and labelled Haversine degradation. |
| 8 | Open-Meteo real/fixture Provider and unknown out-of-range result | Satisfied | Bounded forecast result, cache/contracts, and unknown rather than invented future weather. |
| 9 | SearchAPI flight/calendar real/fixture Provider | Satisfied | Read-only contracts, short TTL, no booking token, and live evidence within the fixed budget. |
| 10 | Manual intercity input boundary | Satisfied | Deterministic user-supplied candidates carry needs-confirmation provenance and perform no external I/O. |
| 11 | Provider cache/error/contract policy | Satisfied | External Providers have real/fixture implementations, timeouts, bounded retries, cache, normalized errors and provenance contracts. |
| 12 | Nine-tool internal read-only MCP allowlist | Satisfied | Exactly nine normalized read-only tools; forbidden tools absent. |
| 13 | Runtime Agent connects through `langchain-mcp-adapters` | Satisfied | Typed `LangChainMcpToolClient` is injected into the production workflow and Compose waits for MCP health. |
| 14 | Open natural-language extraction into editable condition cards | Satisfied | Strict JSON LLM extraction, disclosed deterministic fallback/assumptions, and editable Web fields. |
| 15 | Explicit confirmation of all critical requirements | Satisfied | Requirements, subject, access/base and must/exclude selections cross explicit interrupts. |
| 16 | User-specific Access/Base planning from origin, destination and dates | Satisfied | Durable workflow builds options from confirmed fields and relative dates. |
| 17 | Simultaneous manual/flight choices and comparison labels | Satisfied | Manual choices remain alongside confirmed IATA flight snapshots with recommended/fastest/cheapest/fewest-transfer labels. |
| 18 | Weather affects the itinerary as an explainable constraint | Satisfied | High rain deterministically reduces the walking cap; unavailable forecasts remain unknown and visible. |
| 19 | Route A point validation, provenance and deduplication | Satisfied | Coordinate/source/membership cleaning, deterministic IDs and warnings are contract-tested. |
| 20 | Route A complete/partial semantics in the product | Satisfied | `/lite` versus detail counts drive `is_complete`; badges, warnings and attribution are rendered. |
| 21 | Deterministic Route B subset, buffers, windows, walking and must/exclude validation | Satisfied | Property/contract tests plus explicit 98% planner branch coverage. |
| 22 | Product controls for must-visit/excluded points and constraints | Satisfied | Route A controls update the confirmed requirement schema and reject cross-membership conflicts. |
| 23 | Product Route B uses configured ORS and visible Haversine degradation | Satisfied | MCP matrix call is primary; failure becomes labelled straight-line estimation. |
| 24 | Main Web is driven by the durable Agent workflow | Satisfied | Start/resume/modify endpoints and PostgreSQL checkpoints own the product path. |
| 25 | LangGraph nodes perform specified real work | Satisfied | Requirements, subject, Anitabi, access/flights, weather, RAG, matrix, planning, validation, review and local replan are integrated. |
| 26 | Real LLM Reviewer in the runtime workflow | Satisfied | Configured OpenAI-compatible strict boundary with safe deterministic fallback; malformed envelopes do not crash the workflow. |
| 27 | Reviewer warnings, validation issues and omitted reasons are visible | Satisfied | Structured panels render all three classes. |
| 28 | Route A/Route B map switch and source legend | Satisfied | Responsive OpenFreeMap/OSM map switch, provenance legend, controls, attribution and keyboard markers. |
| 29 | Daily timeline and bounded Google Maps handoff links | Satisfied | Three-day timeline and encoded bounded walking URLs. |
| 30 | Per-item live/cached/estimated/community/confirm states and timestamps | Satisfied | Point and access cards render normalized state and fetched time. |
| 31 | Schema-driven local modification and exact 30% S1 change | Satisfied | Day/percentage parser recomputes only the target day, enforces at most 70% walking and preserves stable days. |
| 32 | Exports, responsive UI, errors, empty and degraded recovery | Satisfied | JSON/GeoJSON/HTML, desktop/mobile E2E, partial data preservation and actionable retry controls. |
| 33 | Five project-owned stores, checkpoint recovery and namespace tests | Satisfied | SQL stores, PostgreSQL saver, restart recovery and isolation checks. |
| 34 | Product-visible long-term preference lifecycle | Satisfied | Explicit-consent save, inspect, delete, apply and per-trip override in API/Web. |
| 35 | Bounded ContextBuilder and three-revision termination | Satisfied | Versioned safe projection, no raw payloads/secrets, and hard loop cap. |
| 36 | Production RAG uses real multilingual E5 | Satisfied | Compose uses lazy real E5 with CPU-only PyTorch; fixture embeddings remain test-only. |
| 37 | Knowledge CRUD/search, namespace, OCR/empty degradation | Satisfied | Required API/persistence/degradation contracts. |
| 38 | Hybrid RAG, conflicts, injection protection and metric thresholds | Satisfied | Exact pgvector + BM25 + RRF, visible conflicts and passing fixed-corpus metrics. |
| 39 | Dynamic RAG integration in Agent/Web, conflict display and upload UX | Satisfied | Trip/subject query, evidence IDs in context, upload, insufficient-evidence and conflict rendering. |
| 40 | Full S1 acceptance scenario | Satisfied | Domestic relative-clock workflow, sourced Route A, Route B subset, constraints and exact local 30% reduction. |
| 41 | Full S2 international/timezone/overnight/transfer/stale-price scenario | Satisfied | Relative-clock contract validates offsets, overnight legs, transfers, deterministic duration/currency, late arrival, return buffer and expired price rejection. |
| 42 | Full S3 partial-provider/error-recovery scenario | Satisfied | Combined Anitabi partial detail, ORS 429 fallback, unknown weather, bounded invalid LLM and visible partial recovery. |
| 43 | Domain Validator branch coverage at least 90% | Satisfied | Focused `planning/planner.py` branch coverage is 97.57%; full suite reports 98% rounded. |
| 44 | Final report honestly lists limitations and unfinished items | Satisfied | README, demo, ADR, known limitations and generated final report disclose Anitabi coverage, bounded modification, model/bootstrap and local-operation limits. |
| 45 | Six phase gates and `make verify-all` | Satisfied | All mandated gates are rerun in final acceptance and write reports under `artifacts/`. |
| 46 | Clean database/volume startup and PostgreSQL recovery | Satisfied | Phase 6 scopes volume removal to this project, migrates cleanly, restarts PostgreSQL and verifies persistence/isolation. |
| 47 | Documentation, license inventory and deliverable privacy scans | Satisfied | Required artifacts, dependency inventories and zero-leakage scans. |

## Bottom line

The product path is now Web → durable LangGraph Agent → typed read-only MCP → normalized Providers → deterministic Route A/Route B/Reviewer/RAG/memory → responsive presentation and exports. The previous 29 implementation/verification deviations have been closed. The only non-full capability is the externally constrained Anitabi detail coverage described above; it is visible in schemas, UI, tests and documentation.
