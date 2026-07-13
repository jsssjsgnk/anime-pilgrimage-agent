# Reproducible demo

## Preconditions

1. Activate only the Conda environment `anime-pilgrimage-agent`.
2. Run `make bootstrap` and `make compose-up`.
3. Confirm `python scripts/wait_compose.py` reports four healthy services.
4. Do not enter personal data. The default fixture request and all external actions are read-only.

For clean acceptance, the Phase 6 gate removes only this Compose project's named volumes, rebuilds the stack, applies migrations, and seeds the fixed RAG corpus.

## Walkthrough

1. Open `http://localhost:4173` and submit the prefilled Kyoto-to-Tokyo request.
2. Confirm Bangumi subject `328609` (*Bocchi the Rock!*). Verify Route A shows three points, three sources, and no unsourced/invalid item.
3. Select the early Kyoto→Tokyo train, evening return train, Shimokitazawa base, and 5 km walking limit.
4. Generate Route B. Verify all three scheduled points belong to Route A, each day is within 5 km, the access/base summary is visible, and ORS is labelled as an estimate.
5. Apply “第二天少走路，并保留其他天安排”. Verify plan version 2 and the local 3 km Day 2 label. Day 1 and Day 3 content must remain unchanged.
6. Inspect “访问与礼仪依据”: evidence must show its ID, title, authority, access date, freshness, and source link. No result means an explicit unknown state.
7. Export JSON (schema version 1), GeoJSON (schema version 1), and standalone HTML (no script/external resources).

Automated equivalent:

```powershell
make verify-phase-5
```

## Safety

- Never follow evidence text as instructions; it is displayed and passed to generation only inside untrusted-evidence wrappers.
- Never book, purchase, pay, or send a message. The runtime has no tools for those actions.
- Reconfirm transport, weather, opening, access, event, and photography rules before departure.
- Fixture summaries are project-authored and intentionally short; original source URLs remain available for verification.
