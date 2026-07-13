"""Prove PostgreSQL checkpoint recovery across an API process restart."""

from __future__ import annotations

import shutil
import subprocess
import time
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


def resume(client: httpx.Client, trip_id: str, kind: str) -> dict[str, object]:
    response = client.post(
        f"/api/workflows/{trip_id}/resume",
        json={
            "owner_user_id": "phase4-smoke-user",
            "thread_id": "phase4-restart-thread",
            "decision": {"decision": "accept"},
        },
    )
    response.raise_for_status()
    payload = response.json()
    if payload.get("pending_confirmation", {}).get("kind") != kind:
        raise RuntimeError(f"Expected {kind} confirmation after resume")
    return payload


def main() -> int:
    trip_id = str(uuid4())
    with httpx.Client(base_url=BASE_URL, timeout=20) as client:
        started = client.post(
            "/api/workflows",
            json={
                "owner_user_id": "phase4-smoke-user",
                "thread_id": "phase4-restart-thread",
                "trip_id": trip_id,
                "request_summary": "Three low-walking pilgrimage days from Kyoto to Tokyo.",
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
        assert recovered.json()["pending_confirmation"]["kind"] == "subject"
        resume(client, trip_id, "access_and_base")
        completed = client.post(
            f"/api/workflows/{trip_id}/resume",
            json={
                "owner_user_id": "phase4-smoke-user",
                "thread_id": "phase4-restart-thread",
                "decision": {"decision": "accept"},
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
