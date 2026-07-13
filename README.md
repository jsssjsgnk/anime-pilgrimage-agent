# Anime Pilgrimage Agent

A source-aware, mixed-initiative travel planner for anime pilgrimage trips. The application separates a complete, sourced set of pilgrimage candidates (Route A) from the constraint-checked executable itinerary (Route B). It never books, pays, or silently confirms consequential choices.

> This repository is under phased implementation. The current authoritative acceptance status is recorded under `artifacts/`.

## Prerequisites

- Conda
- Docker Desktop with Compose
- Node.js 24 and pnpm 11 (or Corepack)

Local configuration belongs in `.env`; copy the empty names from `.env.example`. Never commit secret values.

## Fast development mode

```powershell
conda env create --solver rattler -f environment.yml
conda activate anime-pilgrimage-agent
make bootstrap
make verify-env
make dev-infra
make dev
```

This runs PostgreSQL/pgvector in Docker while API, read-only MCP tools, and Web run from the local Conda/Node toolchains.

## Full Compose mode

```powershell
conda activate anime-pilgrimage-agent
make bootstrap
make compose-up
```

The Web is served at `http://localhost:4173`, the API at `http://localhost:8000`, MCP is internal-only, and PostgreSQL is available at `localhost:5432` for development tooling. Stop only this project with `make compose-down`.

## Verification

```powershell
make lint
make typecheck
make test
make verify-phase-1
# ... through verify-phase-6
make verify-all
```

Each gate writes a human-readable report under `artifacts/`. Fixture, browser E2E, and live read-only smoke results are reported separately. Live smoke never performs booking, payment, writes, or irreversible actions.

## Data caveats

Flight prices, weather, routes, access rules, and opening information are snapshots or estimates and must be reconfirmed before departure. Unknown or partially verified data stays explicitly unknown; the system does not invent points, prices, rules, or citations.

