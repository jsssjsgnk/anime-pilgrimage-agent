# Progress Log

### 2026-07-15 - Phase 17 arbitrary-title discovery

- User reproduced a real dead end by entering “我想用一天巡礼轻音少女”: title extraction succeeded, but subject resolution returned zero candidates and the workspace offered neither a usable confirmation nor an inline retry.
- Started tracing the configured Bangumi candidate Provider, fixture/live composition, alias normalization, and the confirmation UI. “轻音少女” is the required regression case; the fix must still preserve explicit confirmation and honest no-evidence behavior.
- Root cause confirmed: the full development stack uses the two-record fixture Bangumi provider because catalog selection is coupled to the broad `PROVIDER_MODE=fixture` switch. Anitabi is independently live, but never reached when fixture title matching returns zero candidates.
- Confirmed the user's alias observation and verified the official public Bangumi search path with the exact failing title. Planned implementation: independent `BANGUMI_MODE`, optional Authorization header, anime-only search filtering, plus fixture-preserving tests.
- Scope expanded per user clarification: one title intent may select several catalog entries (for example both TV seasons and the film). Auditing the domain/API confirmation contract now; the implementation will keep the 1–3 natural-intent limit while allowing bounded multi-entry confirmation inside each intent.
- Implemented independent `BANGUMI_MODE`, public token-optional anime search, multi-entry confirmation schemas, multi-season priority/coverage planning, checkbox confirmation UI, select-all versions, and no-result return-to-edit recovery. Focused Python/Web tests, lint, and strict typing are being run incrementally.
- Verified that Anitabi has live point/detail data for all three K-On entries, so the exact user scenario can continue through real scene evidence rather than ending at catalog confirmation.
- Rebuilt the API, MCP, and Web images and confirmed all four Compose services healthy. The real browser path returned the three K-On versions, selected all three, merged 178 scene records into 138 places/30 areas, and displayed 50 markers in the default focused area with working scene detail.
- Focused acceptance is green: 135 Python tests at 80.45% coverage, 8 Web unit tests, lint, strict Python/Web typing, and all 12 desktop/mobile E2E scenarios including the new arbitrary-title multi-season flow.
- Final `make verify-all` passed in 461.9 seconds with the same 135 Python / 8 Web / 12 E2E results plus clean Compose rebuild and recovery, real E5/pgvector checks, all six phase reports, secret/privacy scans, and remediation A–J.

### 2026-07-15 - Phase 16 initial canvas correction

- Started from the user-provided desktop screenshot and identified the oversized, mostly empty center panel plus bottom-edge content leakage.
- Restored the repository plan and re-read the applicable UI/UX and file-planning skills before changing the interface.
- Read the persisted Pilgrimage Atlas design system and traced the issue to the null-workspace branch rendering later-stage controls after a full-height intro.
- Traced the world view to all-candidate bounds crossing distant longitudes; planned correction is dominant-area defaulting plus explicit focus bounds rather than treating the global extent as the useful initial view.
- Implemented mutually exclusive empty/confirmation/map rendering, a structured initial canvas, dominant-area defaulting, and focused camera bounds. The first lint pass found two narrow MapLibre/Hook issues before browser verification; these are being corrected rather than bypassed.
- Rebuilt the Web image and inspected the real local application through the in-app browser at 1440×900 and 375×812. The initial canvas is now self-contained and exposes no future-stage filters.
- Browser inspection found 21 point elements but zero visible markers; the missing MapLibre base stylesheet was the root cause. After importing it, all 21 focused desktop markers are visible, numbered, keyboard-addressable, and clickable; selection opens the matching scene image/evidence detail.
- The default area is now the largest canonical-place cluster instead of `all`, so the initial map opens around the useful Tokyo neighborhood rather than at world scale. The explicit area selector still allows switching clusters.
- Focused quality checks pass: Web lint, strict typecheck, six unit tests, and six desktop/mobile Playwright scenarios covering initial layout, natural multi-work confirmation, visible markers, compact maps, scene detail, and batch selection.
- Final `make verify-all` passed in 449.5 seconds: 132 Python tests at 80.43% coverage, 6 Web unit tests, 10 desktop/mobile E2E tests, clean Compose rebuild/recovery, real E5/pgvector checks, secret/privacy scans, all six historical phase reports, and remediation A–J.

## 2026-07-14 — CPU-only E5 container remediation
- Confirmed the apparent Compose hang was a completed BuildKit job, not an application deadlock: the API image reached 16.9 GB after `uv sync --extra rag` selected CUDA-enabled PyTorch and multiple NVIDIA runtime wheels, then spent several minutes exporting/unpacking layers.
- Added the official uv explicit `pytorch-cpu` index/source mapping to `pyproject.toml`; the lock still needs regeneration through the authorized Conda environment because no repository-local `uv.exe` exists.
- Error: the first lock attempt tried a missing `.venv\\Scripts\\uv.exe`; do not repeat that path. Use `conda run -n anime-pilgrimage-agent uv lock` with the repository-local TEMP/TMP workaround.
- The first successful Conda lock still left transitive `torch` on PyPI because uv source overrides apply to declared project dependencies. Added `torch>=2,<3` explicitly to the `rag` extra so the CPU index binding becomes authoritative on the next lock.
- Regenerated `uv.lock`: the CPU index is now authoritative and all CUDA/NVIDIA/Triton packages were removed. The rebuilt API image completed once in 1m44s and shrank from 16.9 GB to 3.84 GB.
- Recreated the API container from the CPU image. Improved `scripts/wait_compose.py` to print immediate status changes and a flushed heartbeat every 10 seconds, so legitimate startup waits no longer look frozen.
- Post-rebuild regression passed: Ruff, mypy, 70 Python tests, 3 Web tests, and 80.14% aggregate branch coverage. The remaining explicit coverage gap is the planner/Domain Validator module at 83%; added boundary tests for empty input, matrix failures, visit/arrival windows, and validator violations.
- First focused planner run reached 88.35%, short of the 90% module target, and Ruff found import ordering. Corrected the import and added a successful scheduling/maps path to cover the main planner branch before rechecking.
- Second focused planner run passed 8/8 and reached 97.57% branch coverage; Ruff also passed.
- The mandatory in-app Browser skill was read and attempted for live visual QA. Runtime initialization failed with `Cannot redefine property: process`; after a documented fresh-kernel recovery attempt it failed identically, with no browser binding available to read troubleshooting docs. Stopped repeating the plugin failure and switched to the repository's Playwright desktop/mobile acceptance path.
- First integrated Playwright run: foundation passed on desktop/mobile, but all six workflow scenarios timed out after the first action. API logs identified one shared root cause: the configured OpenAI-compatible provider returned valid standard metadata (`role`, `index`, `finish_reason`, `usage`, provider reasoning) that the overly narrow response envelope rejected, causing HTTP 500.
- Updated the explicit Pydantic response envelope to validate required fields while ignoring legitimate provider metadata. Added resilient, disclosed deterministic extraction/reviewer fallbacks so malformed LLM output degrades safely instead of taking down the workflow.
- Focused LLM/graph regressions passed 11/11. Ruff then found only import ordering in the API module; corrected it before rebuilding the container.
- Rebuilt/recreated the API with the LLM fix; health replacement succeeded. The build showed source changes invalidated the entire dependency layer, so split Docker installation into a cached `--no-install-project` dependency layer followed by the small project install layer for subsequent rebuilds.
- Focused desktop Phase 2 advanced past requirements but ended at `subject_not_found`; API returned 200 for both start/resume, so the response-envelope crash is fixed. A PowerShell diagnostic request suffered host encoding corruption and therefore is not valid evidence for the browser's UTF-8 Bangumi query; inspect the retained Playwright response trace instead.
- Error: piping an inline Python diagnostic through `conda run ... python -` opened an interactive prompt because that wrapper did not forward stdin. Do not repeat; use trace parsing or an on-disk tested script.
- Parsed only the retained trace's safe workflow response bodies: UTF-8 was correct, LLM extraction found Kyoto/Tokyo/Bocchi but left start/end null for “September, three days”; explicit confirmation therefore correctly stopped at `requirements_incomplete`. Updated LLM extraction to let deterministic code fill only null explicit/inferable fields, disclose date assumptions, and recompute missing fields while preserving the `llm` source.
- The focused merge test passed, then Ruff rejected ambiguous full-width punctuation in the new test literal. Replaced only those punctuation characters with explicit Unicode escapes before rerunning static checks.
- Second focused desktop Phase 2 reached the real Anitabi Route A successfully: 74 markers, basemap, attribution, provenance and completeness disclosure all passed. Only the final pointer click failed because marker 73 geometrically overlapped marker 1; changed the regression to keyboard focus + Enter, which verifies the existing accessible marker interaction without pretending dense coordinates do not overlap.
- The keyboard regression then exposed that MapLibre's popup binding did not activate from native Enter in this configuration. Added an explicit Enter/Space handler and `aria-haspopup` to every marker, turning the test failure into a real accessibility fix rather than forcing the click in Playwright.
- A later focused run timed out because the configured external LLM consumed nearly the entire 30-second browser budget, although the API ultimately returned 200. Added a Playwright request fixture that supplies explicit relative-date requirements to the real workflow start endpoint. Browser gates now test Compose Agent/MCP/Bangumi/Anitabi/planning/maps deterministically without repeated paid LLM calls; the LLM boundary remains covered independently.
- Full Playwright acceptance then passed 8/8 in 27.5s across desktop and Pixel 7.
- Visual inspection found Route A's 74-point list stretching the desktop grid item so the map shell became page-height with a large blank lower area. Constrained the map to a responsive viewport height, aligned grid items at the top, made the desktop map sticky, and gave the complete point list its own accessible scroll region; mobile retains the map plus a bounded scrollable list.
- Began explicit S2/S3 closure: flight segments now require timezone-aware ordered timestamps; options require continuous transfers, exact stop counts and deterministically recomputed elapsed duration. Real point-tool exceptions now become `fetch_points_partial` with confirmed subject data preserved. Added a product-visible partial recovery panel and corrected the intro so it no longer says Anitabi necessarily returns a complete corpus.
- Added explicit relative-clock contract scenarios: S2 covers cross-offset overnight two-segment flight timing, transfer count, deterministic 930-minute duration, USD price, late-arrival empty first day, return-buffer violation and expired-price rejection; S3 composes partial Anitabi detail, ORS 429 Haversine fallback, out-of-range unknown weather and bounded invalid-LLM failure.
- First focused scenario run: S2 and 19 existing Provider/graph tests passed; S3 fixture used GeoJSON longitude/latitude order instead of Anitabi's documented latitude/longitude tuple and was correctly rejected. Fixed the fixture order. The new Web partial-recovery test passed (4/4 Web unit tests).
- Second scenario run passed 21/21; Ruff and strict mypy passed. Web typecheck passed, while ESLint found an unnecessary async mock and unsafe generic string conversion in the new recovery test. Replaced it with typed URL extraction and explicit resolved responses.
- Full regression now passes 76 Python tests, 4 Web tests, 81.00% aggregate coverage, and 98% planner coverage.
- The first combined API/Web rebuild hit Docker Desktop's known Bake gRPC non-printable shared-key header bug before any build step. Reuse the established repository workaround `COMPOSE_BAKE=false`; no code or image layer failed.
- Rebuilt with the established workaround: dependency cache was fully reused, API project installation took 3.3s, API layer export/unpack took under 1s, and API+Web build/recreate completed in 23.9s.
- Updated README, demo, Provider ADR, known limitations and final-report generator to describe the integrated Anitabi/Agent behavior instead of the obsolete three-point/import demo. Re-audited all 47 groups: 46 satisfied, one externally limited by Anitabi's documented 74-detail/414-total mismatch, zero unmet.

