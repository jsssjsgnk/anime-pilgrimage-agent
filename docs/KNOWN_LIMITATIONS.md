# Known limitations

## External data

- The pilgrimage-point boundary uses legal JSON/GeoJSON import plus fixtures; it does not scrape or bypass Anitabi. The included subject `328609` fixture has three sourced records solely for reproducible acceptance and is not an exhaustive real-world location set. Operators can extend `fixtures/providers/points.geojson` with permitted records carrying valid coordinates and source URLs.
- The MapLibre view loads the no-key OpenFreeMap Liberty style and OpenStreetMap-derived tiles at runtime. It needs network access for street detail, displays the provider/data attribution, and degrades to numbered markers plus the adjacent source list if the basemap is unavailable.
- Bangumi, ORS, Open-Meteo, and SearchAPI can change or become unavailable. Providers use timeouts, bounded retries, normalized partial/unknown states, provenance, and caches, but the user must reconfirm time-sensitive facts.
- SearchAPI smoke has a strict call budget. It searches only and never follows booking/payment links.
- Google Maps URLs are handoff links, not evidence that a route is open or safe at travel time.

## RAG

- The MVP supports Markdown, TXT, and text PDFs up to 10 MiB/200 pages. It does not execute attachments or external resources and does not perform OCR.
- `intfloat/multilingual-e5-small` is 384-dimensional and runs locally. Its initial official snapshot download is an operator prerequisite; gates run it offline afterward.
- Exact pgvector search is intentional below roughly 10,000 chunks. HNSW must be justified by a benchmark before introduction.
- The fixed 24-query evaluation is small and scenario-specific. Two failed query IDs are disclosed in `artifacts/rag-evaluation.json`; averages are not a claim of general factual accuracy.
- Low-authority community notes provide experience only. Hard access/photography facts require authority ≥4, and conflicts stay visible rather than being silently resolved.

## Operations

- This is a local four-service Compose stack, not a deployed high-availability system. Authentication is represented by server-derived owner/trip inputs at the API boundary; a production identity provider is out of scope.
- PostgreSQL and BM25 use named volumes. The Phase 6 clean-start gate intentionally removes only these project volumes and recreates them.
- The Web revision demo supports a Day 2 walking constraint and preserves other days; it is not a general natural-language plan-patch interpreter.
- The production Web bundle is currently a single large Vite chunk. It is acceptable for the local demo but should be code-split before latency-sensitive deployment.
- Accessibility is covered by semantic roles, keyboard-focus patterns, contrast, responsive layouts, and automated browser checks, but no external assistive-technology certification was performed.
