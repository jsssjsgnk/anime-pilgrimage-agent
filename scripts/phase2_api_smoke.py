"""Verify the explicit subject confirmation and sourced Route A HTTP flow."""

from __future__ import annotations

import json
import urllib.request
from typing import Any


def read_json(url: str, *, method: str = "GET") -> dict[str, Any]:
    request = urllib.request.Request(url, method=method)
    with urllib.request.urlopen(request, timeout=10) as response:
        payload = json.loads(response.read())
    if not isinstance(payload, dict):
        raise RuntimeError("API response must be an object")
    return payload


def main() -> int:
    search = read_json(
        "http://127.0.0.1:8000/api/subjects/search?query=%E5%AD%A4%E7%8B%AC%E6%91%87%E6%BB%9A&limit=5"
    )
    candidates = search.get("candidates")
    if not isinstance(candidates, list) or not candidates:
        raise RuntimeError("subject search returned no fixture candidate")
    subject_id = candidates[0].get("subject_id")
    if subject_id != "328609":
        raise RuntimeError("fixture subject identifier changed unexpectedly")
    confirmed = read_json(
        f"http://127.0.0.1:8000/api/subjects/{subject_id}/confirm",
        method="POST",
    )
    if confirmed.get("subject_id") != subject_id:
        raise RuntimeError("explicit confirmation did not preserve the selected identifier")
    route = read_json(f"http://127.0.0.1:8000/api/subjects/{subject_id}/route-a")
    points = route.get("points")
    if not isinstance(points, list) or not points:
        raise RuntimeError("Route A returned no points")
    if len(points) < 400:
        raise RuntimeError(
            "Route A did not use the complete static Anitabi collection "
            f"({len(points)} points)"
        )
    scene_ids: set[str] = set()
    for point in points:
        source = point.get("provenance", {}).get("source_url")
        latitude = point.get("latitude")
        longitude = point.get("longitude")
        if not source:
            raise RuntimeError("Route A contains a point without a source")
        if not isinstance(latitude, int | float) or not -90 <= latitude <= 90:
            raise RuntimeError("Route A contains an invalid latitude")
        if not isinstance(longitude, int | float) or not -180 <= longitude <= 180:
            raise RuntimeError("Route A contains an invalid longitude")
        scene_id = point.get("id")
        if not isinstance(scene_id, str) or not scene_id:
            raise RuntimeError("Route A contains a point without a stable scene ID")
        if scene_id in scene_ids:
            raise RuntimeError("Route A contains an exact duplicate scene ID")
        scene_ids.add(scene_id)
    print(f"Subject confirmation and Route A smoke passed with {len(points)} sourced points")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