## Session: 2026-07-14

### Phase 9: Integrated Agent and Provider foundation
- **Status:** in progress
- User explicitly requested implementation of the audited shortcomings, emphasizing that the Agent functionality had not been implemented.
- User clarified that Anitabi is a required product dependency; it will be implemented as a first-class read-only Provider rather than leaving import-only as the final state.
- Found the official Anitabi Open API documentation and confirmed subject `328609` reports 414 API points versus the repository's three imported records.
- Remediation is organized around one integrated runtime path before UI polish or additional acceptance claims.
- No further SearchAPI live call is permitted because the prior documented budget has been exhausted; existing real-provider evidence plus new fixture/contract integration will be used.
- Implemented the real documented Anitabi Provider, full-count validation, source attribution, bounded cache, normalized failures, typed fallback and a separate point-source mode.
- Added `langchain-mcp-adapters==0.3.0`, a strict nine-tool Agent client, structured result normalization, fixture client, and passing focused tests/types/lint.
- Focused evidence: 15 Anitabi/provider tests and 2 MCP-client tests pass; focused Ruff and mypy pass.

### Phase 8: Requirements and simplification audit
- **Status:** complete
- User challenged whether Anitabi API access was required and requested a complete count of unmet or unilaterally simplified requirements.
- Acknowledged that live mode currently hard-codes the same three-record import and that prior “complete” language overstated the conditional fallback.
- Audit scope is the full original handoff chain, not only test-gate pass/fail. No implementation changes or paid/live provider calls are authorized by this review.
- Re-read all required handoff documents and audited code, dependencies, API/Web wiring, tests, coverage, reports, and current public Anitabi access evidence.
- Corrected the audit after finding the official Anitabi Open API: 18 satisfied, 0 final-state fallbacks, 14 partial/simplified, and 15 unmet.
- Published `artifacts/requirements-compliance-audit.md`; the corrected 29 deviations comprise 24 implementation/product gaps plus 5 verification/reporting gaps.

### Phase 7: User-reported Route A map correction
- **Status:** complete
- User reported that the Route A map looked incomplete and asked why only three points appeared.
- Inspected the supplied screenshot and reproduced the implementation cause in `apps/web/src/App.tsx`.
- Confirmed the map has no basemap source and all interaction is disabled, contrary to the original MapLibre + OpenStreetMap/OpenFreeMap requirement.
- Confirmed both provider modes currently use the same three-record legal GeoJSON import; no point is being hidden by the UI.
- Selected the existing calm editorial atlas design system and the UI/UX accessibility/touch/responsive rules for the correction.
- Replaced the background-only MapLibre style with the current official OpenFreeMap Liberty style and visible OpenFreeMap/OpenStreetMap attribution.
- Enabled cooperative drag/zoom, localized navigation/fullscreen controls, 44px numbered point markers, safe text-only popups, loading/failure feedback, and list-based fallback.
- Changed ambiguous “complete candidate set/import complete” copy to disclose that the current legal import contains three records and is not the complete real-world scene set.
- Added unit coverage for basemap configuration and Phase 2 browser assertions for the real style request, loaded map canvas, controls, markers, attribution, and dataset-scope copy.
- First focused check: TypeScript passed and all three Web unit tests passed; ESLint found one Fast Refresh module-boundary warning and one unsafe asymmetric matcher, which are being corrected in a dedicated typed config module.
- Moved the basemap constants/options into `route-map-config.ts`, replaced the unsafe matcher with exact typed assertions, and passed focused Web lint, TypeScript, and all three unit tests.
- Rebuilt the production Web container; all four Compose services are healthy. The focused Phase 2 Playwright run passed both desktop and mobile cases and regenerated their screenshots.
- The optional in-app Browser runtime could not initialize because its local bootstrap twice raised `Cannot redefine property: process`, including after a clean kernel reset. Per the browser skill recovery rules, stopped repeating it and continued visual QA from the fresh Playwright artifacts.
- Visual review of the fresh desktop/mobile screenshots confirmed the real street basemap, numbered markers, and controls, and caught duplicate attribution from combining custom credit with the style's built-in credit. Removed only the duplicate custom text; the official expanded attribution remains.
- Passed repository-wide `make lint`, `make typecheck`, and `make test` (57 Python tests, 3 Web tests, 80.13% Python coverage), then passed all eight desktop/mobile E2E cases after the normal fixed-corpus seed and removed that corpus again.
- Added README/known-limitations disclosure and `artifacts/map-correction-report.md`; final Compose health is four of four healthy services.

### Phase 0: Required handoff discovery
- **Status:** complete
- **Started:** 2026-07-14
- Actions taken:
  - Confirmed the existing active task goal.
  - Read the complete `planning-with-files` skill and its three templates.
  - Confirmed the repository contains `START_HERE.md` and no prior planning files.
  - Created persistent planning, findings, and progress files.
  - Read `START_HERE.md`, `AGENTS.md`, and all nine required handoff documents in the mandated order.
  - Captured the fixed architecture, security boundaries, six phase gates, RAG thresholds, and acceptance scenarios.
  - Inventoried the new, unimplemented Git repository and local toolchain.
  - Confirmed all expected local configuration names are populated using boolean-only checks; no values were emitted.
  - Identified that `.env` is not yet ignored and GNU Make is absent from the base PATH.
  - Added `.gitignore` protection for local secrets and a value-free `.env.example`.
- Files created/modified:
  - `task_plan.md` (created)
  - `findings.md` (created)
  - `progress.md` (created)
  - `.gitignore` (created)
  - `.env.example` (created)

### Phase 1: Project foundation
- **Status:** complete
- Actions taken:
  - Began creation of the dedicated Conda environment.
  - Created `anime-pilgrimage-agent` with Python 3.12, pip, and uv via the supported `rattler` solver.
  - Added GNU Make to `environment.yml` so mandatory targets run from the isolated environment on Windows.
  - Verified the environment name, Python 3.12.13, uv 0.11.14, and GNU Make 4.4.1.
  - Added the strict Python project, core Pydantic schemas, Provider protocol/error taxonomy, FastAPI health/capabilities, initial SQLAlchemy model, and Alembic migration.
  - Added the read-only FastMCP server with a single Phase 1 status tool.
  - Added the React/Vite/TanStack Query shell, responsive design system, unit tests, and desktop/mobile Playwright scaffold.
  - Added four-service Docker Compose, non-root pinned Dockerfiles, Make targets, secret scanning, environment verification, local dev orchestration, and report-producing phase gate scripts.
  - Generated `uv.lock` and `pnpm-lock.yaml`; installed locked Python and Web dependencies with only esbuild's required build script approved.
  - Built and started the full Compose stack; verified four healthy services, database-backed API health, idempotent migration reruns, and MCP initialize/tools-list.
  - Passed desktop and mobile Chromium E2E, then independently confirmed the submit interaction and visible safety boundary in the in-app browser.
  - Passed `make verify-phase-1` with all 16 checks green and produced `artifacts/phase-1-report.md` plus final desktop/mobile screenshots.
  - Committed Phase 1 as `55cd342` (`phase 1: establish verified project foundation`).
