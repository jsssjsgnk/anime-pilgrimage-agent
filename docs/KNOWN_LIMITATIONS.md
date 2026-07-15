# Known limitations

## External data

- The primary pilgrimage-point boundary is the documented read-only Anitabi Open API. For subject `328609`, `/lite` currently advertises 414 map points (and reports `imagesLength=414`), while `/points/detail` returns 74 records without a documented pagination parameter. Route A therefore exposes the sourced detail subset as partial and never invents or scrapes the unavailable remainder. Legal JSON/GeoJSON import and fixtures remain explicit fallbacks.
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
- Continuous conversation retains the latest 50 normalized messages for the current trip. It answers from bounded workspace facts and can propose validated PlanPatch operations; arbitrary requirement rewrites and silent critical confirmations remain intentionally unsupported.
- PostgreSQL and BM25 use named volumes. The Phase 6 clean-start gate intentionally removes only these project volumes and recreates them.
- Natural-language revision recognizes a bounded set of date and walking-limit edits. The UI also proposes validated point inclusion/exclusion and local move/reorder patches. Unsupported prose stays conversational, and material patches require explicit confirmation.
- The local Compose stack uses CPU-only PyTorch for real multilingual E5 retrieval. The model snapshot is downloaded separately and cached; an unavailable snapshot degrades retrieval to `insufficient_evidence` instead of fabricating guidance.
- The production Web bundle is currently a single large Vite chunk. It is acceptable for the local demo but should be code-split before latency-sensitive deployment.
- Accessibility is covered by semantic roles, keyboard-focus patterns, contrast, responsive layouts, and automated browser checks, but no external assistive-technology certification was performed.
