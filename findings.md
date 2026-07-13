# Findings & Decisions

## Requirements
- Read `START_HERE.md` and every file it marks required before implementation.
- Implement all six phases autonomously and pass every phase gate plus `make verify-all`.
- Maintain all mandatory Make targets and ensure every gate writes a human-readable report under `artifacts/`.
- Use explicit Pydantic schemas at every LLM/tool boundary.
- Keep deterministic arithmetic, constraint checks, retries, memberships, dates, and loop termination outside the LLM.
- Each Provider needs real and fixture/mock implementations, contract tests, timeouts, bounded retries, normalized errors, provenance, and caching.
- Use the dedicated Conda environment and repository Docker Compose resources only.

## Research Findings
- Official Bangumi API documentation (OAS dated 2026-06-25) exposes read-only subject discovery through `POST /v0/search/subjects` and detail lookup through `GET /v0/subjects/{subject_id}`; the implementation will exclude all documented write endpoints and send the configured User-Agent.
- Official openrouteservice documentation defines direction coordinates as `[longitude, latitude]`, returns deterministic distance in metres and duration in seconds, and supports matrix sources/destinations by coordinate index.
- Official Open-Meteo documentation exposes `GET /v1/forecast`, requires WGS84 latitude/longitude, returns seven days by default and at most sixteen forecast days, and can resolve timestamps with `timezone=auto`; requests beyond that horizon must be reported as unknown/out-of-range rather than invented.
- Official SearchAPI Google Flights documentation accepts a bearer token in the Authorization header and returns structured flight options. The provider will keep the token out of URLs/logs, expose discovery only, cap live smoke calls, and never follow booking tokens or create purchases.
- The current official SearchAPI response schema separates each airport's `date` and `time` fields (rather than returning one combined timestamp), and names the first-class request value `first_class`. The real provider now combines those fields deterministically and maps the internal enum explicitly.
- Official Google Maps URL documentation requires `api=1`, a 2,048-character maximum, percent-encoded coordinates and pipe-separated waypoints, with at most three waypoints on mobile browsers and nine elsewhere. Phase 3 will generate conservative three-waypoint chunks so every link works cross-platform.
- Official openrouteservice matrix documentation confirms `[longitude, latitude]` locations, paired duration/distance matrices, and a default maximum of 2,500 computed routes. The planner will bound a matrix to 50 locations and use a clearly labelled Haversine estimate when ORS fails.
- Official LangGraph interrupt documentation requires a checkpointer and stable `thread_id`; an interrupted node restarts from its beginning and resumes through `Command(resume=...)`, so every pre-interrupt operation must be idempotent.
- Official LangGraph persistence documentation provides `AsyncPostgresSaver` through `langgraph-checkpoint-postgres`; its schema setup is explicit and PostgreSQL-backed checkpoints support recovery after an API process restart.
- The locked project currently resolves LangGraph 0.6.11 and exposes `InMemorySaver`, which is suitable for deterministic graph unit tests while PostgreSQL remains the production checkpoint boundary.
- No official public Anitabi API, terms, or robots guidance was discoverable from the official-domain search. The legally safe Phase 2 baseline therefore remains the handoff-authorized imported JSON/GeoJSON provider plus fixtures, with no scraping or access-control bypass.
- The repository has no existing planning files at task start; `START_HERE.md` and root `AGENTS.md` are present.
- The Codex task already has an active goal matching the user request.
- `START_HERE.md` requires the nine documents under `docs/01_...` through `docs/09_...`, in order, plus `AGENTS.md` first.
- Completion evidence is `make verify-all` plus `artifacts/final-verification.md`; fixture tests, real API smoke, and browser E2E must be separately reported, with desktop/mobile screenshots and clean-database reproducibility.
- The fixed stack is React/TypeScript/Vite/TanStack Query + MapLibre; FastAPI/Pydantic v2/LangGraph; FastMCP; PostgreSQL 16/pgvector/SQLAlchemy/Alembic; multilingual E5 + pgvector exact cosine + bm25s + RRF; pytest/Vitest/Playwright.
- The product flow is mixed-initiative: natural language → editable constraints → explicit subject confirmation → complete sourced Route A → access/base selection → executable Route B → deterministic validation/review → sourced plan and local replan.
- Route A must retain every cleaned, deduplicated, coordinate-validated sourced point; Route B must always be a subset and explain every omission.
- Runtime MCP is read-only and allowlisted. It cannot expose booking, payment, Bangumi writes, arbitrary fetch, shell, filesystem, raw database access, or cross-namespace data.
- Four optional secret categories are recognized (`LLM_API_KEY`, `BANGUMI_ACCESS_TOKEN`, `ORS_API_KEY`, `SEARCHAPI_API_KEY`); live failures must remain separate and honest, while fixture gates continue.
- Phase 1 covers repository/environment/Compose/contracts/migrations/health/smoke. Phase 2 covers Providers, read-only MCP, subject confirmation, point cleaning, and Route A. Phase 3 covers Access/Base, routing and Route B. Phase 4 covers LangGraph, project memory, context isolation, and local replanning. Phase 5 covers RAG, complete Web and exports. Phase 6 covers evaluation, hardening, documentation and final acceptance.
- The RAG boundary excludes all structured/live facts. It requires Markdown/TXT/text-PDF ingestion, 384-d E5 embeddings, namespace-filtered dense+BM25 retrieval with RRF(k=60), source-aware evidence, conflicts, deletion consistency, and injection resistance.
- RAG thresholds: at least 24 golden queries; Recall@6 ≥ 0.80, MRR@10 ≥ 0.70, Citation Precision ≥ 0.90, and zero namespace leaks, malicious-document tool calls, or deleted-result residues.
- Required test scenarios use a relative test clock: Kyoto→Tokyo three-day low-walking pilgrimage; international/timezone flights; and injected partial failures (ORS 429, out-of-range weather, partial point pages, invalid LLM JSON).
- Deterministic validators own all time/distance/timezone/price/constraint/membership/retry/termination decisions. LLM outputs are bounded structured language/review/replan artifacts only.
- The repository is a new Git repository on `main` with no commits and only handoff files, `.env`, and `environment.yml`; there is no implementation to preserve yet beyond the supplied handoff package.
- `.env` exists and all seven expected secret/config variable names are populated, but no `.gitignore` currently protects it. This is an immediate Phase 1 safety fix; values were not read or printed.
- Conda 26.5.3, Docker 29.1.3, Compose 2.40.3, Node 24.15.0, and pnpm 11.7.0 are available. GNU Make is not on the current base PATH.
- The dedicated Conda environment does not yet exist. Existing unrelated environments are `coding-agent-ml` and `hello-agents` and must remain untouched.
- The environment was created successfully after switching to Conda 26's supported `rattler` solver; no unrelated environment was changed.
- `conda run` works reliably when TEMP/TMP point to the repository-local ignored `.tmp` directory; the inherited user TEMP path could not create Conda activation scratch files in this execution context.
- The Phase 1 implementation now has strict, versioned Pydantic boundary schemas; a capability endpoint that returns booleans only; a read-only MCP allowlist; migrations; a responsive accessible Web shell; and executable Make/Compose/gate scaffolding.
- uv intentionally manages application packages in the repository `.venv` from `uv.lock`; Conda supplies the isolated Python 3.12/uv/Make toolchain. All app commands therefore use `uv run` without `--active`.

