# Phase 19 authoritative remediation gap audit

## Authority and preservation

- Authority: repository `AGENTS.md` and user-supplied `CODEX_REMEDIATION_HANDOFF.md`.
- Review baseline: `c544c3b9c1010d17e3a117c73ae273c489c0af56`.
- Checked branch: `codex/publish-current-project`.
- Local HEAD and fetched remote HEAD both equal the review baseline; there are zero later commits.
- Intake had no tracked or staged user changes. The untracked authority handoff is preserved.

## Regression baseline

`make verify-all` passed from the unchanged implementation in 579.7 seconds:

- Python lint and strict typing: PASS.
- Python tests: 136 PASS, 81.17% coverage.
- Web unit tests: 9 PASS.
- Desktop/mobile E2E: 14 PASS.
- Historical phase gates 1–6: PASS.
- Historical remediation A–J: PASS.
- Compose clean rebuild, PostgreSQL recovery, and real-E5/pgvector smoke: PASS.
- Live SearchAPI transit/place/flight quota: UNVERIFIED by this baseline.
- Live Workspace LLM Reviewer/Replanner: NOT IMPLEMENTED, therefore not a PASS.
- Static Anitabi completeness: NOT IMPLEMENTED; the Compose smoke loaded only 74 detail records.

## Reuse instead of reimplementation

The following foundations are present and should be extended:

- multi-work and multi-season explicit subject confirmation;
- in-workspace work add/remove with preservation of unaffected evidence;
- SceneEvidence, VisitPlace, AreaCluster, candidate graph, and itinerary version schemas;
- deterministic place/area/planner modules with stable IDs and no-loss assertions;
- PlanPatch preview, optimistic version checks, idempotency, impact metadata, and diffs;
- bounded RoleContext builders and strict Requirement/Reviewer LLM schemas;
- normalized SQL projections and project-owned conversation events;
- hybrid RAG retrieval, namespace filtering, proposed-rule validation, and acceptance;
- React mixed workspace, map markers/details, batch point selection, and desktop/mobile tests.

## Confirmed gaps

| Capability | Current evidence | Status |
|---|---|---|
| Workspace LangGraph main chain | `/api/workspaces` invokes `WorkspaceAgent` directly; only legacy `/api/workflows` uses `StateGraph` | missing |
| Real Reviewer/Replanner | workspace creates contexts and already-terminal handoffs but calls neither receiver | missing |
| Handoff lifecycle | helper writes completed/partial with identical create/complete timestamps | incorrect |
| Checkpoint interrupt/resume | only legacy workflow has graph checkpoint/resume | missing |
| Anitabi static completeness | provider uses lite + detail only; baseline loads 74 | missing |
| Clear/remove/delete/restore semantics | no operation/API/store support; exclude triggers refill | missing |
| Transit and place facts | SearchAPI implements flights/calendar only | missing |
| Travel tools in workspace planning | confirmation/planning calls no ORS/weather/flight/transit/place tools | missing |
| Canonical identity | equal source label within 100 m forces merge; all-pairs comparison | incorrect |
| Travel-area DBSCAN | early noise singleton cannot be absorbed by later core; workspace supplies no ORS matrix | partial |
| Multi-area/time-dependent planning | exact `reachable_areas[:len(windows)]` one-area/day slice remains | missing |
| Context compression | latest 50 event projection and latest 8 LLM messages; no traceable summary | partial |
| RAG closure | retrieval/rule APIs exist, but no workspace graph retriever node or Web rule controls | partial |
| Frontend intake/session | hard-coded Tokyo/medium and fixed local identity in component | incorrect |
| Workspace audit/provider APIs | list/resume/runs/handoffs/evidence snapshots/delete absent | missing |

## Dependency-ordered implementation plan

1. **Runtime and evidence contracts**
   - add static-point completeness/version schemas, provider snapshots, real handoff/run lifecycle fields, pending confirmation, reviewer assessments, and explicit schedule/version/workspace operations;
   - preserve compatibility adapters for existing persisted state and routes.

2. **MiriaGo static Anitabi adapter**
   - implement guarded `g.json` + versioned `gN.json` parsing/merge, page fallback scan, version-aware cache, refresh, and detail fallback marked incomplete;
   - add all six static contract scenarios, MCP/API projection, fixture Compose smoke, and honest live status.

3. **Single Workspace LangGraph runtime**
   - move start/confirm/evidence/curation/access/facts/RAG/planning/validation/review/presentation into one workspace graph;
   - persist checkpoints and pending interrupts; make legacy workflow a thin compatibility adapter;
   - execute Requirement, Reviewer, and bounded Replanner through strict schemas with explainable LLM-unavailable degradation.

4. **Patch, clearing, restore, and deletion semantics**
   - implement clear schedule/day, remove visit, include/exclude, undo/restore/delete itinerary, archive/delete workspace, inverse/snapshot metadata, and impact-directed graph routing;
   - transactionally delete trip data, audit rows, associations, BM25/dense visibility, and checkpoints without deleting user-global knowledge.

5. **Travel providers and facts**
   - add SearchAPI transit and Google Maps/place providers plus fixtures/contracts/MCP tools;
   - integrate existing flights, ORS, and Open-Meteo as TTL-bound provider snapshots used by planner/validator, with live tests reported independently.

6. **Curation, clustering, planner, and validator corrections**
   - remove source-label identity merging, add spatial candidate indexing and ambiguity handling;
   - fix DBSCAN border semantics and feed ORS/transit corrections;
   - replace one-area/day selection with a time-dependent multi-area graph, materially different strategies, and expanded deterministic constraints.

7. **Context, RAG, and product workspace**
   - add traceable conversation summaries that preserve confirmations/hard constraints, graph-integrated knowledge retrieval/rule closure, and audit separation;
   - inject development session identity, remove hard-coded travel defaults, expose condition cards/confirmations/source freshness/clear-undo-restore-delete controls, and keep responsive behavior.

8. **Final acceptance and truthfulness**
   - run focused unit/API/Web/E2E/Compose acceptance after every independent item;
   - run all historical gates plus new authoritative scenarios;
   - classify live external checks as PASS, FAIL, or UNVERIFIED and update capability/limitation documents to match the actual path.
