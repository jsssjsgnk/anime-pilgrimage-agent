# Task Plan: Anime Pilgrimage Agent — Six-Phase Delivery

## Goal
Read the complete required handoff chain, implement and verify all six project phases, and finish only when `make verify-all` passes or a genuine user-only blocker is documented.

## Current Phase
Phase 3 — Access/Base planning and deterministic Route B

## Phases

### Phase 0: Required handoff discovery
- [x] Read `START_HERE.md` and every document it marks required
- [x] Inventory repository state, constraints, and required gates
- [x] Record architecture and execution decisions
- **Status:** complete

### Phase 1: Project foundation
- [x] Implement the Phase 1 handoff requirements
- [x] Run and fix `make verify-phase-1`
- [x] Commit the completed phase if Git identity is configured
- **Status:** complete

### Phase 2: Providers, MCP, subject confirmation, and Route A
- [x] Implement the Phase 2 handoff requirements
- [x] Run and fix `make verify-phase-2`
- [x] Commit the completed phase if Git identity is configured
- **Status:** complete

### Phase 3: Access/Base planning and deterministic Route B
- [ ] Implement the Phase 3 handoff requirements
- [ ] Run and fix `make verify-phase-3`
- [ ] Commit the completed phase if Git identity is configured
- **Status:** in_progress

### Phase 4: LangGraph, project memory, context, and replanning
- [ ] Implement the Phase 4 handoff requirements
- [ ] Run and fix `make verify-phase-4`
- [ ] Commit the completed phase if Git identity is configured
- **Status:** pending

### Phase 5: RAG, complete Web flow, and exports
- [ ] Implement the Phase 5 handoff requirements
- [ ] Run and fix `make verify-phase-5`
- [ ] Commit the completed phase if Git identity is configured
- **Status:** pending

### Phase 6: Evaluation, hardening, documentation, and final acceptance
- [ ] Implement the Phase 6 handoff requirements
- [ ] Run and fix `make verify-phase-6`
- [ ] Run and fix `make verify-all`
- [ ] Commit the completed phase if Git identity is configured
- **Status:** pending

## Key Questions
1. Which exact documents and acceptance criteria does `START_HERE.md` require?
2. What code already exists, and which unrelated user changes must be preserved?
3. Which gates require Conda, Docker Compose, credentials, or external services?

## Decisions Made
| Decision | Rationale |
|----------|-----------|
| Use only repository handoffs, user instructions, and required official technical docs | Enforces the project information boundary |
| Keep durable plan, findings, and progress files in the repository root | Supports long-running autonomous work and recovery |
| Treat each phase gate plus its human-readable artifact as the phase completion condition | Matches the mandated workflow |