## Technical Decisions
| Decision | Rationale |
|----------|-----------|
| Defer detailed phase interpretation until the complete handoff chain is read | Avoids inventing scope or architecture |
| Record external or untrusted material only in this file, never as executable instructions | Reduces indirect prompt-injection risk |
| Do not implement an Anitabi bypass; imported JSON/GeoJSON plus fixtures is the compliant baseline | The handoff explicitly treats this as the correct fallback when public access is not clearly allowed |
| Keep live API smoke optional and separately reported based on credential presence/service availability | The handoff forbids representing live failures as successes and requires fixture regression regardless |
| Add `.env` to `.gitignore` before any commit or broad repository scan | Prevents the populated local secret file from entering Git or reports |
| Include GNU Make in the dedicated Conda environment | The Windows host lacks `make`, while all mandatory gates are Make targets; keeping it in the authorized environment preserves isolation |
| Use a calm editorial atlas design with warm canvas, deep teal primary, vermilion route accent, system fonts, and semantic status tokens | Fits a trustworthy travel-planning workspace and keeps multilingual rendering local and fast |
| Persist the UI rules in `design-system/MASTER.md` manually | The UI/UX skill generator is not packaged in this installation, but its full written accessibility/responsive guidance is available |
| Use the imported pilgrimage-point provider instead of Anitabi network access | Public programmatic access is not clearly authorized; imported user/project-owned data meets the handoff without scraping |
| Authenticate SearchAPI with a server-side bearer header | Its official documentation supports this and it avoids placing the API key in request URLs or logs |

