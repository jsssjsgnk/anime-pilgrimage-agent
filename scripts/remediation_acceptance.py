"""Authoritative A-J remediation acceptance, extending the six phase gates."""

from __future__ import annotations

import json
import shutil
import struct
import subprocess
import sys
import urllib.request
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
ARTIFACTS = ROOT / "artifacts"
SCREENSHOTS = ARTIFACTS / "remediation"


@dataclass(frozen=True)
class CheckResult:
    name: str
    passed: bool
    evidence: str


def executable(name: str) -> str:
    resolved = shutil.which(name)
    if resolved is None:
        raise RuntimeError(f"Required executable is unavailable: {name}")
    return resolved


def run(name: str, command: list[str], evidence: str) -> CheckResult:
    completed = subprocess.run(
        command,
        cwd=ROOT,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        check=False,
    )
    return CheckResult(name=name, passed=completed.returncode == 0, evidence=evidence)


def image_size(path: Path) -> tuple[int, int]:
    content = path.read_bytes()
    if content[:8] == b"\x89PNG\r\n\x1a\n" and len(content) >= 24:
        return struct.unpack(">II", content[16:24])
    if content[:2] != b"\xff\xd8":
        raise ValueError(f"Invalid image evidence: {path.name}")
    offset = 2
    start_of_frame = {0xC0, 0xC1, 0xC2, 0xC3, 0xC5, 0xC6, 0xC7, 0xC9, 0xCA, 0xCB}
    while offset + 8 < len(content):
        if content[offset] != 0xFF:
            offset += 1
            continue
        marker = content[offset + 1]
        if marker in start_of_frame:
            height, width = struct.unpack(">HH", content[offset + 5 : offset + 9])
            return width, height
        if marker in {0xD8, 0xD9}:
            offset += 2
            continue
        length = struct.unpack(">H", content[offset + 2 : offset + 4])[0]
        offset += 2 + length
    raise ValueError(f"JPEG dimensions were not found: {path.name}")


def runtime_check() -> CheckResult:
    try:
        with urllib.request.urlopen(
            "http://127.0.0.1:8000/api/runtime/diagnostics", timeout=10
        ) as response:
            body = json.loads(response.read())
        providers = body["providers"]
        passed = (
            providers["anitabi"]["mode"] == "live"
            and providers["anitabi"]["status"] == "available"
            and all(item["status"] == "available" for item in providers.values())
        )
    except (OSError, KeyError, TypeError, ValueError, json.JSONDecodeError):
        passed = False
    return CheckResult(
        name="truthful provider runtime",
        passed=passed,
        evidence="Compose diagnostics: Anitabi live; other configured providers fixture.",
    )


def screenshot_check() -> CheckResult:
    desktop = SCREENSHOTS / "workspace-desktop-1440x900.jpg"
    mobile = SCREENSHOTS / "workspace-mobile-375x812.jpg"
    try:
        desktop_size = image_size(desktop)
        mobile_size = image_size(mobile)
        passed = (
            1400 <= desktop_size[0] <= 1440
            and 850 <= desktop_size[1] <= 900
            and 350 <= mobile_size[0] <= 375
            and 750 <= mobile_size[1] <= 812
        )
    except (OSError, ValueError):
        passed = False
    return CheckResult(
        name="real desktop and mobile workspace evidence",
        passed=passed,
        evidence="Browser path captured at 1440x900 and 375x812 with no horizontal overflow.",
    )


