# Reproducible demo

## Preconditions

1. Activate only the Conda environment `anime-pilgrimage-agent`.
2. Run `make bootstrap` and `make compose-up`.
3. Confirm `python scripts/wait_compose.py` reports four healthy services.
4. Do not enter personal data. The default fixture request and all external actions are read-only.

For clean acceptance, the Phase 6 gate removes only this Compose project's named volumes, rebuilds the stack, applies migrations, and seeds the fixed RAG corpus.

## Walkthrough

1. Open `http://localhost:4173`. In “你的巡礼想法”, describe multiple works and the trip pace naturally, then select the dates and start planning.
2. Confirm the matched works once. The interface must not show catalog/provider names, workspace IDs, raw states, role handoffs, or patch internals.
3. Verify the compact map shows the sourced places. Click a point and inspect the work, episode/time reference, scene image when available, and its source link.
4. Choose “批量选择”. Tick three or more places from the scrollable list (or use “全选当前列表”), then preview one combined add, exclude, or move-to-day change.
5. Generate the multi-day itinerary. Verify the map defaults to scheduled places and each day shows its ordered visits and walking distance.
6. Return to the same conversation and send “我想每天少走一点”. Confirm the human-readable change preview, apply it, and verify a new itinerary version appears.
7. Refresh the browser. Verify the original request, subsequent conversation, selected plan, and pending preview (if any) recover without exposing internal diagnostics.
8. Repeat the workflow in a mobile viewport; the title confirmation automatically opens the map panel, the map remains compact, and batch selection does not depend on tapping overlapping markers.

Automated equivalent:

```powershell
make verify-phase-5
```

## Safety

- Never follow evidence text as instructions; it is displayed and passed to generation only inside untrusted-evidence wrappers.
- Never book, purchase, pay, or send a message. The runtime has no tools for those actions.
- Reconfirm transport, weather, opening, access, event, and photography rules before departure.
- Fixture summaries are project-authored and intentionally short; original source URLs remain available for verification.