- Files created/modified:
  - `.gitignore`
  - `.env.example`
  - `pyproject.toml`, `Makefile`, `compose.yaml`, `Dockerfile.api`, `Dockerfile.mcp`
  - `src/pilgrimage_agent/**`, `alembic/**`, `tests/**`, `scripts/**`
  - `package.json`, `pnpm-workspace.yaml`, `apps/web/**`
  - `design-system/MASTER.md`, `README.md`

### Phase 2: Providers, MCP, subject confirmation, and Route A
- **Status:** complete
- Actions taken:
  - Implemented strict normalized schemas and real/fixture providers for Bangumi, imported JSON/GeoJSON pilgrimage points, openrouteservice geocoding/directions/matrix, Open-Meteo, and SearchAPI Flights/Calendar.
  - Added credential-safe HTTP transport, bounded retries, normalized errors, deterministic request fingerprints, bounded TTL cache, provenance, and compliant Anitabi fallback documentation.
  - Replaced the Phase 1 MCP status tool with the exact nine-tool read-only allowlist and saved a validated schema snapshot.
  - Added explicit subject search/confirmation APIs and deterministic Route A cleaning/deduplication with source and coordinate invariants.
  - Added the Bangumi candidate, confirmation, local MapLibre Route A layer, source list, desktop/mobile E2E, and browser semantic verification.
  - Passed the final live read-only smoke for Bangumi, openrouteservice, Open-Meteo, and SearchAPI. SearchAPI consumed two total diagnostic/acceptance calls, below the Phase 2 cap of three.
  - Passed `make verify-phase-2` across 14 checks, 27 Python tests at 83.8% coverage, two Web unit tests, four browser E2E cases, full Compose health, secret scan, and schema snapshot.
- Evidence:
  - `artifacts/phase-2-report.md`
  - `artifacts/mcp-tools-schema.json`
  - `artifacts/screenshots/phase-2-desktop.png`
  - `artifacts/screenshots/phase-2-mobile.png`

### Phase 3: Access/Base planning and deterministic Route B
- **Status:** complete
- Actions taken:
  - Added strict access, base, visit-window, daily plan, omission, Route B, and validation schemas with timezone-aware constraints.
  - Added manual intercity real/fixture boundaries, validated flight-to-access normalization, deterministic access comparison, base selection, stable geographic clustering, and daily schedule packing.
  - Implemented arrival/departure buffers, visit windows, max walking, required/excluded handling, return-to-base accounting, structured omission reasons, and a validator report.
  - Added ORS matrix integration with clearly labelled Haversine fallback and conservative cross-platform Google Maps URL splitting at three waypoints/2,048 characters.
  - Added a relative-clock Kyoto→Tokyo three-day scenario plus transport/base selection and timeline UI with on-page source/estimate warnings.
  - Passed `make verify-phase-3`: 11 checks, seven focused property/scenario/API tests, all 35 aggregate Python tests at 83.2% coverage, and six serialized browser cases.
- Evidence:
  - `artifacts/phase-3-report.md`
  - `artifacts/screenshots/phase-3-desktop.png`
  - `artifacts/screenshots/phase-3-mobile.png`

### Phase 4: LangGraph, project memory, context, and replanning
- **Status:** complete
- Actions taken:
  - Added one LangGraph workflow spanning requirements, subject resolution, Route A, Access/Base, retrieval, planning, deterministic validation, review, bounded replan, and presentation.
  - Added three native interrupt/resume confirmations backed by PostgreSQL checkpoints and stable namespaced thread identifiers.
  - Added five project stores for trip state, trip events, explicit opt-in preferences, knowledge metadata, and normalized tool cache.
  - Added minimal versioned ContextBuilder snapshots, content-free run metrics, and bounded strict Reviewer JSON validation.
  - Proved rejection, provider failure, invalid model JSON, namespace isolation, preference deletion, day-2-only replanning, and the three-revision limit.
  - Restarted the API after an interrupt and resumed the same PostgreSQL checkpoint successfully.
  - Passed one real structured-output LLM smoke without logging configuration or response content.
  - Passed `make verify-phase-4` across 13 static, fixture, security, Compose, persistence, live, and browser checks.
- Evidence:
  - `artifacts/phase-4-report.md`

## Test Results
| Test | Input | Expected | Actual | Status |
|------|-------|----------|--------|--------|
| Planning bootstrap | Check root planning files | Three planning files exist | Created all three | pass |

## Error Log
| Timestamp | Error | Attempt | Resolution |
|-----------|-------|---------|------------|
| 2026-07-14 | Goal creation rejected due to existing unfinished goal | 1 | Retrieved and continued existing goal |
| 2026-07-14 | Initial `START_HERE.md` output was mojibake under legacy PowerShell decoding | 1 | Switched all handoff reads to explicit UTF-8 decoding |
| 2026-07-14 | `conda env create -f environment.yml` timed out after 124 seconds with no diagnostic output | 1 | Inspecting whether the environment was partially created before selecting an alternative |
| 2026-07-14 | `--solver libmamba` is invalid in installed Conda 26.5.3 | 2 | Switched to the supported `rattler` solver |
| 2026-07-14 | Conda 26 `env update` rejected `-y` | 1 | Removed the unsupported flag for the next attempt |
| 2026-07-14 | Environment update succeeded but all `conda run` checks failed to create a temp activation file | 1 | Testing a repository-local writable TEMP/TMP path |
| 2026-07-14 | A multi-file planning patch had an invalid context transition | 1 | Corrected it with explicit `Update File` sections |
| 2026-07-14 | Environment tools ran from local TEMP, but truncating Make output produced a broken pipe before the final assertion | 1 | Retain full short version output and run the assertion separately |
| 2026-07-14 | UI/UX design-system command used the documented script path, but that path is absent in this installation | 1 | Searching the installed skill directory for its actual script location |
| 2026-07-14 | The UI/UX skill's `scripts` file pointed to an absent package location | 2 | Created a project design system manually from the skill's documented rules |
| 2026-07-14 | A fallback script search was too broad for the repository information boundary | 1 | Discarded it and restricted subsequent discovery to allowed roots |
| 2026-07-14 | pnpm installed packages but failed its security gate because esbuild was not approved to run its platform-binary setup | 1 | Explicitly allowlisted only esbuild in the workspace configuration |
| 2026-07-14 | The legacy `onlyBuiltDependencies` key did not clear pnpm 11's ignored-build state | 2 | Inspecting the installed pnpm CLI's current approval mechanism before the third attempt |
| 2026-07-14 | Local pnpm help confirmed `allowBuilds` is the current project format | 3 | Approved only esbuild and will rebuild that package |
| 2026-07-14 | A pnpm-generated placeholder duplicated the new `allowBuilds` YAML key | 1 | Removed the placeholder, keeping `esbuild: true` only |
| 2026-07-14 | `uv.lock` was created, but Python packages were not synced because the parallel pnpm failure interrupted the enclosing operation | 1 | Running the Python sync as an independent operation |
| 2026-07-14 | Initial lint/typecheck reported 26 Ruff findings and one mypy error | 1 | Fixed imports and formatting, documented controlled subprocess/bind exceptions, modernized the Protocol generic, and adjusted the runtime-only extra-field test |
| 2026-07-14 | Conda's output wrapper hit a GBK encoding error while relaying lint output | 1 | Set `PYTHONUTF8=1` and `PYTHONIOENCODING=utf-8` for later non-interactive Conda commands |
| 2026-07-14 | Web typecheck found the Vite config's Vitest field was typed through the wrong helper | 1 | Switched to `defineConfig` from `vitest/config` |
| 2026-07-14 | Web lint found one project-scope omission and one unsafe matcher | 1 | Included E2E in tsconfig and replaced the matcher with an exact typed fixture assertion |
| 2026-07-14 | Python tests passed at 80.72% coverage; Web tests mixed Playwright into Vitest and retained the first DOM | 1 | Added a Vitest include boundary and explicit post-test DOM cleanup |
| 2026-07-14 | Environment and Compose schema passed; secret scan false-positive matched across lines in the required API handoff | 1 | Tightened the regex to horizontal whitespace only |
| 2026-07-14 | First full Compose build pulled PostgreSQL/pgvector, then Docker Bake failed before app image build on an internal gRPC session-header error | 1 | Retrying with `COMPOSE_BAKE=false` to bypass the failing Bake path |
| 2026-07-14 | API and MCP images built, but Web context contained pnpm symlinks and Docker rejected an invalid file request | 2 | Added `.dockerignore` and configured the gate to use the working internal Compose builder in this Unicode path |
| 2026-07-14 | All images built and Postgres/MCP became healthy; API migration connected to localhost because `DATABASE_URL` lacked an explicit alias | 1 | Added the uppercase environment alias to `Settings` |
| 2026-07-14 | Rebuilt API became healthy and all four services reported healthy, but the combined manual smoke omitted the Conda TEMP override | 1 | Re-running smoke commands with the established local TEMP/TMP and preserved exit codes |
| 2026-07-14 | Desktop Playwright E2E passed and saved its screenshot; mobile inherited an uninstalled WebKit engine from the iPhone profile | 1 | Switched the mobile Chromium project to the Pixel 7 descriptor |
| 2026-07-14 | Mobile Chromium then found the safety boundary hidden by a desktop-only CSS rule | 1 | Promoted it to a visible mobile header row with a desktop inline override |
| 2026-07-14 | Screenshot review found the translated skip link appearing as a teal overlay in full-page captures | 1 | Replaced transform hiding with an accessible clipped one-pixel pattern and focus-visible reveal |
| 2026-07-14 | First full gate passed environment/Python checks but Windows could not launch the bare `pnpm` shim; the exception also bypassed report creation | 1 | Added explicit executable resolution and launch-error capture to the gate runner |
| 2026-07-14 | Second gate produced its report and reached tests; one engine test inherited a local database driver instead of its intended asyncpg fixture | 1 | Isolated the test with an explicit value-safe Settings fixture and documented `DATABASE_URL` in `.env.example` |
| 2026-07-14 | First Phase 2 static pass found eight Ruff, five mypy, and one ESLint issue | 1 | Corrected formatting, PEP 695 generics, explicit real/fixture union attributes, and the promise-returning click handler |
| 2026-07-14 | Focused Phase 2 tests passed 9/9, but Ruff found six narrow issues and the secret scanner flagged dynamic/fixture assignments | 1 | Applied formatting and adjusted the scanner to retain literal-secret detection without flagging runtime configuration expressions or fixture sentinels |
| 2026-07-14 | All 23 Python tests passed but aggregate coverage fell to 72%; Vitest could not import MapLibre because jsdom lacks `URL.createObjectURL` | 1 | Added fixture/API/cache tests, excluded smoke entrypoints from coverage, and installed the minimal jsdom worker-URL stub |
| 2026-07-14 | Initial `make verify-phase-2` wrapper was mistakenly given a one-second process timeout | 1 | Relaunching with the gate's required build/E2E time budget |
| 2026-07-14 | Phase 2 passed static, fixtures, security, Compose, MCP schema, and Route A checks; live script import failed before network activity | 1 | Changed the gate's live launcher to the locked project environment |
| 2026-07-14 | Bangumi, ORS, and Open-Meteo live smokes passed; SearchAPI's first call exposed split airport date/time fields | 1 | Matched the current official schema and added a regression contract; one of the three allowed SearchAPI calls has been consumed |
| 2026-07-14 | Initial Phase 3 property/scenario run found Windows had no IANA timezone database; Ruff found ten narrow typing/format issues | 1 | Added locked `tzdata`, made the matrix boundary a Protocol, and corrected formatting/imports |
| 2026-07-14 | Relative-clock scenario correctly omitted the farthest fixture point at a 3 km cap because the coarse fixture matrix estimated a 4.5 km round trip | 1 | Raised only the acceptance scenario to a still-low 5 km cap; hard walking-limit behavior remains independently tested |
| 2026-07-14 | First Phase 3 gate stopped immediately on one long report string | 1 | Wrapped the string before any build or browser check ran |
| 2026-07-14 | Phase 3 Compose/API passed and the UI generated Route B; Playwright's base-text assertion was ambiguous across selection and summary cards | 1 | Scoped all final assertions to the labelled timeline region |
| 2026-07-14 | Parallel Playwright rerun passed behavior but two mobile workers intermittently could not open distinct screenshot paths | 1 | Set one Playwright worker so artifact writes are deterministic on this Windows Documents volume |
| 2026-07-14 | Initial Phase 4 graph compilation treated `__interrupt__` as an application channel, which LangGraph reserves internally | 1 | Removing it from WorkflowState and reading returned interrupt metadata through a narrow typed projection |
| 2026-07-14 | Phase 4 gate launch was accidentally bounded to one second and timed out before producing check output | 1 | Re-running the unchanged gate with a full acceptance time budget |
| 2026-07-14 | The first multilingual E5 smoke hit its five-minute budget while downloading the initial model snapshot | 1 | Re-running the resumable official model load with a larger one-time timeout and retaining the fixture gate separately |
| 2026-07-14 | The resumed official multilingual E5 snapshot still did not finish within ten minutes | 2 | Marked the real-model smoke unpassed and continued pgvector/BM25/API/Web work that is independently verifiable |

