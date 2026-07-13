"""Read-only HTTP health smoke for the Compose stack."""

from __future__ import annotations

import json
import urllib.request


def read_json(url: str) -> dict[str, object]:
    with urllib.request.urlopen(url, timeout=5) as response:
        return json.loads(response.read().decode("utf-8"))


def main() -> int:
    health = read_json("http://127.0.0.1:8000/health?check_database=true")
    capabilities = read_json("http://127.0.0.1:8000/api/capabilities")
    with urllib.request.urlopen("http://127.0.0.1:4173/health", timeout=5) as response:
        web_ok = response.status == 200
    if health.get("status") != "ok" or health.get("database") != "ok":
        raise RuntimeError("API/database health did not report ok")
    if not isinstance(capabilities.get("capabilities"), dict) or not web_ok:
        raise RuntimeError("Capability or Web health contract failed")
    print("API/database/Web smoke passed; capability values were not emitted")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

