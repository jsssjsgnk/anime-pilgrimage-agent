"""Wait until this project's four Compose services report healthy."""

from __future__ import annotations

import subprocess
import time

SERVICES = ("postgres", "api", "mcp-tools", "web")


def health(service: str) -> str:
    container = subprocess.run(
        ["docker", "compose", "ps", "-q", service],
        capture_output=True,
        text=True,
        check=False,
    ).stdout.strip()
    if not container:
        return "missing"
    return subprocess.run(
        ["docker", "inspect", "--format", "{{.State.Health.Status}}", container],
        capture_output=True,
        text=True,
        check=False,
    ).stdout.strip()


def main() -> int:
    deadline = time.monotonic() + 180
    last: dict[str, str] = {}
    while time.monotonic() < deadline:
        last = {service: health(service) for service in SERVICES}
        if all(value == "healthy" for value in last.values()):
            print("Compose health passed: " + ", ".join(f"{k}=healthy" for k in SERVICES))
            return 0
        time.sleep(2)
    print("Compose health timed out: " + ", ".join(f"{k}={v}" for k, v in last.items()))
    return 1


if __name__ == "__main__":
    raise SystemExit(main())

