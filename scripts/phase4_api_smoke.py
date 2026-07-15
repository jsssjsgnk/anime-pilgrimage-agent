"""Prove PostgreSQL checkpoint recovery across an API process restart."""

from __future__ import annotations

import shutil
import subprocess
import time
from datetime import date, timedelta
from uuid import uuid4

import httpx

BASE_URL = "http://127.0.0.1:8000"


def wait_for_api() -> None:
    for _attempt in range(40):
        try:
            if httpx.get(f"{BASE_URL}/health", timeout=2).status_code == 200:
                return
        except httpx.HTTPError:
            pass
        time.sleep(0.5)
    raise RuntimeError("API did not recover after its scoped restart")


def resume(
    client: httpx.Client,
    trip_id: str,
    kind: str,
    *,
    decision_fields: dict[str, object] | None = None,
) -> dict[str, object]:
    decision: dict[str, object] = {"decision": "accept"}
    decision.update(decision_fields or {})
    response = client.post(
        f"/api/workflows/{trip_id}/resume",
        json={
            "owner_user_id": "phase4-smoke-user",
            "thread_id": "phase4-restart-thread",
            "decision": decision,
        },
    )
    response.raise_for_status()
    payload = response.json()
    pending = payload.get("pending_confirmation")
    pending_kind = pending.get("kind") if isinstance(pending, dict) else None
    if pending_kind != kind:
        raise RuntimeError(
            f"Expected {kind} confirmation after resume; "
            f"got status={payload.get('status')} phase={payload.get('phase')}"
        )
    return payload


def main() -> int:
    trip_id = str(uuid4())
    start_date = date.today() + timedelta(days=60)
    end_date = start_date + timedelta(days=2)
    with httpx.Client(base_url=BASE_URL, timeout=20) as client:
        started = client.post(
            "/api/workflows",
            json={
                "owner_user_id": "phase4-smoke-user",
                "thread_id": "phase4-restart-thread",
                "trip_id": trip_id,
                "request_summary": (
                    "Three low-walking pilgrimage days from Kyoto to Tokyo for Bocchi the Rock."
                ),
                "requirements": {
                    "origin": "Kyoto",
                    "destination": "Tokyo",
                    "start_date": start_date.isoformat(),
                    "end_date": end_date.isoformat(),
                    "anime_query": "孤独摇滚!",
                    "budget_level": "medium",
                    "walking_preference": "low",
                    "max_walking_meters_per_day": 5_000,
                },
            },
        )
        started.raise_for_status()
        payload = started.json()
        assert payload["status"] == "waiting_confirmation"
        assert payload["pending_confirmation"]["kind"] == "requirements"

        leaked = client.get(
            f"/api/workflows/{trip_id}",
            params={"owner_user_id": "another-user", "thread_id": "phase4-restart-thread"},
        )
        assert leaked.status_code == 404
        resume(client, trip_id, "subject")

    docker = shutil.which("docker")
    if docker is None:
        raise RuntimeError("Docker is unavailable")
    restarted = subprocess.run(
        (docker, "compose", "restart", "api"),
        check=False,
        capture_output=True,
        text=True,
    )
    if restarted.returncode != 0:
        raise RuntimeError("Scoped API restart failed")
    wait_for_api()

    with httpx.Client(base_url=BASE_URL, timeout=20) as client:
        recovered = client.get(
            f"/api/workflows/{trip_id}",
            params={
                "owner_user_id": "phase4-smoke-user",
                "thread_id": "phase4-restart-thread",
            },
        )
        recovered.raise_for_status()
        recovered_pending = recovered.json().get("pending_confirmation")
        assert isinstance(recovered_pending, dict)
        assert recovered_pending["kind"] == "subject"
        resume(
            client,
            trip_id,
            "access_and_base",
            decision_fields={"selected_subject_id": "328609"},
        )
        completed = client.post(
            f"/api/workflows/{trip_id}/resume",
            json={
                "owner_user_id": "phase4-smoke-user",
                "thread_id": "phase4-restart-thread",
                "decision": {
                    "decision": "accept",
                    "inbound_option_id": "manual-inbound",
                    "outbound_option_id": "manual-outbound",
                    "base_id": "route-centroid",
                },
            },
        )
        completed.raise_for_status()
        final = completed.json()
        assert final["status"] == "complete"
        assert final["phase"] == "present"

    print("PASS: workflow resumed from PostgreSQL after API restart and stayed namespace-safe.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
