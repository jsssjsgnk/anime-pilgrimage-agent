"""Compose smoke for explicit clear, durable emptiness, and complete trip deletion."""

from __future__ import annotations

from datetime import date, timedelta
from uuid import uuid4

import httpx


def _checked(response: httpx.Response) -> dict[str, object]:
    response.raise_for_status()
    payload = response.json()
    if not isinstance(payload, dict):
        raise RuntimeError("workspace endpoint returned a non-object response")
    return payload


def main() -> int:
    trip_id = str(uuid4())
    owner = f"deletion-smoke-{trip_id[:8]}"
    thread = "compose-deletion"
    start = date.today() + timedelta(days=55)
    request = {
        "owner_user_id": owner,
        "thread_id": thread,
        "trip_id": trip_id,
        "request_summary": "用两天巡礼《孤独摇滚》。",
        "requirements": {
            "origin": "京都",
            "destination": "东京",
            "start_date": start.isoformat(),
            "end_date": (start + timedelta(days=1)).isoformat(),
            "subject_intents": [
                {"query": "孤独摇滚", "priority": 5, "is_primary": True}
            ],
        },
    }
    base_url = "http://127.0.0.1:8000"
    with httpx.Client(base_url=base_url, timeout=120) as client:
        initial = _checked(client.post("/api/workspaces", json=request))
        groups = initial.get("subject_groups")
        if not isinstance(groups, list) or not groups:
            raise RuntimeError("workspace did not return a subject confirmation group")
        group = groups[0]
        if not isinstance(group, dict):
            raise RuntimeError("subject group is invalid")
        candidates = group.get("candidates")
        intent = group.get("intent")
        if not isinstance(candidates, list) or not candidates or not isinstance(intent, dict):
            raise RuntimeError("subject confirmation candidates are unavailable")
        candidate = candidates[0]
        if not isinstance(candidate, dict):
            raise RuntimeError("subject candidate is invalid")
        curated = _checked(
            client.post(
                f"/api/workspaces/{trip_id}/subjects/confirm",
                json={
                    "owner_user_id": owner,
                    "thread_id": thread,
                    "expected_state_version": initial["state_version"],
                    "confirmations": [
                        {
                            "intent_id": intent["intent_id"],
                            "decision": "accept",
                            "selected_subject_id": candidate["subject_id"],
                        }
                    ],
                },
            )
        )
        bases = curated.get("base_candidates")
        if not isinstance(bases, list) or not bases or not isinstance(bases[0], dict):
            raise RuntimeError("workspace did not produce a base candidate")
        planned = _checked(
            client.post(
                f"/api/workspaces/{trip_id}/plan",
                json={
                    "owner_user_id": owner,
                    "thread_id": thread,
                    "expected_state_version": curated["state_version"],
                    "base_id": bases[0]["base_id"],
                },
            )
        )
        cleared = _checked(
            client.post(
                f"/api/workspaces/{trip_id}/schedule/clear",
                json={
                    "owner_user_id": owner,
                    "thread_id": thread,
                    "expected_state_version": planned["state_version"],
                },
            )
        )
        recovered = _checked(
            client.get(
                f"/api/workspaces/{trip_id}",
                params={"owner_user_id": owner, "thread_id": thread},
            )
        )
        if cleared.get("status") != "ready_to_plan" or recovered.get("itineraries") != []:
            raise RuntimeError("cleared workspace was automatically repopulated")
        deleted = _checked(
            client.delete(
                f"/api/workspaces/{trip_id}",
                params={"owner_user_id": owner, "thread_id": thread},
            )
        )
        if deleted.get("deleted") is not True:
            raise RuntimeError("workspace deletion was not acknowledged")
        missing = client.get(
            f"/api/workspaces/{trip_id}",
            params={"owner_user_id": owner, "thread_id": thread},
        )
        if missing.status_code != 404:
            raise RuntimeError("deleted workspace remains readable")
        recreated = _checked(client.post("/api/workspaces", json=request))
        if recreated.get("itineraries") != [] or recreated.get("state_version") != 1:
            raise RuntimeError("deleted graph checkpoint leaked into the recreated workspace")
        client.delete(
            f"/api/workspaces/{trip_id}",
            params={"owner_user_id": owner, "thread_id": thread},
        ).raise_for_status()
    print("PASS: clear remains empty; trip data and graph checkpoint delete together.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