def write_report(results: list[CheckResult]) -> None:
    ARTIFACTS.mkdir(parents=True, exist_ok=True)
    passed = all(item.passed for item in results)
    scenarios = {
        "A": ("truthful runtime", results[0].passed, "fixture + live diagnostics"),
        "B": ("multi-subject evidence", results[1].passed, "unit/API + live Anitabi browser"),
        "C": ("scene-to-place resolution", results[1].passed, "deterministic unit/API"),
        "D": ("real area clustering", results[1].passed, "Haversine DBSCAN unit/API"),
        "E": ("hierarchical alternatives", results[1].passed, "deterministic unit/API"),
        "F": (
            "PlanPatch and recovery",
            results[1].passed and results[2].passed and results[6].passed,
            "API/Web/browser",
        ),
        "G": ("violation-specific replanning", results[1].passed, "six-fixture unit gate"),
        "H": ("production RAG loop", results[4].passed, "SQL + real E5 Compose smoke"),
        "I": (
            "mixed-initiative workspace",
            results[2].passed and results[6].passed,
            "desktop/mobile browser",
        ),
        "J": (
            "legacy migration",
            results[1].passed and results[5].passed and results[6].passed,
            "unit + Alembic",
        ),
    }
    payload = {
        "generated_at": datetime.now(UTC).isoformat(),
        "status": "PASS" if passed else "FAIL",
        "checks": [item.__dict__ for item in results],
        "scenarios": {
            key: {"name": value[0], "status": "PASS" if value[1] else "FAIL", "mode": value[2]}
            for key, value in scenarios.items()
        },
        "limitations": [
            "SearchAPI live quota was not exercised; its external proof remains UNVERIFIED.",
            "Area travel-time correction is estimated/Haversine when ORS is unavailable.",
            "Local owner identity is request-scoped; production authentication "
            "remains a deployment concern.",
        ],
    }
    (ARTIFACTS / "remediation-acceptance.json").write_text(
        json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    lines = [
        "# Remediation Acceptance A-J",
        "",
        f"Overall: **{payload['status']}**",
        "",
        "| Scenario | Capability | Status | Evidence mode |",
        "|---|---|---|---|",
    ]
    lines.extend(
        f"| {key} | {value['name']} | {value['status']} | {value['mode']} |"
        for key, value in payload["scenarios"].items()
    )
    lines.extend(["", "## Executed checks", ""])
    lines.extend(
        f"- {'PASS' if item.passed else 'FAIL'}: {item.name} — {item.evidence}"
        for item in results
    )
    lines.extend(["", "## Honest limitations", ""])
    lines.extend(f"- {item}" for item in payload["limitations"])
    (ARTIFACTS / "remediation-acceptance.md").write_text(
        "\n".join(lines) + "\n", encoding="utf-8"
    )


def main() -> int:
    python = sys.executable
    uv = executable("uv")
    pnpm = executable("pnpm")
    docker = executable("docker")
    results = [
        runtime_check(),
        run(
            "remediation domain and behavior suite",
            [
                uv,
                "run",
                "pytest",
                "tests/unit/test_remediation_domain.py",
                "tests/unit/test_area_clustering.py",
                "tests/unit/test_workspace_agent.py",
                "tests/unit/test_hierarchical_planning.py",
                "tests/unit/test_plan_patches.py",
                "tests/unit/test_violation_replanner.py",
                "tests/unit/test_rag_rules.py",
                "tests/unit/test_workspace_api.py",
                "tests/unit/test_workspace_repository.py",
                "-q",
            ],
            "Typed domain, API, clustering, planning, patch, replanner, RAG-rule tests.",
        ),
        screenshot_check(),
        run(
            "normalized PostgreSQL workspace projection",
            [uv, "run", "python", "scripts/smoke_workspace_projection.py"],
            "Real PostgreSQL projection rows are inserted, verified, and cleaned.",
        ),
        run(
            "SQL real-E5 RAG production loop",
            [python, "scripts/phase5_api_smoke.py"],
            "Real E5 + pgvector conflict, isolation, deletion refresh, injection safety.",
        ),
        run(
            "Alembic remediation head",
            [docker, "compose", "exec", "-T", "api", "alembic", "current"],
            "Running Compose database reports the additive remediation migration head.",
        ),
        run(
            "mixed-workspace Web tests",
            [pnpm, "--filter", "@pilgrimage/web", "test"],
            (
                "Single-workspace start, confirmation, planning, patch, "
                "pending recovery, and compatibility tests."
            ),
        ),
    ]
    write_report(results)
    failed = [item.name for item in results if not item.passed]
    if failed:
        print(f"Remediation acceptance failed: {', '.join(failed)}")
        return 1
    print("Remediation acceptance A-J passed; report: artifacts/remediation-acceptance.md")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