| 2026-07-14 | Phase 9 progress patch targeted a heading that did not exist in the older progress layout | 1 | Inserted the remediation section using stable section anchors instead |
| 2026-07-14 | Combined audit/Web discovery returned non-zero because the assumed `web/` directory does not exist | 1 | Retained the audit output and switched Web discovery to the repository's actual `apps/web/` path |
| 2026-07-14 | First strict check of the LLM/extraction boundary found Ruff punctuation/line issues and one narrowed Literal inference | 1 | Escaped full-width regex delimiters, adjusted prose punctuation/wrapping, and explicitly widened the requirement-source type |
| 2026-07-14 | Ruff also treats full-width semicolons in Chinese user-facing strings as ambiguous | 2 | Rephrased the assumptions as short full-stop-separated sentences without changing their meaning |
| 2026-07-14 | The new Chinese extraction regression used full-width punctuation that Ruff intentionally flags as lookalikes | 1 | Kept the Chinese-language coverage while using ASCII punctuation in the fixture text |
| 2026-07-14 | The first flight-helper patch inserted the new function before the remainder of `build_planning_options`, leaving that remainder unreachable | 1 | Moved the helper after the completed manual/base builder before running any tests |
| 2026-07-14 | Focused flight integration checks found one import order, one long warning, and a missing type-narrowing assertion | 1 | Ordered the helper imports, wrapped the warning, and asserted the already-required origin before conversion |
| 2026-07-14 | Local-modification regression passed behavior but Ruff flagged a full-width comma in its Chinese fixture | 1 | Kept the Chinese instruction and switched only that delimiter to ASCII |
| 2026-07-14 | Initial graph-local-replan patch used stale import context after Ruff reordered the file | 1 | Reapplied against the current imports and replaced the hash-only replan with a real Day-N walking replan |
| 2026-07-14 | A PowerShell `rg` command parsed `|@app` inside a double-quoted regex as a pipeline expression | 1 | Used a plain UTF-8 file slice for endpoint placement verification and avoided shell-sensitive regex composition |
| 2026-07-14 | First Web style patch assumed a nonexistent 700px media-query anchor | 1 | Appended the new requirements/map/legend/accessibility styles before the stable reduced-motion block |
| 2026-07-14 | Direct `make` was unavailable in the host PowerShell; the first aggregate remediation run then found four test-only mypy narrowings, one updated capability expectation, and aggregate coverage at 78.19% | 1 | Returned to the authorized Conda Make path, validated typed models in tests, added Anitabi to the expected capability set, and started targeted boundary coverage additions |
| 2026-07-14 | A narrow direct mypy invocation treated the editable package as untyped and also exposed an inferred heterogeneous mock-response dictionary | 1 | Kept aggregate project mypy as the authoritative invocation and explicitly typed the mock JSON content as `dict[str, object]` |
| 2026-07-14 | Real Anitabi integration returned 74 detail records while `/lite` advertised 414 total map points | 1 | Verified the documented endpoint has no pagination and that default/`haveImage=false`/`haveImage=true` all return 74; modelled `imagesLength` separately and now discloses the documented detail subset as partial |

### Phase 5: RAG, complete Web flow, and exports
- **Status:** complete
- Actions taken:
  - Added Markdown/TXT/PDF ingestion, `needs_ocr`, multilingual normalization and chunking, strict document/chunk/query/evidence/conflict schemas, and dedupe.
  - Added real `intfloat/multilingual-e5-small` with required prefixes, documented mean pooling, normalized 384-d embeddings, and an offline model smoke.
  - Added pgvector exact cosine retrieval, persistent bm25s indexes, RRF(k=60), authority/freshness handling, namespace filters, deletion consistency, citations, and injection isolation.
  - Curated nine short project-authored fixture documents and 24 golden queries with manifest hashes and source metadata; no whole external pages were copied.
  - Added complete Web revision/evidence/export flow, strict JSON/GeoJSON boundaries and schemas, standalone HTML validation, and stable local Day 2 replanning.
  - Passed `make verify-phase-5` across 17 checks, 57 aggregate Python tests at 80.13% coverage, two Web unit tests, and eight serialized desktop/mobile E2E cases.
- Evidence:
  - `artifacts/phase-5-report.md`
  - `artifacts/rag-evaluation.json` (Recall@6 0.929, MRR@10 0.952, Citation Precision 0.952; failed IDs retained)
  - `artifacts/plan-export-schema.json`, `artifacts/geojson-export-schema.json`
  - `artifacts/screenshots/phase-5-desktop.png`, `artifacts/screenshots/phase-5-mobile.png`

### Phase 6: Evaluation, hardening, documentation, and final acceptance
- **Status:** complete
- Actions taken:
  - Rewrote the operator README and added accepted ADRs, reproducible demo instructions, known limitations, and resume/interview notes.
  - Added locked Python/Node license inventory, production-bundle secret/conversation scanning, MCP forbidden-tool metrics, and final system metrics.
  - Added explicit timeout/429/partial/invalid-model regression replay and a scoped PostgreSQL restart smoke that proves persistence and namespace isolation.
  - Added clean acceptance that removes only project volumes, rebuilds all four services, migrates an empty database, seeds RAG, runs the complete API/browser demo, and cleans fixtures.
  - Passed `make verify-phase-6` across 23 checks, then passed `make verify-all` across all six phase gates.
  - Used the third and final budgeted SearchAPI acceptance call during `verify-all`; no further live provider rerun is permitted without a new budget.
- Evidence:
  - `artifacts/phase-6-report.md`
  - `artifacts/final-verification.md` (Status: PASS)
  - `artifacts/system-metrics.json`, `artifacts/security-metrics.json`, `artifacts/dependency-licenses.json`

