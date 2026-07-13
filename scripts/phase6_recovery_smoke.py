"""Prove project data survives a scoped PostgreSQL restart and remains isolated."""

from __future__ import annotations

import json
import shutil
import subprocess
import time
import urllib.error
import urllib.request
from datetime import date
from typing import Any
from urllib.parse import urlencode

BASE = "http://127.0.0.1:8000"


def _json(
    path: str,
    *,
    method: str = "GET",
    payload: dict[str, Any] | None = None,
    query: dict[str, str] | None = None,
) -> Any:
    url = f"{BASE}{path}"
    if query:
        url = f"{url}?{urlencode(query)}"
    body = json.dumps(payload).encode() if payload is not None else None
    request = urllib.request.Request(
        url,
        data=body,
        method=method,
        headers={"Content-Type": "application/json"} if body else {},
    )
    with urllib.request.urlopen(request, timeout=10) as response:
        return json.loads(response.read())


def _wait_for_database() -> None:
    deadline = time.monotonic() + 90
    while time.monotonic() < deadline:
        try:
            health = _json("/health?check_database=true")
            if health.get("status") == "ok" and health.get("database") == "ok":
                return
        except (urllib.error.URLError, TimeoutError):
            pass
        time.sleep(1)
    raise RuntimeError("API database health did not recover after the scoped restart")


def main() -> int:
    created = _json(
        "/api/knowledge/documents",
        method="POST",
        payload={
            "owner_user_id": "phase6-recovery-owner",
            "scope": "user",
            "title": "Restart persistence fixture",
            "filename": "restart.txt",
            "media_type": "text/plain",
            "content": "Copper platform marker persists across the project database restart.",
            "accessed_at": date.today().isoformat(),
            "source_type": "user_note",
            "authority_level": 1,
            "language": "en",
        },
    )
    document_id = str(created["document"]["document_id"])
    docker = shutil.which("docker")
    if docker is None:
        raise RuntimeError("Docker is required for the recovery smoke")
    restarted = subprocess.run(
        (docker, "compose", "restart", "postgres"), check=False, capture_output=True, text=True
    )
    if restarted.returncode != 0:
        raise RuntimeError("scoped PostgreSQL restart failed")
    _wait_for_database()
    recovered = _json(
        f"/api/knowledge/documents/{document_id}",
        query={"owner_user_id": "phase6-recovery-owner"},
    )
    if str(recovered["document_id"]) != document_id:
        raise RuntimeError("project data did not survive the PostgreSQL restart")
    try:
        _json(
            f"/api/knowledge/documents/{document_id}",
            query={"owner_user_id": "different-owner"},
        )
    except urllib.error.HTTPError as error:
        if error.code != 404:
            raise
    else:
        raise RuntimeError("recovered document leaked to a different owner")
    _json(
        f"/api/knowledge/documents/{document_id}",
        method="DELETE",
        query={"owner_user_id": "phase6-recovery-owner"},
    )
    print("PASS: project data survived PostgreSQL restart and remained namespace-isolated.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