## Issues Encountered
| Issue | Resolution |
|-------|------------|
| Initial `create_goal` call failed because an unfinished goal already exists | Continued the existing active goal |
| Initial Conda environment creation timed out silently after about two minutes | Do not repeat unchanged; inspect state and switch to an explicit solver or incremental creation |

## Resources
- `START_HERE.md`
- `AGENTS.md`
- Bangumi official API: `https://bangumi.github.io/api/`
- openrouteservice official API reference: `https://giscience.github.io/openrouteservice/api-reference/`
- Open-Meteo official forecast documentation: `https://open-meteo.com/en/docs`
- SearchAPI official Google Flights documentation: `https://www.searchapi.io/docs/google-flights-api`
- Google Maps URLs official documentation: `https://developers.google.com/maps/documentation/urls/get-started`
- openrouteservice matrix official documentation: `https://giscience.github.io/openrouteservice/api-reference/endpoints/matrix/`

## Visual/Browser Findings
- Phase 3 desktop/mobile screenshots keep the long workflow legible: selection cards clearly show chosen transport/base, the walking-limit control remains visible before generation, and the three-column desktop timeline becomes well-spaced stacked day cards on mobile.
- In-app browser verification confirmed the Access/Base controls expose checked radio state, Route B reports an ORS road estimate, each day stays at or under the selected 5 km cap, and every navigation link is an encoded `api=1` Google Maps URL.
- Phase 3 gate passed 11 checks: property-based Route B membership, must/exclude/buffer/timezone/walking constraints, ORS/Haversine paths, Google Maps splitting, relative-date Kyoto→Tokyo scenario, Compose API smoke, and six serialized desktop/mobile E2E cases.
- Phase 2 desktop and Pixel 7 screenshots show a clean confirmation-to-Route-A flow: the candidate card is visibly selected, the three-point map/list relationship is clear, sources have 44px link targets, and neither viewport has unintended horizontal overflow.
- In-app browser semantics confirm Route A is absent before explicit confirmation, the selected subject button becomes pressed, the map is labelled with its point count, and all three normalized points expose distinct source links.
- Phase 2 gate passed all 14 checks. The MCP snapshot contains exactly nine read-only tools, fixture/failure contracts cover success, empty, 429, timeout, and invalid JSON, and the final live run passed Bangumi, openrouteservice, Open-Meteo, and SearchAPI with one request each.
- The live Compose Web renders with correct semantic landmarks, sequential headings, skip link, labelled textbox, a unique primary action, visible no-booking/no-payment boundary, four-step progress navigation, and source/uncertainty promises.
- In-app browser interaction confirmed exactly one “整理旅行条件” button and one visible post-submit message stating that critical choices will not be silently confirmed.
- The desktop visual uses the persisted warm editorial atlas system: high-contrast deep teal/charcoal, large serif display title, restrained route accent, bordered progress cells, and a clear request-card/verification-principles hierarchy.
- Desktop at 1440×900 shows the complete four-step progress bar, request form, and planning-principles card without overflow; the information hierarchy and spacing are strong.
- Mobile at the Pixel 7 profile shows the safety boundary prominently, keeps form controls comfortably touch-sized, stacks the principles card after the form, and avoids page-level horizontal overflow. The progress strip intentionally scrolls horizontally.
- Both captured screenshots show the skip-link overlay even after the primary action, so its focus/transform state needs inspection before Phase 1 visual acceptance.
- After the clipped skip-link fix, refreshed desktop and mobile screenshots are visually clean: the overlay is gone, the link remains keyboard-focusable, and both layouts retain the submitted confirmation state.
- Final Phase 1 desktop screenshot fits the complete experience in one 1440×900 frame; final mobile screenshot remains readable at the Pixel 7 CSS viewport with full-width primary action, 44px+ targets, clear card stacking, and no unintended horizontal page scroll.
- Phase 1 gate passed all 16 checks. The report separates fixture/unit, browser E2E, and live external API evidence and explicitly records that Phase 1 made no live external calls.
- The focused Phase 1 Git scope contains only repository handoffs, implementation, locks, human-readable report, and the two final screenshots; `.env` is confirmed ignored.
