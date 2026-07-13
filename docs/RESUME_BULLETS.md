# Portfolio notes

## Resume bullets

- Built a six-phase, source-aware anime pilgrimage planner with React, FastAPI, LangGraph, PostgreSQL/pgvector, and a read-only MCP tool gateway; enforced explicit confirmation and deterministic Route A→Route B membership, time-zone, buffer, and walking constraints.
- Implemented local hybrid RAG using multilingual E5, exact cosine search, persistent bm25s, RRF, namespace isolation, freshness/conflict handling, and citation validation; achieved 0.929 Recall@6, 0.952 MRR@10, and 0.952 citation precision on a disclosed 24-query fixture set.
- Designed failure-safe provider contracts with strict Pydantic schemas, bounded retries/timeouts, 429/invalid-JSON normalization, provenance/caching, and fixture/live evidence separation; verified database and workflow recovery across scoped container restarts.
- Delivered a responsive, accessible five-stage planning UI with sourced maps, local replanning stability, and versioned JSON/GeoJSON plus standalone HTML exports, covered by serialized desktop/mobile Playwright acceptance.
- Automated reproducible acceptance through Make/Conda/uv/pnpm/Docker Compose, ≥80% backend coverage, secret/conversation-output scans, dependency-license inventory, clean-volume boot, and human-readable phase/final reports.

## Interview talking points

- Why two routes: Route A preserves recall and provenance; Route B is a deterministic executable subset with an omission reason for every excluded candidate.
- Why LangGraph: explicit interrupts and bounded cycles make consequential confirmations, failure states, restart recovery, and maximum revisions inspectable.
- Why hybrid RAG: E5 handles multilingual semantics, BM25 preserves exact names/terms, and RRF avoids uncalibrated score mixing. Metadata and namespace filtering happen before ranking.
- Why the LLM is constrained: it interprets and explains, while code owns calculations, authorization scopes, citations, retries, and termination.
- What I would productionize next: real identity/authentication, a broader licensed evaluation corpus, observability with value-safe traces, Web code splitting, and load/chaos benchmarks before approximate vector indexing.