### Phase 9: Requirements-compliance remediation
- **Status:** complete
- Actions taken:
  - Added an official Anitabi provider and made it the production Route A source, with the legal import path retained only as a marked incomplete fallback.
  - Added a typed LangChain MCP adapter and replaced the placeholder workflow with an integrated confirmation, subject, Route A, matrix, weather, validation, and bounded-review graph.
  - Replaced the legacy placeholder graph tests with async integration tests covering the three confirmation boundaries, typed Route A/Route B output, fail-closed point fetches, local replan isolation, and the three-revision cap.
  - Added real/configured and deterministic-fallback natural-language extraction boundaries, a configured real structured Reviewer, flight/manual comparison with deterministic labels, dynamic project RAG retrieval, real-E5 Compose mode, weather-driven walking reduction, and labelled Haversine matrix degradation.
  - Passed 13 focused Agent/LLM tests after these integrations; focused Ruff and mypy checks are clean.

### Phase 12: Integrated final acceptance
- **Status:** complete
- Actions taken:
  - Forced the live smoke to exercise Anitabi regardless of local fallback defaults; the current official response produced 74 sourced details and an explicit 414-count partial-data warning.
  - Classified retryable optional-provider outages as visible degraded evidence while keeping authentication and validation failures gate-blocking; SearchAPI remained disabled with zero new requests.
  - Corrected checkpoint recovery fixtures to provide relative dates and every required explicit choice.
  - Added a non-root writable, project-scoped Hugging Face cache volume and a bounded first-use E5 wait for clean Compose acceptance.
  - Removed Playwright response and Windows screenshot-file races using response-bound waits and per-run evidence paths.
  - Passed the final `make verify-all` invocation across Phase 1 through Phase 6 after a clean project-volume rebuild.
- Evidence:
  - `artifacts/final-verification.md` (Status: PASS)
  - `artifacts/phase-1-report.md` through `artifacts/phase-6-report.md`
  - `artifacts/requirements-compliance-audit.md`

### Phase 13: Continuous conversational Agent
- **Status:** complete
- Session start:
  - User identified that the shipped Agent behaves primarily as a workflow wizard and lacks durable multi-turn conversation.
  - Restored planning context with the planning-with-files skill and confirmed the previous integrated implementation remains an uncommitted working-tree baseline.
  - Scope is trip-scoped message persistence, context recovery, intent-aware conversation, safe changes, and a Web chat surface while preserving deterministic confirmation/tool boundaries.
  - Confirmed the existing trip-event store is sufficient for durable messages; no conversation-specific migration is required.
  - Identified the integration boundary: graph snapshots intentionally omit raw chat, while the API currently exposes no message resource. The new bounded conversation layer will sit alongside the graph state.
  - Established the mutation boundary: natural-language requests become typed actions executed by deterministic code; unsupported or confirmation-sensitive requests become explicit proposals, never silent changes.
  - Chosen implementation: a separate typed `ConversationAgent` consumes the current normalized workflow plus a bounded recent transcript. It handles grounded status/explanation questions and emits a typed modification proposal; the API alone executes the existing bounded local replan.
  - Browser recovery will persist only the opaque trip identifier in session storage, then reload namespace-checked workflow/message resources from the API.
  - Added strict conversation intent/action/message/request/response schemas, event timestamps, normalized workflow context, deterministic grounded responses, structured LLM synthesis, and conservative fallback behavior.
  - Wired workflow creation to seed the durable transcript, added namespace-checked GET/POST message endpoints, and routed typed chat modifications through the existing deterministic single-day replanner.
  - Focused conversation and memory tests pass (5/5), covering clarification, typed changes, persisted ordering/timestamps, reload reads, and thread isolation.
  - Added Web session recovery for the opaque trip ID, workflow/message rehydration, a responsive persistent conversation log, grounded prompt shortcuts, and typed plan-change/confirmation badges.
  - Existing Web lint and Vitest tests pass after integration; a dedicated send/reload recovery test remains next.
  - Added and passed the Web send/reload recovery test (5/5 Web tests total) plus the production Web build.
  - Passed repository `make lint`, `make typecheck`, and `make test`: 78 Python tests and 5 Web tests are green; aggregate Python coverage remains above the 80% gate.
  - Rebuilt all four Compose services successfully; every service is healthy and existing project volumes were preserved.
  - First desktop conversational E2E reached an HTTP 200 response but exposed avoidable LLM latency for a deterministic modification. Updated the responder to short-circuit recognized bounded intents and made the browser test await the POST response explicitly.
  - Rebuilt the API, passed Compose health, and passed the desktop real-stack conversational replan/reload acceptance in 5.0 seconds.
  - Passed the focused desktop and mobile conversational replan/reload acceptance (2/2).
  - Passed final `make verify-all` in 554.9 seconds: all six phase reports are PASS, 79 Python tests and 5 Web unit tests pass, the clean four-service rebuild is healthy, and the serialized full browser suite passes 10/10 including continuous conversation on both viewports.
  - Updated operator/demo/limitation documentation to describe persistence, bounded context, safe mutation scope, and browser recovery.
  - Post-documentation checks passed: full Python/Web lint, full Python/Web typechecks, the six-file documentation contract, and a 1,292-file secret scan.
  - Optional in-app Browser setup remained unavailable due the known runtime initialization fault; no user browser state was inspected. The passing serialized desktop/mobile Playwright acceptance remains the visual/interactive evidence.

