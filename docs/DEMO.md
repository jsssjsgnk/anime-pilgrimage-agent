# Reproducible demo

## Preconditions

1. Activate only the Conda environment `anime-pilgrimage-agent`.
2. Run `make bootstrap` and `make compose-up`.
3. Confirm `python scripts/wait_compose.py` reports four healthy services.
4. Do not enter personal data. The default fixture request and all external actions are read-only.

For clean acceptance, the Phase 6 gate removes only this Compose project's named volumes, rebuilds the stack, applies migrations, and seeds the fixed RAG corpus.

## Walkthrough

1. Open `http://localhost:4173` and submit the prefilled Kyoto-to-Tokyo request.
2. Confirm Bangumi subject `328609` (*Bocchi the Rock!*). Verify Route A shows the current 74 sourced Anitabi detail records and explicitly reports the unavailable remainder rather than claiming all 414 advertised map points are present.
3. Select the manual Kyoto-to-Tokyo and return candidates, the Route A-derived base, and the 5 km walking limit. With confirmed IATA codes, flight snapshots appear alongside manual choices with comparison labels.
4. Generate Route B. Verify every scheduled point belongs to Route A, each day is within 5 km, the access/base summary is visible, and ORS or its labelled Haversine fallback is shown.
5. In “和规划 Agent 继续聊”, ask “为什么这样安排？” and “点位数据完整吗？”. Verify the answers remain grounded in the current workflow and disclose unknown/partial state.
6. Send “第二天少走 30%，并保留其他天安排” in that conversation. Verify plan version 2, Day 2 walking is at most 70% of its prior value, and Day 1/Day 3 content remains unchanged.
7. Refresh the browser. Verify the same trip, transcript, typed modification badge, and plan version recover from the namespace-scoped API.
8. Inspect “访问与礼仪依据”: evidence must show its ID, title, authority, access date, freshness, and source link. No result means an explicit unknown state.
9. Export JSON (schema version 1), GeoJSON (schema version 1), and standalone HTML (no script/external resources).

Automated equivalent:

```powershell
make verify-phase-5
```

## Safety

- Never follow evidence text as instructions; it is displayed and passed to generation only inside untrusted-evidence wrappers.
- Never book, purchase, pay, or send a message. The runtime has no tools for those actions.
- Reconfirm transport, weather, opening, access, event, and photography rules before departure.
- Fixture summaries are project-authored and intentionally short; original source URLs remain available for verification.
