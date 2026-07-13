# ADR 0002: Durable agent memory and hybrid RAG

Status: Accepted

## Context

The workflow must survive restarts, isolate users/trips, avoid account-memory dependencies, and retrieve multilingual guidance without treating documents as instructions.

## Decision

Use LangGraph with PostgreSQL checkpoints and native interrupt/resume for requirements, subject, and access/base confirmations. Keep five project-owned stores for trip state/events, opt-in preferences, knowledge metadata, and normalized tool cache. ContextBuilder emits only a minimal versioned snapshot. Reviewer output is strict JSON and replanning stops after three revisions.

Use local `intfloat/multilingual-e5-small` embeddings (query/passage prefixes, mean pooling, normalization), pgvector exact cosine search, application-layer persistent bm25s, and RRF(k=60). Apply server-derived namespace and metadata/validity filters before ranking. Wrap evidence as untrusted data, validate citations against the current retrieval set, and surface source conflicts.

## Consequences

- State and knowledge survive scoped service/database restarts without reading ChatGPT account memory.
- Deterministic filters and validators own security/correctness even if model or documents are malicious.
- Initial E5 model acquisition is an operator prerequisite; a fixture embedder keeps non-model tests deterministic.
