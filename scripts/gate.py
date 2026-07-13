"""Run phase gates and always write a concise, value-redacted Markdown report."""

from __future__ import annotations

import os
import shutil
import subprocess
import sys
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
ARTIFACTS = ROOT / "artifacts"


@dataclass(frozen=True)
class Check:
    name: str
    command: tuple[str, ...]
    category: str


PHASE_1 = (
    Check(
        "Dedicated environment and lockfiles",
        (sys.executable, "scripts/verify_env.py"),
        "environment",
    ),
    Check("Python lint", ("uv", "run", "ruff", "check", "."), "static"),
    Check("Python strict types", ("uv", "run", "mypy"), "static"),
    Check("Web lint", ("pnpm", "lint"), "static"),
    Check("Web strict types", ("pnpm", "typecheck"), "static"),
    Check(
        "Python unit and contract tests",
        (
            "uv",
            "run",
            "pytest",
            "tests/unit",
            "tests/contract",
            "--cov=pilgrimage_agent",
            "--cov-report=term-missing",
        ),
        "fixture",
    ),
    Check("Web unit tests", ("pnpm", "test"), "fixture"),
    Check("Repository secret scan", (sys.executable, "scripts/check_secrets.py"), "security"),
    Check("Compose schema", ("docker", "compose", "config", "--quiet"), "compose"),
    Check("Build and start full stack", ("docker", "compose", "up", "-d", "--build"), "compose"),
    Check("Four-service health", (sys.executable, "scripts/wait_compose.py"), "compose"),
    Check(
        "Idempotent migration run 1",
        ("docker", "compose", "exec", "-T", "api", "alembic", "upgrade", "head"),
        "integration",
    ),
    Check(
        "Idempotent migration run 2",
        ("docker", "compose", "exec", "-T", "api", "alembic", "upgrade", "head"),
        "integration",
    ),
    Check("API and database health", (sys.executable, "scripts/http_smoke.py"), "integration"),
    Check(
        "MCP initialize and tools/list",
        ("docker", "compose", "exec", "-T", "api", "python", "-m", "pilgrimage_agent.smoke.mcp", "http://mcp-tools:8001/mcp"),
        "integration",
    ),
    Check("Desktop/mobile browser shell", ("pnpm", "test:e2e"), "e2e"),
)


def redact(text: str) -> str:
    """Remove likely credential-bearing lines before report/log output."""

    sensitive = ("authorization", "cookie", "api_key", "access_token", "signed")
    lines = []
    for line in text.splitlines():
        if any(token in line.lower() for token in sensitive):
            lines.append("[redacted sensitive line]")
        else:
            lines.append(line)
    return "\n".join(lines)


def resolve_command(command: tuple[str, ...]) -> tuple[str, ...]:
    """Resolve Windows `.cmd` shims and normal executables without invoking a shell."""

    executable = command[0]
    if Path(executable).is_absolute():
        return command
    resolved = shutil.which(executable)
    if resolved is None:
        raise FileNotFoundError(f"Required executable is unavailable: {executable}")
    return (resolved, *command[1:])


def run_phase(phase: int) -> bool:
    if phase != 1:
        ARTIFACTS.mkdir(parents=True, exist_ok=True)
        path = ARTIFACTS / f"phase-{phase}-report.md"
        path.write_text(
            f"# Phase {phase} verification\n\nStatus: **not implemented**\n",
            encoding="utf-8",
        )
        print(f"Phase {phase} is not implemented yet; report: {path}")
        return False

    results: list[tuple[Check, int, str]] = []
    command_env = os.environ.copy()
    command_env["COMPOSE_BAKE"] = "false"
    for check in PHASE_1:
        print(f"\n=== {check.name} ===", flush=True)
        try:
            completed = subprocess.run(
                resolve_command(check.command),
                cwd=ROOT,
                env=command_env,
                capture_output=True,
                text=True,
                check=False,
            )
            code = completed.returncode
            output = redact((completed.stdout + "\n" + completed.stderr).strip())
        except OSError as error:
            code = 127
            output = redact(str(error))
        print(output[-4000:] if output else "(no output)")
        results.append((check, code, output))
        if code != 0:
            break

    ARTIFACTS.mkdir(parents=True, exist_ok=True)
    report = ARTIFACTS / "phase-1-report.md"
    lines = [
        "# Phase 1 verification",
        "",
        f"Generated: {datetime.now(UTC).isoformat()}",
        "",
        "## Summary",
        "",
        "| Check | Category | Result |",
        "|---|---|---|",
    ]
    for check, code, _ in results:
        lines.append(f"| {check.name} | {check.category} | {'PASS' if code == 0 else 'FAIL'} |")
    if len(results) < len(PHASE_1):
        for check in PHASE_1[len(results) :]:
            lines.append(f"| {check.name} | {check.category} | NOT RUN |")
    lines.extend(["", "## Failure details", ""])
    failures = [(check, output) for check, code, output in results if code != 0]
    if failures:
        for check, output in failures:
            lines.extend([f"### {check.name}", "", "```text", output[-6000:], "```", ""])
    else:
        lines.append("None.")
    lines.extend(
        [
            "",
            "## Evidence separation",
            "",
            "- Fixture/unit evidence: Python and Web unit/contract checks above.",
            "- Browser E2E evidence: Playwright report and desktop/mobile screenshots "
            "under `artifacts/`.",
            "- Live external API evidence: not part of Phase 1; no live calls were made.",
        ]
    )
    report.write_text("\n".join(lines) + "\n", encoding="utf-8")
    passed = len(results) == len(PHASE_1) and not failures
    print(f"\nPhase 1 {'passed' if passed else 'failed'}; report: {report}")
    return passed


def main() -> int:
    requested = sys.argv[1] if len(sys.argv) > 1 else "all"
    if requested == "all":
        phases = range(1, 7)
    else:
        try:
            phases = (int(requested),)
        except ValueError:
            print("Usage: gate.py {1|2|3|4|5|6|all}")
            return 2
    for phase in phases:
        if not run_phase(phase):
            return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
