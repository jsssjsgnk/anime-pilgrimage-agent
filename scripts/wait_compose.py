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
    last_reported: dict[str, str] = {}
    last_heartbeat = 0.0
    while time.monotonic() < deadline:
        last = {service: health(service) for service in SERVICES}
        if all(value == "healthy" for value in last.values()):
            print(
                "Compose health passed: " + ", ".join(f"{k}=healthy" for k in SERVICES),
                flush=True,
            )
            return 0
        now = time.monotonic()
        if last != last_reported or now - last_heartbeat >= 10:
            remaining = max(0, int(deadline - now))
            status = ", ".join(f"{key}={value}" for key, value in last.items())
            print(f"Waiting for Compose ({remaining}s remaining): {status}", flush=True)
            last_reported = last.copy()
            last_heartbeat = now
        time.sleep(2)
    print(
        "Compose health timed out: " + ", ".join(f"{k}={v}" for k, v in last.items()),
        flush=True,
    )
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
