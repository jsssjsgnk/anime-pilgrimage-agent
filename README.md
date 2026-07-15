# Anime Pilgrimage Agent

A source-aware, mixed-initiative planner that turns natural multi-work pilgrimage requests into a constraint-checked, multi-day itinerary. The product uses one continuous conversational workspace for title confirmation, place exploration, batch selection, planning, and revision. It is read-only: it never books, pays, or silently confirms consequential choices.

## What is implemented

- Bangumi subject search with explicit confirmation, followed by the documented Anitabi Open API with honest complete/partial Route A semantics and legal import fallback.
- Read-only provider/MCP boundaries for catalog, points, ORS, weather, and flight snapshots.
- Deterministic access/base selection, road-matrix planning, omissions, buffers, time zones, walking limits, and bounded Google Maps URLs.
- A durable LangGraph workflow with three explicit interrupts, PostgreSQL checkpoints, five project-owned memory stores, structured review, and a three-revision cap.
- Trip-scoped continuous conversation with PostgreSQL history, browser reload recovery, grounded status/plan/source explanations, and deterministic conversational replanning.
- Hybrid RAG for Markdown/TXT/text PDFs using multilingual E5, exact pgvector cosine search, persistent bm25s, RRF, namespace filters, citations, freshness, conflicts, and prompt-injection isolation.
- A responsive React workspace for natural request → title confirmation → scene/place exploration → batch selection → multi-day plan → conversational revision, with scene images and source attribution disclosed on demand.

## Architecture

```mermaid
flowchart LR
    WEB["React / TypeScript Web"] --> API["FastAPI / Pydantic"]
    API --> GRAPH["LangGraph workflow"]
    GRAPH --> MCP["Read-only MCP allowlist"]
    MCP --> PROVIDERS["Bangumi · Anitabi · ORS · Weather · SearchAPI"]
    API --> PG["PostgreSQL 16 + pgvector"]
    GRAPH --> PG
    API --> RAG["E5 + exact vector + persistent BM25 + RRF"]
    RAG --> PG
```

Pydantic schemas guard every provider, tool, LLM, API, RAG, and export boundary. Deterministic code—not the model—owns distance/time/price arithmetic, time zones, membership, retry and revision limits, namespace filters, and validation. See [architecture](docs/02_ARCHITECTURE.md) and the accepted [ADRs](docs/adr/).

## Prerequisites

- Conda
- Docker Desktop with Compose
- Git

The dedicated environment is exactly `anime-pilgrimage-agent`. `environment.yml` owns Python 3.12, uv, and Make; `uv.lock` and `pnpm-lock.yaml` own application dependencies. Local values belong only in ignored `.env`; copy variable names from `.env.example` and never commit values.

## Bootstrap and fast development

```powershell
conda env create --solver rattler -f environment.yml
conda activate anime-pilgrimage-agent
make bootstrap
make verify-env
make dev-infra
make dev
```

Fast mode runs only PostgreSQL/pgvector in Docker. API, MCP, and Web run from the local locked toolchains. If the environment already exists, `make bootstrap-conda` updates only this dedicated environment from `environment.yml`.

## Full Compose

```powershell
conda activate anime-pilgrimage-agent
make compose-up
```

Web: `http://localhost:4173`; API: `http://localhost:8000`. MCP and PostgreSQL are isolated on the backend network (PostgreSQL also exposes a development port). Named volumes preserve PostgreSQL and the application-layer BM25 indexes. Stop only this project with `make compose-down`; do not prune unrelated Docker resources.

## Demo

The reproducible walkthrough is in [docs/DEMO.md](docs/DEMO.md). In brief:

1. Open the Web and describe several works and the desired pace in one natural sentence.
2. Confirm the matched works once, then explore the compact map and open a point to inspect its episode, scene image, and source link.
3. Enter batch-selection mode, tick any number of filtered places (or select all), and preview one combined add/exclude/move operation.
4. Generate the multi-day itinerary, then continue the same conversation with a request such as “第二天少走一点”.
5. Confirm the preview, refresh the browser, and verify the conversation and updated itinerary recover without exposing internal IDs or orchestration diagnostics.

All dates are relative to the test clock. The included content is fixed, short, project-authored fixture material; live provider checks are separate and read-only.

## Verification

```powershell
make lint
make typecheck
make test
make verify-phase-1
make verify-phase-2
make verify-phase-3
make verify-phase-4
make verify-phase-5
make verify-phase-6
make verify-all
```

Every phase writes `artifacts/phase-N-report.md` and fails non-zero on a failed check. `make verify-all` replays all six phase gates. Reports separate fixtures, browser E2E, real read-only smoke, and model smoke. Final evidence is summarized in `artifacts/final-verification.md`.

Current fixed-corpus RAG metrics are Recall@6 **0.929**, MRR@10 **0.952**, and Citation Precision **0.952**. Aggregate Python coverage is at least 80%; the validator/property suite covers Route B membership, required/excluded points, time windows, buffers, time zones, walking limits, and URL bounds.

## Security and privacy

- Secrets stay server-side and are scanned from source, reports, browser artifacts, and the production Web bundle without printing values.
- Project output is checked for the kickoff/conversation body, credential values, and forbidden MCP tools.
- MCP exposes exactly nine allowlisted read-only tools; there is no booking, payment, shell, filesystem, arbitrary URL, or database-query tool.
- External pages, uploads, MCP responses, and RAG text are untrusted data. Citations are limited to the current retrieval result.
- User and trip data are restricted to `curated + current user + current trip`; deletion removes database, dense, BM25, and citation visibility.

## Known limitations

- The documented Anitabi `/points/detail` response currently exposes 74 point details for subject `328609`, while `/lite` advertises 414 map points (and currently reports `imagesLength=414`). The product returns those 74 sourced records with `is_complete=false`; it does not scrape or invent the unavailable remainder. A configurable legal JSON/GeoJSON import remains a labelled fallback.
- The interactive MapLibre basemap uses the no-key OpenFreeMap Liberty style with OpenStreetMap data and visible attribution, so street tiles require an internet connection; the numbered markers and adjacent point list remain available if the basemap cannot load.
- Flights, routes, weather, prices, opening/access rules, and photography rules are snapshots or estimates and must be reconfirmed before departure.
- The MVP extracts text PDFs with pypdf but does not run OCR; scanned PDFs return `needs_ocr`.
- Workspace changes use validated PlanPatch operations for dates, daily walking limits, point inclusion/exclusion, and local move/reorder actions. Material changes require preview and explicit confirmation; arbitrary free-form mutations remain unsupported.
- Conversation keeps the latest 50 normalized messages per trip. Recognized status, source, confirmation, weather, evidence, and local-change intents use deterministic handling; configured LLM synthesis is reserved for otherwise-general questions and cannot directly mutate the plan.
- The real multilingual E5 snapshot must be downloaded once before offline verification; the Compose image includes CPU-only PyTorch, not CUDA, and model weights are not committed to Git.
- This is a local portfolio implementation, not a deployed or multi-tenant production service.

See [the complete limitations](docs/KNOWN_LIMITATIONS.md), [data/safety policy](docs/06_DATA_SAFETY.md), and [resume/interview notes](docs/RESUME_BULLETS.md).
