"""Run local API, MCP, and Web processes while Docker supplies PostgreSQL."""

from __future__ import annotations

import os
import signal
import subprocess
from pathlib import Path


def main() -> int:
    env = os.environ.copy()
    env.setdefault(
        "DATABASE_URL",
        "postgresql+asyncpg://pilgrimage:pilgrimage@localhost:5432/pilgrimage",
    )
    commands = [
        ["uv", "run", "uvicorn", "pilgrimage_agent.api.main:app", "--reload"],
        ["uv", "run", "python", "-m", "pilgrimage_agent.mcp.server"],
        ["pnpm", "--filter", "@pilgrimage/web", "dev"],
    ]
    processes = [subprocess.Popen(command, env=env, cwd=Path.cwd()) for command in commands]
    try:
        while all(process.poll() is None for process in processes):
            processes[0].wait(timeout=1)
    except (KeyboardInterrupt, subprocess.TimeoutExpired):
        pass
    finally:
        for process in processes:
            if process.poll() is None:
                process.send_signal(signal.SIGTERM)
        for process in processes:
            try:
                process.wait(timeout=8)
            except subprocess.TimeoutExpired:
                process.kill()
    return 0 if all(process.returncode in {0, -15, None} for process in processes) else 1


if __name__ == "__main__":
    raise SystemExit(main())
