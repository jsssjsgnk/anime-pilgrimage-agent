# Route A map correction report

**Status:** PASS

**Date:** 2026-07-14

**Scope:** User-reported blank Route A basemap and ambiguous three-point count

## Corrected behavior

- Route A now loads the official no-key OpenFreeMap Liberty style in MapLibre and shows OpenStreetMap-derived street detail.
- Visible, expanded map attribution is supplied by the official style.
- The map supports cooperative pan/zoom, localized zoom/fullscreen controls, keyboard focus, and 44px numbered markers with text-only popups.
- When the basemap fails, the UI reports that state while retaining numbered markers and the adjacent sourced point list.
- Route A now labels the result as the current imported candidate set and states that the three fixture records are not the work's exhaustive real-world location set.

## Verification

| Check | Result |
|---|---|
| `make lint` | PASS |
| `make typecheck` | PASS |
| `make test` | PASS — 57 Python tests, 3 Web tests, 80.13% Python coverage |
| Focused Phase 2 desktop/mobile E2E | PASS — 2/2 |
| Full desktop/mobile browser flow after fixed-corpus seed | PASS — 8/8 |
| Production Web image rebuild | PASS |
| Four-service Compose health | PASS |
| Desktop/mobile screenshot inspection | PASS |

The fixed RAG corpus was removed again after the full browser run. `make verify-all` was not replayed because its already-consumed SearchAPI live-call budget must not be exceeded; this correction made no provider, API, planning, or RAG logic changes.