### Phase 14: Authoritative remediation audit and implementation
- **Status:** complete
- Session start:
  - User supplied `anime-agent-remediation-handoff-files.zip` and designated five documents as the next-round authoritative requirements.
  - Restored the file-based planning context and confirmed the current branch is clean and synchronized before remediation work begins.
  - Inspected the archive manifest: all entries are relative paths and the required remediation documents are present; extraction will use an isolated repository directory to avoid overwriting current `AGENTS.md` or `START_HERE.md` before comparison.
  - Extracted the handoff safely to `.remediation-handoff/` and read `REMEDIATION_START_HERE.md` completely.
  - Confirmed that the audit targets the current `a7350f4` baseline and that the new remediation acceptance document—not the old aggregate gate—is the completion authority.
  - Read the remediation `AGENTS.md` and current implementation audit completely.
  - Captured the P0 runtime-truthfulness defect and the P1/P2 domain, Agent, clustering, planning, RAG, and workspace gaps for source-level verification.
  - Read `docs/11_REMEDIATION_SPEC.md` and `docs/12_IMPLEMENTATION_GUIDE.md` completely.
  - Recorded the target domain invariants, typed handoff and PlanPatch requirements, recommended deterministic algorithms, RAG rule boundary, and mixed-initiative workspace shape.
  - Read `docs/13_REMEDIATION_ACCEPTANCE.md` completely and enumerated its ten mandatory product-path scenarios and evidence vocabulary.
  - Located all historical `docs/01`–`docs/09` and ADRs required by the remediation entry point for compatibility review.
  - Read historical `docs/01_PRODUCT_SPEC.md` through `docs/04_MEMORY_CONTEXT.md` completely and recorded the retained three-layer planning, provider, MCP, memory, and minimal-context contracts.
  - Read historical `docs/05_PHASE_ACCEPTANCE.md` through `docs/09_RAG_SPEC.md` and both current ADRs completely.
  - Completed all reading required by the remediation entry point; next work is source/test/persistence tracing and a remediation requirement matrix.
  - Verified current config, domain/workflow schemas, persistence records, memory stores, and all Alembic revisions against the audit.
  - Confirmed the exact provider alias bug, pervasive single-subject boundary, walking-only mutation schema, per-use DB engine, and absence of remediation persistence models.
  - Read the full LangGraph and FastAPI product paths and verified provider exception inconsistencies, minimal Reviewer context, violation-agnostic replanning, checkpoint-bypassing edits, per-request resources, and disconnected RAG mutations.
  - Traced provider composition, MCP adapter, clustering/planning, SQL RAG, ingestion, and context implementations.
  - Verified every audited algorithmic/RAG defect in source, including lexical-gated dense retrieval, missing SQL conflicts, namespace-insensitive document IDs, fixed Tokyo/manual access assumptions, and fake geographic clustering.
  - Implemented explicit uppercase environment aliases, safe provider-mode diagnostics, Compose propagation, and the generic validated `ToolOutcome` boundary with focused tests.
  - Routed subject, evidence, geocoding, flights, weather, and matrix graph calls through `ToolOutcome`; added an integrated rate-limit scenario proving geocode/weather degrade and matrix visibly falls back without aborting the trip.
  - Added lifespan-managed engine/session/RAG/store/MCP/LLM resources and lazy one-time LangGraph checkpointer setup, while retaining a bounded fallback for direct unit calls.
  - Passed full local lint, strict typechecks and tests after Scenario A work: 86 Python tests at 80.01% coverage and 5 Web tests.
  - Rebuilt all four Compose services in 166.7 seconds; bounded health checks report all healthy and PostgreSQL available.
  - Verified safe runtime diagnostics from the running API and wrote `artifacts/remediation-a-runtime-truthfulness.md`, honestly marking credentialed live/SearchAPI evidence UNVERIFIED.
  - Exercised the running workflow endpoint to initialize lifespan checkpoint resources, then restored the same waiting-confirmation trip successfully without any external Provider call.
  - Added the remediated strict domain schemas: 1–3 subject intents, scene evidence/quarantine, canonical places/appearances, areas, candidate graphs, itinerary versions, typed patch operations/impact/diff, Agent handoffs, role contexts, and derived knowledge rules.
  - Added an explicit stable legacy `anime_query` adapter into one primary SubjectIntent and focused invariant tests for source accounting, duplicate shared-place scheduling, patch discrimination, handoff completion, and rule authority.
  - First remediation-domain Ruff pass found one now-unused enum import (which also disturbed import sorting); removed it before rerunning the focused checks.
  - A combined error-log patch had an invalid empty hunk and changed nothing; reapplied valid file-specific hunks. Ruff's diff then showed `PlanningStrategy` sorts before `PlanPatch` under its import normalization, so the exact order was applied manually.
  - Focused domain tests exposed that serializing the expanded TripRequest into a 500-character confirmation summary overflowed the boundary. Replaced raw JSON with a concise normalized requirements projection and changed required-subject validation to the new intent set.
  - Added additive ORM records and Alembic `0004` for normalized subjects/intents, evidence, places/links/appearances/overrides, areas/members, candidate graphs, itinerary versions, PlanPatches, Agent handoffs, and derived rules; legacy trip JSON remains untouched.
  - First migration static pass found only the repository's Alembic import grouping convention; moved `alembic.op` after SQLAlchemy imports and retained the implementation unchanged.
  - Mypy could not safely type a generic timestamp-column helper in the Alembic script; inlined the two subject timestamp columns and aligned the ORM record explicitly.
  - Upgraded the existing project PostgreSQL database transactionally from `0003` to `0004`; Alembic reports the new head and legacy data was not rewritten.
  - Created a uniquely named project-scoped empty test database, upgraded it from `0001` through `0004`, verified all six sampled remediation tables, and removed the test database in the command's `finally` block.
  - One intermediate combined patch again contained an invalid empty hunk and made no changes; reapplied the migration/ORM/progress edits with valid adjacent context.
  - Passed full domain-foundation regression: lint, strict Python/TypeScript typing, 95 Python tests at 81.60% coverage, and 5 Web tests.
  - Wrote `artifacts/remediation-domain-foundation.md` with explicit PASS/PARTIAL scenario interpretation and migration evidence.
  - Implemented legacy point→SceneEvidence normalization, deterministic complete-link place resolution with explicit exit conflicts/ambiguity/overrides/quarantine, and stable canonical IDs/medoids/appearances.
  - Implemented Haversine DBSCAN over VisitPlace plus optional road-time outlier correction, recorded parameters/version/status, fallback warnings, and a no-loss membership assertion.
  - First curation static pass found one 102-character ambiguity explanation; wrapped the string without changing behavior.
  - Place/area static checks passed. The first override test expected two places, but its own split override intentionally creates two shared-location places plus one merged-exit place (three total); corrected the assertion while retaining exact membership/re-ingestion checks.
  - Added the area-first/day-assignment/place-selection/nearest-neighbor+bounded-2-opt hierarchical planner, candidate graph construction, explainable strategy score components, timezone/access windows, coverage/omission accounting, and deterministic validations.
  - First hierarchical static pass found one unused import and requested `itertools.pairwise`; applied both mechanical corrections.
  - Passed ten focused place-resolution, DBSCAN-area, and hierarchical-planning tests after lint and strict source typing.
  - Added the Workspace Agent product path with 1–3 independent subject candidate groups, explicit per-intent confirmation, isolated evidence failures, deterministic evidence→place→area curation, estimated-base disclosure, two strategy versions, and typed role handoffs.
  - Added progressive workspace/evidence views and namespace/state-version-checked `/api/workspaces` start/read/confirm/evidence/plan endpoints while retaining the old workflow routes as compatibility APIs.
  - Added and passed focused Agent/API coverage for three subjects, one isolated Anitabi failure, shared-place multi-work coverage without duplicate visits, two independent strategy versions, hidden-by-default evidence, namespace isolation, persisted events, and stale-version rejection.
  - Passed full repository regression for this slice: Ruff, Python/TypeScript strict typing, 108 Python tests at 82.37% coverage, and 5 Web tests.
  - Implemented the common PlanPatch preview/apply path with server-derived material confirmation, expected-version checks, idempotency, centralized invalidation, local move/reorder boundaries, deterministic replanning, Validator handoff, role-specific Reviewer/Replanner contexts, new itinerary versions, and structured diffs.
  - Added API parse/direct-preview/apply routes and passed focused reload/event/state-version tests; natural-language and direct date edits normalize to the same operation.
  - Added normalized SQL projection persistence for subjects, intents, evidence, places, areas, graphs, itinerary versions, patches, handoffs, and derived rules. Namespaced evidence IDs now prevent cross-trip primary-key collisions for the same provider record.
  - Fixed RAG ingestion IDs to include the authorized namespace, removed the SQL dense-retrieval lexical-overlap gate, and reused shared conflict detection in SQL results.
  - Added the strict retrieved-evidence→derived-rule authority/conflict boundary. High-authority current evidence remains proposed until explicit acceptance; conflicting/low-authority evidence remains non-binding, and accepted closure rules produce visit-window omissions through deterministic planning.
- Error log update:
  - A file-targeted mypy invocation treated repository imports from `scripts/` as an untyped installed package; use the configured repository-wide mypy target, which includes the source root correctly.
  - Direct Conda Python lacked the uv-managed application site-packages and could not import SQLAlchemy for the projection smoke. Run the script through the locked `uv run` executable housed in the authorized Conda environment.
  - The first Windows SQL smoke used the default Proactor event loop, which psycopg async explicitly rejects. The smoke now creates a bounded Selector event loop, matching psycopg's Windows requirement.
  - The next host-side SQL smoke inherited the Compose-internal hostname `postgres`, which is not resolvable from Windows. The project-only smoke maps that hostname to `localhost` without logging the URL and skips cleanup when no row was persisted.
  - Normalized PostgreSQL workspace smoke passed and cleaned up its project row: 3 evidence, 3 places, 1 area, 1 candidate graph, 2 itinerary versions, and 6 typed handoffs were persisted.
- Error log:
  - An initial planning-file patch used an outdated heading and failed without changing files; inspected the current tails and reapplied against the exact Phase 14 headings.
  - Two parallel inventory searches referenced nonexistent legacy-style `services/` and `src/pilgrimage_agent/persistence/` directories; both were read-only failures. Re-ran against the actual flat `persistence.py` and current package tree.
  - First focused Ruff pass found one unnecessary quoted generic return annotation in the new outcome model; removed the quotes and tightened the test fixture type before rerunning.
  - First graph-focused Ruff pass found import ordering only in the graph and new degradation test; reordered imports and wrapped the affected expression manually.
  - Lifespan-focused mypy rejected `AbstractAsyncContextManager` from both `typing` and `collections.abc` under the locked stubs; corrected it to the canonical `contextlib` export.

## 5-Question Reboot Check
| Question | Answer |
|----------|--------|
| Where am I? | Complete — all six phases plus persistent conversational Agent acceptance pass |
| Where am I going? | Handoff complete; remaining limits are explicitly documented product boundaries |
| What's the goal? | Deliver the verified pilgrimage Agent with sourced points, deterministic planning, and durable multi-turn conversation |
| What have I learned? | See `findings.md` |
| What have I done? | Completed Phases 1–13, integrated Anitabi and the runtime Agent, added persistent conversation, and passed `make verify-all` |
### 2026-07-14 - Development tool entry points are outside `conda run` PATH

- Running `conda run ... ruff` / `mypy`, then `python -m ruff` / `mypy`, showed that the modules are not installed in the environment's Python site-packages.
- The locked `uv.exe` is present under the environment's `Library/bin`, which `conda run` did not expose on Windows. Resolution: invoke that exact executable for the repository's canonical `uv run` lint/typecheck commands.

### 2026-07-14 - Workspace Agent test fixture initially over-merged nearby records

- The first multi-subject fixture put two intentionally distinct locations inside the 100 m place-resolution radius, so deterministic resolution correctly merged them and the expected canonical-place count failed.
- Resolution: moved the distinct fixture points beyond the place-resolution radius while keeping them inside one 1.2 km area cluster. The remaining assertion was corrected to use the user-facing subject-intent warning label rather than an internal catalog ID.

### 2026-07-14 - Phase 14 remediation completion

- Added persistent workspace conversation endpoints and restored conversation plus pending PlanPatch previews after reload.
- Added the three-pane desktop and tabbed mobile workspace, canonical-place MapLibre view, subject/area/status/confidence filters, itinerary versions, structured omissions, and preview-only mutation controls.
- Real browser acceptance used live Anitabi data: 119 raw scene records became 96 canonical places in 28 areas; 36 places were scheduled across three days with no horizontal overflow at 1440x900 or 375x812.
- Added `make verify-remediation`; remediation scenarios A-J pass and write both Markdown and JSON reports.
- Fixed two aggregate compatibility regressions discovered only by legacy gates: premature Route A heading exposure and fixture/live point-ID divergence in Route B. The latter now bounds matrix candidates and preserves complete omission accounting.
- Final `make verify-all` passed with exit code 0 in 652.4 seconds: all historical phase reports, clean Compose recovery, 131 Python tests at 80.41% coverage, 8 Web tests, 10 full desktop/mobile E2E tests, real SQL/E5 RAG smoke, and remediation A-J.

### 2026-07-15 - Phase 15 single-flow conversation UX

