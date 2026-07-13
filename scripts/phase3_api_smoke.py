"""Full-stack Phase 3 planning smoke with deterministic membership and URL checks."""

from __future__ import annotations

import json
import urllib.request
from datetime import date
from typing import Any
from urllib.parse import parse_qs, urlparse


def request_json(url: str, *, payload: dict[str, Any] | None = None) -> dict[str, Any]:
    body = json.dumps(payload).encode() if payload is not None else None
    request = urllib.request.Request(
        url,
        data=body,
        method="POST" if body else "GET",
        headers={"Content-Type": "application/json"} if body else {},
    )
    with urllib.request.urlopen(request, timeout=10) as response:
        result = json.loads(response.read())
    if not isinstance(result, dict):
        raise RuntimeError("planning API response must be an object")
    return result


def main() -> int:
    options = request_json("http://127.0.0.1:8000/api/planning/options")
    start = date.fromisoformat(str(options["start_date"]))
    end = date.fromisoformat(str(options["end_date"]))
    if start <= date.today() or (end - start).days != 2:
        raise RuntimeError("Phase 3 scenario dates are not a relative future three-day window")
    plan = request_json(
        "http://127.0.0.1:8000/api/subjects/328609/route-b",
        payload={
            "inbound_option_id": "train-kyoto-tokyo-early",
            "outbound_option_id": "train-tokyo-kyoto-evening",
            "base_id": "shimokitazawa",
            "max_walking_meters_per_day": 5000,
            "must_visit_point_ids": [],
            "excluded_point_ids": [],
        },
    )
    route_a = request_json("http://127.0.0.1:8000/api/subjects/328609/route-a")
    route_a_ids = {point["id"] for point in route_a["points"]}
    scheduled = {
        visit["point_id"]
        for day in plan["days"]
        for visit in day["visits"]
    }
    omitted = set(plan["omitted_reasons"])
    if not scheduled <= route_a_ids or scheduled | omitted != route_a_ids:
        raise RuntimeError("Route B membership or omission coverage is invalid")
    if len(scheduled) != 3 or plan["matrix_status"] != "road":
        raise RuntimeError("expected the fixture road matrix to schedule all three points")
    for day in plan["days"]:
        if day["walking_distance_meters"] > 5000:
            raise RuntimeError("daily walking constraint was exceeded")
        for url in day["maps_urls"]:
            if len(url) > 2048 or parse_qs(urlparse(url).query).get("api") != ["1"]:
                raise RuntimeError("Google Maps URL is unbounded or lacks api=1")
    print("Kyoto-to-Tokyo three-day Route B smoke passed with subset and URL invariants")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