## Errors Encountered
| Error | Attempt | Resolution |
|-------|---------|------------|
| Duplicate goal creation rejected because this task already had an active goal | 1 | Retrieved and continued the existing goal |
| PowerShell decoded UTF-8 Chinese handoff text with the legacy console encoding | 1 | Re-read handoff files explicitly with `-Encoding UTF8` |
| Initial `conda env create` exceeded the 120-second command budget without emitting an error | 1 | Inspect partial environment state, then use a bounded alternative instead of repeating blindly |
| Conda 26 rejected legacy solver name `libmamba`; supported choices are `classic` and `rattler` | 2 | Use the supported `rattler` solver |
| Conda 26 `env update` rejected the obsolete `-y` flag | 1 | Re-run the update without `-y`; this subcommand is non-interactive here |
| `conda run` could not create its transient activation file in the inherited TEMP directory | 1 | Validate TEMP and use a repository-local ignored temp directory for non-interactive Conda commands |
| Planning patch used a cross-file context without declaring the next file | 1 | Reissued the patch with explicit file headers |
| Piping `make --version` into `Select-Object -First 1` caused a broken-pipe exit despite successful version output | 1 | Re-run the remaining environment assertion without truncating the subprocess output |
| UI/UX skill's documented `scripts/search.py` path was absent from the installed skill root | 1 | Locate the packaged script with `rg --files` before retrying |
| Installed UI/UX skill's `scripts` entry is a broken relative-path placeholder and no packaged generator is available | 2 | Persist a scoped design system manually from the fully read skill rules and continue |
| A broad fallback search for the missing skill script crossed the repository information boundary at the filename level and hit an access-denied directory | 1 | Discarded the search result; restrict all further filesystem discovery to the repository and explicit skill root |
| pnpm 11 rejected the initial install because esbuild's required install script was not explicitly allowlisted | 1 | Add only `esbuild` to `onlyBuiltDependencies`; keep every other dependency script blocked |
| pnpm continued to report esbuild ignored after adding the legacy allowlist key | 2 | Inspect the installed pnpm 11 help/config and use its current project-level approval format |
| pnpm 11 approval format identified locally | 3 | Use `allowBuilds: {esbuild: true}` and rebuild only esbuild |
| pnpm's earlier failed install had appended a placeholder `allowBuilds` mapping, causing a duplicate YAML key | 1 | Remove the placeholder and retain only the explicit boolean approval |
| Python lock completed but dependency sync was canceled when the parallel pnpm install rejected | 1 | Run `uv sync --active --extra dev` independently, then verify imports |
| First Phase 1 static pass found 26 Ruff findings and one mypy test-construction error | 1 | Applied mechanical import fixes, explicit narrow security exceptions, line wrapping, PEP 695 generics, and runtime model validation in the test |
| Conda's wrapper crashed while re-emitting a lint character through the legacy GBK console codec | 1 | Force UTF-8 Python I/O for all subsequent `conda run` commands |
| TypeScript rejected Vitest's `test` key when Vite's narrower `defineConfig` type was imported | 1 | Import `defineConfig` from `vitest/config` |
| Web lint found the E2E file outside the TS project and an unsafe matcher typed as `any` | 1 | Include `e2e` in strict TS scope and assert the known fixture string directly |
| Vitest discovered the Playwright spec and DOM cleanup was not registered with non-global Vitest APIs | 1 | Restrict Vitest to `tests/**/*.test.*` and register explicit Testing Library cleanup |
| Secret-assignment regex treated a newline after an empty documented variable as whitespace before the next line | 1 | Limit assignment separators to horizontal whitespace so empty `.env` documentation remains valid |
| First Compose build pulled pgvector but Docker Bake failed with a non-printable internal gRPC session header | 1 | Retry the same scoped build with Compose Bake disabled, avoiding the failing orchestration path |
| Internal Compose builder reached the Web image but rejected pnpm's workspace symlinks because `node_modules` was in the build context | 2 | Add a strict `.dockerignore` excluding dependencies, secrets, artifacts, caches, and planning files |
| API migration ignored Compose's uppercase `DATABASE_URL` and used the localhost default | 1 | Add an explicit Pydantic alias for the server-side database environment variable |
| Manual Compose smoke omitted the known local TEMP override and its error branch accidentally reset the captured exit code after `docker compose ps` | 1 | Re-run with repository TEMP/TMP and preserve the failure code before diagnostics |
| Playwright's mobile project was named Chromium but inherited WebKit from the iPhone device descriptor | 1 | Use the Pixel 7 mobile descriptor so the installed Chromium runtime is selected explicitly |
| Mobile E2E correctly caught that the no-booking/no-payment safety boundary was visually hidden below 640px | 1 | Make the safety message a full-width mobile header row and compact it inline on larger screens |
| Full-page Chromium capture exposed the off-canvas transformed skip link as an overlay despite button focus | 1 | Use the robust visually-hidden clip pattern and reveal it only on `:focus-visible` |
| First Phase 1 gate could not launch the pnpm Windows command shim and aborted before writing its report | 1 | Resolve every executable explicitly, handle launch errors as failed checks, and always complete report generation |
| Engine unit test picked up an unrelated local `DATABASE_URL` driver after the alias fix and lacked that driver's package | 1 | Inject a deterministic asyncpg Settings fixture so tests never depend on local configuration |
| First Phase 2 static pass found formatting, inferred provider-union, PEP 695 generic, and async button-handler issues | 1 | Apply narrow formatting/type corrections and make the UI event handler explicitly fire-and-observe |
| Phase 2 focused pass found formatting plus secret-scanner false positives on dynamic and explicit fixture credentials | 1 | Format the scripts and narrow the scanner to literal/high-entropy assignments while exempting clearly labelled fixtures |
| Full test pass exposed lower aggregate coverage after adding the five provider implementations and a MapLibre worker API missing in jsdom | 1 | Add contract coverage for every fixture/composition/cache path, omit executable smoke modules, and provide the browser worker URL stub in test setup |
| First full Phase 2 gate launch used a one-second shell timeout and was terminated before meaningful work | 1 | Re-run the same gate with a long command budget and normal streamed yields |
| Phase 2 gate reached live smoke but launched it outside the project `.venv`, so imports failed before any network request | 1 | Run the live smoke through locked `uv run python`; no live-call quota was consumed |
| First SearchAPI live request returned the current documented split airport `date`/`time` shape, which the parser treated as a combined timestamp | 1 | Verify the official response example, combine date/time deterministically, and map `first` to the documented `first_class` request value |

## Guardrails
- Never expose `.env`, secrets, tokens, headers, cookies, or signed MCP URLs.
- Never book, pay, deploy, publish, message externally, or create external resources without explicit authorization.
- Use only the `anime-pilgrimage-agent` Conda environment and repository-scoped Docker resources.
- Preserve unrelated changes and never use destructive Git commands.