- **Status:** in progress
- User screenshot review identified internal terminology and a one-title-per-line restriction in the initial Agent prompt.
- User clarified that two visible product flows must not coexist; the legacy UI will be removed from the page while backend compatibility remains isolated.
- A second screenshot showed a world-scale, oversized mobile map. The fix will reduce its visual height and default planned workspaces to scheduled locations so remote omitted candidates do not control the viewport.
- User requested an Anitabi-like marker detail experience; selected places will progressively reveal scene references and images without exposing internal provider terminology.
- User screenshots confirmed that workspace IDs, raw status enums, and Agent-to-Agent handoff diagnostics are unnecessary in the product UI; these will be removed rather than relabelled.
- Verified the official screenshot-detail contract: validated thumbnail URL, episode/time, origin text, and origin link are available. Implementation will request/display the documented mobile `h360` image variant and preserve attribution.
- User requested bulk point operations. The map will gain an explicit multi-select mode and one batch PlanPatch preview for all selected places.
- Traced workspace creation and confirmed that the opening request is not stored in the conversation event stream; persistence will be added so the interaction reads as one continuous dialogue.
- Removed the legacy React application from the product entry point and began replacing legacy-labelled tests with single-workspace acceptance.
- Added validated scene image URLs end-to-end, persisted the opening user/assistant exchange, removed visible IDs/status/handoffs, added batch selection UI, and replaced internal patch diagnostics with user-facing impact copy.
- Phase 15 static/focused checks pass: Python/Web lint, strict Python/Web typing, 23 focused Python tests, and 6 Web unit tests.
### 2026-07-15 - Phase 15 final inspection

- Confirmed the latest user-facing copy patch is present and no provider/orchestration terminology is rendered by the workspace.
- Confirmed batch selection creates a single patch containing one operation for every selected place; end-to-end browser verification is next.
- Re-ran lint, strict typechecking, 23 focused Python tests, and 6 Web unit tests; all passed.
- The first Compose rebuild attempt exceeded the command's two-minute wrapper timeout without emitting a failure. The existing healthy stack remains available; retrying the build with a longer bounded timeout and plain progress output.
- Rebuilt the API and Web images and confirmed all four Compose services healthy. `wait_compose.py` succeeds when `TEMP`/`TMP` point at the repository's writable `.tmp-conda` directory.
- Browser verification found and fixed mobile marker overlap as a batch-selection blocker by adding a scrollable checkbox list, select-all, and clear controls. One combined preview now contains all selected points.
- Removed internal patch and planner node names from persisted assistant replies after the browser transcript exposed them.
- The focused desktop/mobile browser suite now passes all 10 scenarios, including three-point batch submission and reload-persistent natural conversation.
- The first aggregate run passed Phases 1-3 and then exposed a Phase 4 mobile-only MapLibre overlap flake: another marker intercepted the physical click. Batch acceptance now uses the accessible checkbox surface, while scene-detail acceptance dispatches to the selected marker explicitly.
- Replaced the flaky marker-only detail path with an always-available, collapsible, scrollable “浏览当前地点” list. Desktop/mobile detail acceptance passed 6/6 repeated runs before the aggregate rerun.
- Final `make verify-all` passed in 436.7 seconds: all six phase reports, 132 Python tests at 80.43% coverage, 6 Web unit tests, 10 desktop/mobile E2E tests, clean Compose recovery, real E5/pgvector checks, secret/privacy scans, and remediation A-J.

### 2026-07-15 - Phase 18 editable work collection

- **Status:** in progress
- Reproduced the user-visible single-select discrepancy by inspecting the live Web bundle: it is older than the checked-in Phase 17 checkbox implementation.
- Audited the current workspace mutation surface and confirmed that arbitrary post-creation work addition/removal is not yet implemented end to end.
- Added Phase 18 to the persistent plan; implementation will cover backend recomputation, consumer controls, regression tests, Compose rebuild, and aggregate verification.
- The first static-check invocation used the parent PowerShell PATH, where `make` is unavailable. No check ran. Continue through the authorized Conda environment with repository-local TEMP/TMP, matching the existing project workflow.
- Lint passed. The first strict Web typecheck found exact-optional typing for the edit callback and two legacy test fixtures missing the newly explicit confirmed-ID fields; both were corrected before rerunning.
- Focused Workspace Agent tests passed 6/6. The direct `conda run pnpm` wrapper then failed while re-emitting a Unicode test name through the legacy GBK console codec; rerun with `PYTHONIOENCODING=utf-8`, as required elsewhere in this project.
- The next lint pass found only import order, line length, and ambiguous full-width punctuation in the new natural-language collection parser. Converted regex punctuation to explicit Unicode escapes and normalized response punctuation without changing Chinese user copy.
- Phase 18 focused checks now pass: lint, strict Python/Web typecheck, 7 Workspace Agent/API tests, and 9 Web unit tests. Added direct controls plus natural-language add/remove patch previews and a regression that preserves unaffected subjects/evidence across add-confirm-remove recomputation.
- Live browser verification found a stale nested-state projection: after adding a new work, an already-confirmed three-season intent displayed only its first candidate as selected because `subject_groups.intent` had not been synchronized with `requirements.subject_intents`. Added compatibility-safe projection synchronization plus persisted synchronization on confirmation.
- The first Phase 18 browser gate passed desktop. Mobile clicked the context tab before the asynchronous confirmation response finished, then the completed response correctly returned focus to the map tab and hid the assertion target. The test now waits for the post-confirmation planning control before switching tabs and uses a 90-second multi-provider scenario budget.
- Rebuilt the API/Web Compose images and replaced the stale port-4173 bundle. All four project services are healthy.
- Live in-app browser verification passed multi-season selection, add preview, add confirmation, preserved prior selections after reload, and version editing. The focused Playwright gate then passed 2/2 on desktop/mobile, including final removal.
- The first aggregate `make verify-all` stopped in Phase 1 after 135 tests passed because one legacy domain test still asserted the superseded three-intent limit. Updated that invariant to accept twelve and reject the thirteenth; rerun the aggregate gate from the beginning.
- The second aggregate run passed Phase 1 (136 Python tests, 9 Web tests) and stopped on the old Phase 2 browser copy assertion `2 部作品`. The editable collection now reports the more precise selected-entry count, so the compatibility assertion was updated to `已选 2 个条目` for desktop/mobile.
- The corrected Phase 2 gate passed, followed by a complete `make verify-all` pass. Final acceptance: 136 Python tests at 81.17% coverage, 9 Web unit tests, 14 desktop/mobile E2E scenarios, clean Compose rebuild/recovery, real E5/pgvector RAG, secret/privacy scans, all six historical phase reports, and remediation scenarios A-J.
- **Status:** complete; the running stack serves the new Web bundle and all four project services are healthy.

### 2026-07-15 - Phase 19 authoritative Agent-runtime remediation

