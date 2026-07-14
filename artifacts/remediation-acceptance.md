# Remediation Acceptance A-J

Overall: **PASS**

| Scenario | Capability | Status | Evidence mode |
|---|---|---|---|
| A | truthful runtime | PASS | fixture + live diagnostics |
| B | multi-subject evidence | PASS | unit/API + live Anitabi browser |
| C | scene-to-place resolution | PASS | deterministic unit/API |
| D | real area clustering | PASS | Haversine DBSCAN unit/API |
| E | hierarchical alternatives | PASS | deterministic unit/API |
| F | PlanPatch and recovery | PASS | API/Web/browser |
| G | violation-specific replanning | PASS | six-fixture unit gate |
| H | production RAG loop | PASS | SQL + real E5 Compose smoke |
| I | mixed-initiative workspace | PASS | desktop/mobile browser |
| J | legacy migration | PASS | unit + Alembic |

## Executed checks

- PASS: truthful provider runtime — Compose diagnostics: Anitabi live; other configured providers fixture.
- PASS: remediation domain and behavior suite — Typed domain, API, clustering, planning, patch, replanner, RAG-rule tests.
- PASS: real desktop and mobile workspace evidence — Browser path captured at 1440x900 and 375x812 with no horizontal overflow.
- PASS: normalized PostgreSQL workspace projection — Real PostgreSQL projection rows are inserted, verified, and cleaned.
- PASS: SQL real-E5 RAG production loop — Real E5 + pgvector conflict, isolation, deletion refresh, injection safety.
- PASS: Alembic remediation head — Running Compose database reports the additive remediation migration head.
- PASS: mixed-workspace Web tests — Workspace start, confirmation, planning, patch, pending recovery and legacy tests.

## Honest limitations

- SearchAPI live quota was not exercised; its external proof remains UNVERIFIED.
- Area travel-time correction is estimated/Haversine when ORS is unavailable.
- Local owner identity is request-scoped; production authentication remains a deployment concern.
