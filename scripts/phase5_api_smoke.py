"""Full-stack RAG API isolation, dedupe, evaluation, and deletion smoke."""

from __future__ import annotations

import json
import urllib.error
import urllib.request
from datetime import date
from typing import Any
from urllib.parse import urlencode

BASE = "http://127.0.0.1:8000/api/knowledge"


def request_json(
    path: str,
    *,
    method: str = "GET",
    payload: dict[str, Any] | None = None,
    query: dict[str, str] | None = None,
    expected_status: int = 200,
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
    try:
        with urllib.request.urlopen(request, timeout=20) as response:
            if response.status != expected_status:
                raise RuntimeError(f"unexpected knowledge API status {response.status}")
            return json.loads(response.read())
    except urllib.error.HTTPError as error:
        if error.code == expected_status:
            return None
        raise RuntimeError(f"unexpected knowledge API status {error.code}") from error


def main() -> int:
    upload = {
        "owner_user_id": "phase5-api-owner",
        "scope": "user",
        "title": "Integration-only station note",
        "filename": "integration.txt",
        "media_type": "text/plain",
        "content": "The phase-five purple lift is beside the integration north gate.",
        "accessed_at": date.today().isoformat(),
        "source_type": "user_note",
        "authority_level": 1,
        "language": "en",
    }
    created = request_json("/documents", method="POST", payload=upload)
    document_id = str(created["document"]["document_id"])
    duplicate = request_json("/documents", method="POST", payload=upload)
    if not duplicate["duplicate"] or str(duplicate["document"]["document_id"]) != document_id:
        raise RuntimeError("knowledge API did not deduplicate a namespace/content hash")
    own = request_json(
        "/search",
        method="POST",
        payload={
            "owner_user_id": "phase5-api-owner",
            "question": "Where is the phase-five purple lift near the integration gate?",
        },
    )
    if document_id not in {str(item["document_id"]) for item in own["evidence"]}:
        raise RuntimeError("owner could not retrieve the uploaded document")
    hidden = request_json(
        "/search",
        method="POST",
        payload={
            "owner_user_id": "different-owner",
            "question": "Where is the phase-five purple lift near the integration gate?",
        },
    )
    if document_id in {str(item["document_id"]) for item in hidden["evidence"]}:
        raise RuntimeError("knowledge search leaked across user namespaces")
    request_json(
        f"/documents/{document_id}",
        query={"owner_user_id": "different-owner"},
        expected_status=404,
    )
    evaluation = request_json("/evaluate", method="POST")
    if not (
        evaluation["recall_at_6"] >= 0.80
        and evaluation["mrr_at_10"] >= 0.70
        and evaluation["citation_precision"] >= 0.90
        and evaluation["namespace_leaks"] == 0
        and evaluation["malicious_tool_calls"] == 0
    ):
        raise RuntimeError("RAG evaluation thresholds were not met through the API")
    request_json(
        f"/documents/{document_id}",
        method="DELETE",
        query={"owner_user_id": "phase5-api-owner"},
    )
    deleted = request_json(
        "/search",
        method="POST",
        payload={
            "owner_user_id": "phase5-api-owner",
            "question": "Where is the phase-five purple lift near the integration gate?",
        },
    )
    if document_id in {str(item["document_id"]) for item in deleted["evidence"]}:
        raise RuntimeError("deleted knowledge remained in retrieval results")
    print("Phase 5 knowledge API smoke passed isolation, dedupe, metrics, and deletion")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