- **Status:** in progress
- Read the repository `AGENTS.md` and began a UTF-8, chunked read of the 976-line authoritative handoff.
- Restored the existing file-based plan and preserved all completed Phase 1–18 records.
- Intake Git snapshot: checked out `codex/publish-current-project`; only `CODEX_REMEDIATION_HANDOFF.md` is untracked, with no tracked or staged changes.
- No project implementation files have been modified yet.
- Read authoritative handoff lines 221–780 and recorded the runtime/context, real Handoff lifecycle, MiriaGo static ingestion, provider, planner, PlanPatch/deletion, and RAG requirements.
- Completed the full 976-line handoff read.
- Fetched `origin/codex/publish-current-project` without changing the worktree. Local HEAD, remote HEAD, and review baseline are all exactly `c544c3b9c1010d17e3a117c73ae273c489c0af56`; there are no later commits to preserve beyond the untracked handoff.
- First aggregate baseline invocation used an accidental one-second shell timeout and was killed before producing test evidence; it is not counted as a product failure.
- Baseline `make verify-all` completed successfully in 579.7 seconds: 136 Python tests (81.17% coverage), 9 Web unit tests, 14 desktop/mobile E2E tests, six phase reports, clean Compose/RAG recovery, and remediation A–J all passed.
- The baseline Compose smoke loaded only 74 Anitabi points, so this PASS is retained as regression evidence but not treated as acceptance of the new completeness or Agent-runtime requirements.
- Read README and inventoried all current source/test entry points. Initial call-chain search confirms `/api/workspaces` uses `WorkspaceAgent` directly while the only LangGraph and configured Reviewer belong to the separate legacy workflow.
- Read the workspace API runtime/routes and the key `WorkspaceAgent` planning/patch paths. Confirmed fake-completed handoffs, context-only Reviewer/Replanner, direct deterministic execution, and unconditional eligible replanning are current implementation gaps.
- Audited workspace/handoff/context schemas and SQL projections. Existing bounded RoleContext and normalized tables are reusable, while lifecycle fields, graph state/checkpoint references, run/tool audit, and deletion operations remain incomplete.
- Audited the Anitabi provider, point schemas, MCP allowlist, composition, config, and tests. Confirmed the code is detail-endpoint-only and lacks every MiriaGo static index/page/version/completeness contract required by the handoff.
- Audited PlanPatch operations, impact analysis, store protocols, API routes, and behavior tests. Confirmed clear/remove/version/archive/delete/undo semantics and all required deletion acceptance tests are absent.
- Audited SearchAPI/MCP, workspace curation, canonical resolution, DBSCAN, and hierarchical planning. Confirmed flights-only SearchAPI, no travel tools in workspace planning, forbidden source-label merging, order-sensitive border handling, and the exact one-area-per-day slice remain.
- Audited Web intake, workspace API surface, conversation reconstruction, LLM boundaries, and RAG integration. Confirmed hard-coded trip defaults/identity, latest-50 context, missing workspace resume/audit/delete endpoints, and reusable but disconnected LLM/RAG primitives.
- Read the handoff-referenced MiriaGo static client/reader source and recorded the exact compact index/page field layout, filename guard, origin fallback, and page-selection behavior before implementing the adapter.
- Implemented the initial MiriaGo static Adapter slice, completeness metadata, detail fallback, Workspace summary, Web disclosure, and focused contracts.
- First lint pass stopped on three mechanical findings (self-reference annotation, import order, unused import); no tests ran in that invocation.
- MiriaGo static fixtures, API/Workspace disclosure, Web completeness rendering, lint, and strict Python/Web typing passed; focused acceptance reached 28 Python and 10 Web tests.
- The first live static smoke honestly returned 406/414 because eight optional `seconds` values were non-numeric strings. MiriaGo's source keeps such points and omits only the timestamp; the Adapter now matches that rule and the repeated live smoke passed 414/414 with zero warnings.
- The first aggregate Phase 2 rerun stopped before Compose after 140 tests passed because `detail_then_imported` had not been added to the value-safe diagnostic Literal. The schema and regression assertion were corrected; rerun the full gate from the start.
- The next Phase 2 run reached a healthy rebuilt Compose stack but Route A exposed only 394/414 records. The loss was a compatibility-view name/coordinate dedupe; Route A now deduplicates exact stable point IDs only, preserving distinct Anitabi scenes at the same real place for later CanonicalPlace resolution.
- The rebuilt API then returned all 414 records, but the legacy smoke repeated the same name/coordinate duplicate rule. Acceptance now checks stable Scene ID uniqueness instead of rejecting valid multi-scene real-place overlap.
- Backend live/Compose acceptance passed: Route A 414 scenes, Anitabi static 414/414, and one read-only Bangumi/ORS/Open-Meteo request each; SearchAPI was explicitly skipped with zero requests because live smoke is disabled. Desktop E2E passed; mobile needed to switch from the map pane to the itinerary-information pane before checking the new completeness disclosure.
- **Independent item complete:** the final Phase 2 gate passed with 142 Python tests, 10 Web unit tests, healthy four-service Compose, 414-point API/live static acceptance, MCP allowlist/schema checks, and 4/4 desktop/mobile E2E. SearchAPI remained explicitly skipped with zero live requests.
- **Next item:** replace direct WorkspaceAgent API execution with the authoritative Workspace LangGraph path, durable interrupts/checkpoints, real Handoff transitions, and actual Reviewer/Replanner calls.
- **Independent item complete:** `/api/workspaces` now executes through a durable Workspace LangGraph with separate requirement, subject, point, place-curation, travel-area, planning, validation, reviewer, and bounded-replanner nodes. Subject and access/base confirmations resume the same checkpoint.
- Handoffs now carry started timestamps, correlation/parent identifiers, and strict pending/running/terminal invariants. Reviewer pending and running states are independently checkpointed before execution.
- The configured LLM Reviewer and Replanner are called through strict schemas. Missing or failed LLM boundaries return explicit partial/failed results and never substitute a fixture result in production.
- Target-day replanning creates a parented version and `PlanVersionDiff`, freezes all non-target days, reruns deterministic planning/validation, and re-enters Reviewer with a bounded revision count.
- Phase 4 initially failed only because MiriaGo static scene image URLs lacked the old detail endpoint's `plan=h360` query. The Web now normalizes every scene image display URL; focused desktop/mobile E2E passed 2/2.
- Final Phase 4 rerun passed: Python/Web lint and strict types, 19 Agent/context/API fixtures, 10 Web unit tests, secret scan, healthy Compose, five PostgreSQL stores, restart checkpoint recovery, one real structured-output LLM smoke, and 6/6 desktop/mobile E2E.
- **Next item:** implement explicit clear/archive/delete/restore semantics so an empty schedule remains empty and no fallback itinerary is regenerated.
- **Independent item complete:** explicit `clear_schedule`, `clear_day`, `restore_itinerary_version`, `delete_itinerary_version`, `archive_workspace`, and transactional `delete_workspace` semantics are implemented.
- Clearing the whole schedule moves immutable versions to trip-owned archive state, retains the candidate graph, returns `ready_to_plan`, and never invokes planning. Clearing one day creates auditable child versions with `user_removed` omissions and no candidate refill.
- Permanent deletion validates owner/thread, cascades trip-owned relational projections and events, and deletes LangGraph checkpoint rows in the same PostgreSQL transaction. Recreating the same trip ID starts at state version 1, proving no checkpoint resurrection.
- The consumer UI now distinguishes local close, archive-and-close, and permanent delete. Permanent deletion requires a second explicit click and explains the irreversible scope.
- Acceptance passed: 125 Python unit tests, 11 Web unit tests, full lint/typecheck, healthy Compose clear/delete/recreate smoke, 6/6 desktop/mobile E2E, and the complete Phase 4 gate.
- **Next item:** extend SearchAPI with transit and place facts, then connect flight/weather/transit/facts tool outcomes to the Workspace graph without any booking or payment surface.
## 2026-07-15 - read-only travel facts in the Workspace graph

- Added strict normalized transit and place-fact schemas plus cached SearchAPI directions,
  place search, and exact place-detail adapters.
- Expanded the exact MCP allowlist from 9 to 12 read-only tools; no booking, payment,
  arbitrary URL, or write capability was added.
- Added Access, Place Facts, and Weather nodes to the authoritative Workspace LangGraph
  with checkpoint-visible pending/running/terminal Handoff states.
- Persisted bounded access candidates, place facts, weather, and provider snapshot metadata
  in WorkspaceState. Low-confidence name matches and out-of-window forecasts remain unknown.
- Verification: lint/typecheck PASS; 154 Python tests PASS; 11 Web tests PASS;
  Phase 2 Compose gate PASS with four healthy services, MCP 12/12, Anitabi 414/414,
  and desktop/mobile E2E 4/4.
- Live SearchAPI transit/place remains explicitly UNVERIFIED because live smoke is disabled;
  fixture contract coverage is PASS.
## 2026-07-15 - identity-safe clustering and time-dependent planning

- Removed source-label identity merging, added an ECEF spatial candidate index, preserved
  uncertain nearby pairs as ambiguous, and bumped canonical resolution to v2.
- Fixed DBSCAN noise-to-border reassignment and bumped stable travel-area clustering to v2.
- Added bounded ORS walking edges and nearby-area transit edges to WorkspaceState.
- Removed the one-area-per-day truncation. The planner now composes multiple areas per day,
  consumes walking/transit edges, opening facts, weather, and access buffers, and validates
  provenance/TTL, overlap, exclusions, and arrival/departure buffers.
- Added structured transit route preferences and deterministic Chinese fallback extraction.
- Verification: 163 Python tests, 11 Web tests, lint and strict types PASS; Phase 4 Compose
  PASS including PostgreSQL checkpoint restart, transactional deletion, a real structured
  Reviewer call, and desktop/mobile E2E 6/6.

## 2026-07-15 - Phase 19 final remediation acceptance

- Completed the remaining session-isolation, safe-warning, knowledge-retrieval, multi-subject,
  and browser acceptance gaps without replacing the authoritative Workspace Agent graph.
- Fixed upstream PlanPatch subject additions so the durable graph is rebased from the current
  database workspace, then resumes typed multi-subject confirmation without losing existing work.
- Corrected root LangGraph checkpoint identity: the product version now lives in the hashed
  thread key instead of misusing `checkpoint_ns`, which LangGraph reserves for subgraphs.
- Phase 5 passed with 167 Python tests at 81.50% coverage, 15 Web unit tests, real 384-dimensional
  E5, SQL pgvector/BM25/RRF, and 14/14 desktop/mobile E2E scenarios.
- Phase 6 passed from empty project Compose volumes, including migrations, recovery/isolation,
  privacy/MCP audits, API demos, and 14/14 desktop/mobile E2E scenarios.
- `make verify-remediation` passed acceptance A-J.
- Final `make verify-all` exited 0 in 2079 seconds and reran all six phase gates plus remediation
  A-J from the same working tree. Live SearchAPI transit/place checks remain explicitly unverified
  when live smoke is disabled; fixture contracts pass and no live PASS is fabricated.

## 2026-07-15 - Phase 20 large-batch itinerary correction

- Reproduced the reported failure from the raw response: 109 selected places were serialized as
  109 patch operations, exceeding the strict 25-operation `PlanPatch` boundary.
- Confirmed a second defect in the same path: the Web API helper displays structured 422 response
  bodies verbatim instead of translating them into a safe, concise message.
- Planned correction: one bounded batch-place operation, shared deterministic preview/apply logic,
  safe error normalization, and regressions spanning domain/API/Web/browser behavior.
- Implemented `place_batch` with a 2000-ID hard bound, uniqueness/target validation, complete
  impact references, atomic Workspace application, JSON persistence, and one Web operation label.
- Added a value-free FastAPI validation exception response and status/known-error normalization in
  the Web; structured Pydantic arrays are no longer displayed or echoed.
- Focused verification passed: 26 Python domain/Agent/API tests, 17 Web tests, Python/Web lint,
  Python/TypeScript typechecks, a healthy rebuilt four-service Compose stack, and the real large
  batch browser scenario on desktop and mobile.
- One initial browser attempt timed out before this path because two live catalog lookups completed
  at the old 30-second threshold. The shared start wait now allows 60 seconds, and the regression
  directly uses the single-title K-On all-versions case to isolate the batch boundary.
- Canonical focused commands passed: `make lint`, `make typecheck`, and `make test`; the latter ran
  171 Python tests at 81.68% coverage and 17 Web tests. Compose health/database checks and the
  targeted desktop/mobile Playwright scenario also passed.
- The user replaced mechanical full-gate reruns with layered validation. The in-progress Phase 5
  gate was terminated without a result; `make verify-all` was not run for this small fix. No live
  Provider smoke was required because no Provider boundary changed.
