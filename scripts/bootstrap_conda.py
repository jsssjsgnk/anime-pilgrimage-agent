"""Create or update only the project-owned Conda environment."""

from __future__ import annotations

import json
import subprocess
from pathlib import Path

ENV_NAME = "anime-pilgrimage-agent"


def main() -> int:
    if not Path("environment.yml").is_file():
        print("environment.yml is missing")
        return 1
    info = subprocess.run(
        ["conda", "env", "list", "--json"], capture_output=True, text=True, check=True
    )
    prefixes = json.loads(info.stdout).get("envs", [])
    exists = any(Path(prefix).name == ENV_NAME for prefix in prefixes)
    command = ["conda", "env", "update" if exists else "create", "--solver", "rattler"]
    if exists:
        command.extend(["-n", ENV_NAME, "-f", "environment.yml", "--prune"])
    else:
        command.extend(["-f", "environment.yml", "-y"])
    print(f"{'Updating' if exists else 'Creating'} dedicated environment {ENV_NAME}")
    return subprocess.run(command, check=False).returncode


if __name__ == "__main__":
    raise SystemExit(main())

