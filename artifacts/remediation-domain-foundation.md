# Remediation domain and migration foundation

- Status: `PASS` for schema/migration foundation; product scenarios B–J remain independently gated
- Parent commit: `6a056ca`
- Evidence state: worktree before the focused domain-foundation commit
- Data mode: `not_applicable` (no external Provider calls)

## Implemented product boundaries

- `TripRequest.subject_intents` supports one to three ordered/priority intents with exactly one
  primary intent; legacy `anime_query` maps to one stable primary intent.
- `SceneEvidence` is distinct from `VisitPlace`; invalid evidence is quarantined and every evidence
  record must be linked or quarantined exactly once.
- Shared places carry multiple `SubjectAppearance` records but have one visit identity.
- `AreaCluster`, `TripCandidateGraph` and `ItineraryVersion` are versioned sources of truth; an
  itinerary rejects duplicate scheduling of a shared place.
- One discriminated `PlanPatch` family covers requirements, subjects, places, access/base/strategy,
  branches, knowledge and merge decisions.
- `AgentHandoff`, role context, impact/diff and derived-rule schemas reject unknown boundary fields.
- Active knowledge constraints require authority level at least four and no unresolved conflicts.

## Persistence and compatibility

- Added Alembic revision `0004` without rewriting `0001`–`0003`.
- Added normalized tables for subjects/intents, evidence, places and links, appearances, overrides,
  areas and members, candidate graphs, itinerary versions, patches, handoffs and derived rules.
- Existing `trips.state`, Route A/Route B objects and endpoints remain readable as compatibility
  surfaces; migration to the new source of truth is not yet claimed complete.

## Evidence

| Check | Status |
|---|---|
| Strict domain and invariant tests | PASS |
| Legacy single-query adapter stability | PASS |
| Existing database `0003 → 0004` | PASS |
| Empty database `0001 → 0004` | PASS |
| Required new tables present | PASS |
| Full lint and strict typecheck | PASS |
| Full local regression | PASS: 95 Python + 5 Web tests |
| Python aggregate coverage | PASS: 81.60% |

## Scenario interpretation

- B multi-subject confirmation: `PARTIAL` — domain and compatibility input exist; Agent/UI flow is next.
- C scene-to-place: `PARTIAL` — invariants and storage exist; resolution algorithm is next.
- J legacy/migration: `PASS` for request adapter and empty/existing database migration; Route adapters
  remain the existing compatibility implementation and need explicit removal conditions later.
