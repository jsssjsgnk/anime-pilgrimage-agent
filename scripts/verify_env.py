"""Verify the dedicated Conda/uv environment without exposing configuration values."""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

EXPECTED_ENV = "anime-pilgrimage-agent"


def main() -> int:
    checks: dict[str, bool] = {
        "conda_environment": os.environ.get("CONDA_DEFAULT_ENV") == EXPECTED_ENV,
        "python_3_12": sys.version_info[:2] == (3, 12),
        "uv_available": shutil.which("uv") is not None,
        "make_available": shutil.which("make") is not None,
        "environment_spec": Path("environment.yml").is_file(),
        "uv_lock": Path("uv.lock").is_file(),
        "pnpm_lock": Path("pnpm-lock.yaml").is_file(),
    }
    if checks["uv_available"] and checks["uv_lock"]:
        result = subprocess.run(
            ["uv", "lock", "--check"],
            check=False,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
        checks["uv_lock_current"] = result.returncode == 0
        runtime = subprocess.run(
            [
                "uv",
                "run",
                "python",
                "-c",
                "import sys; raise SystemExit(sys.version_info[:2] != (3, 12))",
            ],
            check=False,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
        checks["uv_runtime_python_3_12"] = runtime.returncode == 0
    else:
        checks["uv_lock_current"] = False
        checks["uv_runtime_python_3_12"] = False

    print(json.dumps(checks, indent=2, sort_keys=True))
    failed = [name for name, passed in checks.items() if not passed]
    if failed:
        print("Environment verification failed: " + ", ".join(failed), file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
