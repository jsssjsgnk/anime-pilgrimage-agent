"""Run phase gates and always write a concise, value-redacted Markdown report."""

from __future__ import annotations

import json
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
    Check(
        "Desktop/mobile browser shell",
        (
            "pnpm",
            "--filter",
            "@pilgrimage/web",
            "exec",
            "playwright",
            "test",
            "e2e/foundation.spec.ts",
        ),
        "e2e",
    ),
)

PHASE_2 = (
    Check("Python lint", ("uv", "run", "ruff", "check", "."), "static"),
    Check("Python strict types", ("uv", "run", "mypy"), "static"),
    Check("Web lint", ("pnpm", "lint"), "static"),
    Check("Web strict types", ("pnpm", "typecheck"), "static"),
    Check(
        "Provider fixture and failure contracts",
        (
            "uv",
            "run",
            "pytest",
            "tests/contract/test_anitabi_static.py",
            "tests/contract/test_phase2_providers.py",
            "tests/unit",
            "--cov=pilgrimage_agent",
            "--cov-report=term-missing",
        ),
        "fixture",
    ),
    Check("Web unit tests", ("pnpm", "test"), "fixture"),
    Check("Repository secret scan", (sys.executable, "scripts/check_secrets.py"), "security"),
    Check("Build and start full stack", ("docker", "compose", "up", "-d", "--build"), "compose"),
    Check("Four-service health", (sys.executable, "scripts/wait_compose.py"), "compose"),
    Check(
        "MCP initialize, allowlist, and schemas",
        (
            "docker",
            "compose",
            "exec",
            "-T",
            "api",
            "python",
            "-m",
            "pilgrimage_agent.smoke.mcp",
            "http://mcp-tools:8001/mcp",
        ),
        "integration",
    ),
    Check(
        "MCP schema snapshot",
        (
            "docker",
            "compose",
            "exec",
            "-T",
            "api",
            "python",
            "-m",
            "pilgrimage_agent.smoke.mcp",
            "http://mcp-tools:8001/mcp",
            "--snapshot",
        ),
        "integration",
    ),
    Check(
        "Subject confirmation and Route A",
        (sys.executable, "scripts/phase2_api_smoke.py"),
        "integration",
    ),
    Check(
        "Live read-only provider smoke",
        ("uv", "run", "python", "scripts/live_provider_smoke.py"),
        "live",
    ),
    Check(
        "Subject confirmation map E2E",
        (
            "pnpm",
            "--filter",
            "@pilgrimage/web",
            "exec",
            "playwright",
            "test",
            "e2e/foundation.spec.ts",
            "e2e/phase2.spec.ts",
        ),
        "e2e",
    ),
)

PHASE_3 = (
    Check("Python lint", ("uv", "run", "ruff", "check", "."), "static"),
    Check("Python strict types", ("uv", "run", "mypy"), "static"),
    Check("Web lint", ("pnpm", "lint"), "static"),
    Check("Web strict types", ("pnpm", "typecheck"), "static"),
    Check(
        "Route B properties and three-day scenario",
        (
            "uv",
            "run",
            "pytest",
            "tests/unit/test_phase3_planning.py",
            "tests/unit/test_phase3_api.py",
            "tests/contract/test_phase3_scenario.py",
        ),
        "fixture",
    ),
    Check("Web unit tests", ("pnpm", "test"), "fixture"),
    Check("Repository secret scan", (sys.executable, "scripts/check_secrets.py"), "security"),
    Check("Build and start full stack", ("docker", "compose", "up", "-d", "--build"), "compose"),
    Check("Four-service health", (sys.executable, "scripts/wait_compose.py"), "compose"),
    Check(
        "Kyoto-to-Tokyo Route B API scenario",
        (sys.executable, "scripts/phase3_api_smoke.py"),
        "integration",
    ),
    Check(
        "Access, map, and timeline E2E",
        (
            "pnpm",
            "--filter",
            "@pilgrimage/web",
            "exec",
            "playwright",
            "test",
            "e2e/foundation.spec.ts",
            "e2e/phase2.spec.ts",
            "e2e/phase3.spec.ts",
        ),
        "e2e",
    ),
)

PHASE_4 = (
    Check("Python lint", ("uv", "run", "ruff", "check", "."), "static"),
    Check("Python strict types", ("uv", "run", "mypy"), "static"),
    Check("Web lint", ("pnpm", "lint"), "static"),
    Check("Web strict types", ("pnpm", "typecheck"), "static"),
    Check(
        "LangGraph, context, review, and memory fixtures",
        (
            "uv",
            "run",
            "pytest",
            "tests/unit/test_phase4_graph.py",
            "tests/unit/test_phase4_context_review.py",
            "tests/unit/test_phase4_memory.py",
            "tests/unit/test_workspace_graph.py",
            "tests/unit/test_workspace_api.py",
        ),
        "fixture",
    ),
    Check("Web unit regression", ("pnpm", "test"), "fixture"),
    Check("Repository secret scan", (sys.executable, "scripts/check_secrets.py"), "security"),
    Check("Build and start full stack", ("docker", "compose", "up", "-d", "--build"), "compose"),
    Check("Four-service health", (sys.executable, "scripts/wait_compose.py"), "compose"),
    Check(
        "Five PostgreSQL project stores",
        (
            "docker",
            "compose",
            "exec",
            "-T",
            "api",
            "python",
            "-m",
            "pilgrimage_agent.smoke.phase4_memory",
        ),
        "integration",
    ),
    Check(
        "Checkpoint resume after API restart",
        ("uv", "run", "python", "scripts/phase4_api_smoke.py"),
        "integration",
    ),
    Check(
        "Workspace clear and transactional deletion",
        ("uv", "run", "python", "scripts/workspace_deletion_smoke.py"),
        "integration",
    ),
    Check(
        "One real structured-output LLM smoke",
        ("uv", "run", "python", "scripts/live_llm_smoke.py"),
        "live",
    ),
    Check(
        "Desktop/mobile browser regression",
        (
            "pnpm",
            "--filter",
            "@pilgrimage/web",
            "exec",
            "playwright",
            "test",
            "e2e/foundation.spec.ts",
            "e2e/phase2.spec.ts",
            "e2e/phase3.spec.ts",
        ),
        "e2e",
    ),
)

PHASE_5 = (
    Check("Python lint", ("uv", "run", "ruff", "check", "."), "static"),
    Check("Python strict types", ("uv", "run", "mypy"), "static"),
    Check("Web lint", ("pnpm", "lint"), "static"),
    Check("Web strict types", ("pnpm", "typecheck"), "static"),
    Check(
        "RAG ingestion, retrieval, conflicts, persistence, and exports",
        (
            "uv",
            "run",
            "pytest",
            "tests/unit/test_phase5_rag.py",
            "tests/unit/test_phase5_ingestion_exports.py",
        ),
        "fixture",
    ),
    Check(
        "Golden metrics and versioned export schemas",
        ("uv", "run", "python", "scripts/phase5_artifacts.py"),
        "fixture",
    ),
    Check(
        "All Python regressions with coverage",
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
    Check("Web unit regression", ("pnpm", "test"), "fixture"),
    Check("Repository secret scan", (sys.executable, "scripts/check_secrets.py"), "security"),
    Check(
        "Real multilingual E5 dimension and normalization",
        ("uv", "run", "--extra", "rag", "python", "scripts/e5_smoke.py"),
        "model",
    ),
    Check("Build and start full stack", ("docker", "compose", "up", "-d", "--build"), "compose"),
    Check("Four-service health", (sys.executable, "scripts/wait_compose.py"), "compose"),
    Check(
        "RAG migration is current",
        ("docker", "compose", "exec", "-T", "api", "alembic", "upgrade", "head"),
        "integration",
    ),
    Check(
        "Exact pgvector and persistent BM25/RRF",
        (
            "docker",
            "compose",
            "exec",
            "-T",
            "api",
            "python",
            "-m",
            "pilgrimage_agent.smoke.phase5_rag",
        ),
        "integration",
    ),
    Check(
        "Knowledge API isolation, dedupe, metrics, and deletion",
        (sys.executable, "scripts/phase5_api_smoke.py"),
        "integration",
    ),
    Check("Complete revision and export browser flow", ("pnpm", "test:e2e"), "e2e"),
    Check(
        "Remove fixed RAG corpus from PostgreSQL",
        (
            "docker",
            "compose",
            "exec",
            "-T",
            "api",
            "python",
            "-m",
            "pilgrimage_agent.smoke.phase5_rag",
            "--cleanup",
        ),
        "integration",
    ),
)

PHASE_6 = (
    Check("Python lint", ("uv", "run", "ruff", "check", "."), "static"),
    Check("Python strict types", ("uv", "run", "mypy"), "static"),
    Check("Web lint", ("pnpm", "lint"), "static"),
    Check("Web strict types", ("pnpm", "typecheck"), "static"),
    Check(
        "Timeout, 429, partial, invalid-model, and deterministic fallback regressions",
        (
            "uv",
            "run",
            "pytest",
            "tests/contract/test_phase2_providers.py",
            "tests/unit/test_phase3_planning.py",
            "tests/unit/test_phase4_graph.py",
        ),
        "resilience",
    ),
    Check("Web unit regression", ("pnpm", "test"), "fixture"),
    Check("Final documentation contract", (sys.executable, "scripts/phase6_docs_check.py"), "docs"),
    Check(
        "Dependency license inventory",
        ("uv", "run", "python", "scripts/license_audit.py"),
        "security",
    ),
    Check("Production Web bundle", ("pnpm", "--filter", "@pilgrimage/web", "build"), "build"),
    Check("Repository secret scan", (sys.executable, "scripts/check_secrets.py"), "security"),
    Check(
        "Deliverable privacy and MCP boundary metrics",
        (sys.executable, "scripts/privacy_audit.py"),
        "security",
    ),
    Check("Compose schema", ("docker", "compose", "config", "--quiet"), "compose"),
    Check(
        "Remove only project Compose containers and volumes",
        ("docker", "compose", "down", "--volumes", "--remove-orphans"),
        "clean-start",
    ),
    Check("Build clean full stack", ("docker", "compose", "up", "-d", "--build"), "clean-start"),
    Check(
        "Clean-stack four-service health",
        (sys.executable, "scripts/wait_compose.py"),
        "clean-start",
    ),
    Check(
        "Clean database migration",
        ("docker", "compose", "exec", "-T", "api", "alembic", "upgrade", "head"),
        "clean-start",
    ),
    Check(
        "Seed and verify fixed hybrid RAG corpus",
        (
            "docker",
            "compose",
            "exec",
            "-T",
            "api",
            "python",
            "-m",
            "pilgrimage_agent.smoke.phase5_rag",
        ),
        "demo",
    ),
    Check(
        "Subject confirmation and Route A demo",
        (sys.executable, "scripts/phase2_api_smoke.py"),
        "demo",
    ),
    Check(
        "Constraint-checked Route B demo",
        (sys.executable, "scripts/phase3_api_smoke.py"),
        "demo",
    ),
    Check("Knowledge API demo", (sys.executable, "scripts/phase5_api_smoke.py"), "demo"),
    Check(
        "PostgreSQL restart recovery and isolation",
        (sys.executable, "scripts/phase6_recovery_smoke.py"),
        "resilience",
    ),
    Check("Full desktop/mobile demo", ("pnpm", "test:e2e"), "e2e"),
    Check(
        "Remove fixed RAG demo corpus",
        (
            "docker",
            "compose",
            "exec",
            "-T",
            "api",
            "python",
            "-m",
            "pilgrimage_agent.smoke.phase5_rag",
            "--cleanup",
        ),
        "clean-start",
    ),
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
    phase_checks = {
        1: PHASE_1,
        2: PHASE_2,
        3: PHASE_3,
        4: PHASE_4,
        5: PHASE_5,
        6: PHASE_6,
    }.get(phase)
    if phase_checks is None:
        ARTIFACTS.mkdir(parents=True, exist_ok=True)
        path = ARTIFACTS / f"phase-{phase}-report.md"
        path.write_text(
            f"# Phase {phase} verification\n\nStatus: **not implemented**\n",
            encoding="utf-8",
        )
        print(f"Phase {phase} is not implemented yet; report: {path}")
        return False

    results: list[tuple[Check, int, str]] = []
    ARTIFACTS.mkdir(parents=True, exist_ok=True)
    command_env = os.environ.copy()
    command_env["COMPOSE_BAKE"] = "false"
    if phase >= 5:
        command_env["HF_HUB_OFFLINE"] = "1"
    for check in phase_checks:
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
        if phase == 2 and check.name == "MCP schema snapshot" and code == 0:
            (ARTIFACTS / "mcp-tools-schema.json").write_text(output + "\n", encoding="utf-8")
        if code != 0:
            break

    ARTIFACTS.mkdir(parents=True, exist_ok=True)
    report = ARTIFACTS / f"phase-{phase}-report.md"
    lines = [
        f"# Phase {phase} verification",
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
    if len(results) < len(phase_checks):
        for check in phase_checks[len(results) :]:
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
            {
                1: "- Live external API evidence: not part of Phase 1; no live calls were made.",
                2: "- Live external API evidence: the separately labelled live smoke row; "
                "each configured provider is called at most once and SearchAPI at most once.",
                4: "- Live external API evidence: one separately labelled, structured-output "
                "LLM smoke; no configuration or response body is logged.",
            }.get(
                phase,
                "- Live external API evidence: no additional live calls were required "
                "for this phase; "
                "provider behavior is covered by the prior live gate plus current fixtures.",
            ),
        ]
    )
    report.write_text("\n".join(lines) + "\n", encoding="utf-8")
    passed = len(results) == len(phase_checks) and not failures
    print(f"\nPhase {phase} {'passed' if passed else 'failed'}; report: {report}")
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
    if requested in {"6", "all"}:
        write_final_verification(overall_verified=requested == "all")
    return 0


def write_final_verification(*, overall_verified: bool) -> None:
    """Write value-safe final evidence after Phase 6 has produced its report."""

    rag = json.loads((ARTIFACTS / "rag-evaluation.json").read_text("utf-8"))
    security = json.loads((ARTIFACTS / "security-metrics.json").read_text("utf-8"))
    licenses = json.loads((ARTIFACTS / "dependency-licenses.json").read_text("utf-8"))
    phase_status = {
        str(phase): (
            "PASS"
            if (ARTIFACTS / f"phase-{phase}-report.md").exists()
            and "| FAIL |" not in (ARTIFACTS / f"phase-{phase}-report.md").read_text("utf-8")
            and "| NOT RUN |" not in (ARTIFACTS / f"phase-{phase}-report.md").read_text("utf-8")
            else "FAIL_OR_MISSING"
        )
        for phase in range(1, 7)
    }
    metrics = {
        "schema_version": "1",
        "generated_at": datetime.now(UTC).isoformat(),
        "phase_status": phase_status,
        "rag": {
            "query_count": rag["query_count"],
            "recall_at_6": rag["recall_at_6"],
            "mrr_at_10": rag["mrr_at_10"],
            "citation_precision": rag["citation_precision"],
            "failed_query_ids": rag["failed_query_ids"],
        },
        "security": security,
        "licenses": {
            "python_package_count": licenses["python_package_count"],
            "node_package_count": licenses["node_package_count"],
            "denied_license_count": licenses["denied_license_count"],
        },
    }
    (ARTIFACTS / "system-metrics.json").write_text(
        json.dumps(metrics, ensure_ascii=False, indent=2) + "\n", "utf-8"
    )
    status = (
        "PASS"
        if overall_verified and all(value == "PASS" for value in phase_status.values())
        else "PHASE 6 PASS; verify-all pending"
    )
    lines = [
        "# Final verification",
        "",
        f"Generated: {metrics['generated_at']}",
        f"Status: **{status}**",
        "",
        "## Commands",
        "",
        "- `make verify-phase-1` through `make verify-phase-6`: see phase reports.",
        f"- `make verify-all`: {'PASS' if overall_verified else 'not yet run in this invocation'}.",
        "- Clean acceptance removed only project Compose volumes, rebuilt four services, "
        "migrated an empty database, ran the demo, restarted PostgreSQL, and recovered.",
        "",
        "## Results",
        "",
        *[f"- Phase {phase}: {phase_status[str(phase)]}" for phase in range(1, 7)],
        "- Python coverage: at least 80% (exact value in Phase 5/all-test output).",
        f"- RAG: Recall@6 {rag['recall_at_6']:.3f}; MRR@10 {rag['mrr_at_10']:.3f}; "
        f"Citation Precision {rag['citation_precision']:.3f}; "
        "failed IDs disclosed in the JSON report.",
        f"- Security: {security['local_secret_exposures']} secret exposures, "
        f"{security['conversation_body_exposures']} conversation-body exposures, "
        f"{security['forbidden_mcp_tool_count']} forbidden MCP tools.",
        f"- Licenses: {licenses['python_package_count']} Python and "
        f"{licenses['node_package_count']} Node records; "
        f"{licenses['denied_license_count']} denied licenses.",
        "",
        "## Browser evidence",
        "",
        "- `artifacts/screenshots/phase-5-desktop.png`",
        "- `artifacts/screenshots/phase-5-mobile.png`",
        "- Serialized Playwright acceptance covers request, confirmation, access/base, "
        "planning, local revision stability, persistent conversational replanning/reload "
        "recovery, evidence, and all three exports.",
        "",
        "## Known limitations",
        "",
        "- Live travel facts remain snapshots/estimates and require reconfirmation.",
        "- Scanned PDFs require external OCR; the MVP returns `needs_ocr`.",
        "- Initial official E5 model download is an operator prerequisite; "
        "subsequent smoke is offline.",
        "- Anitabi may expose fewer documented detail records than `/lite` advertises; "
        "Route A remains explicitly partial and does not use undocumented scraping.",
        "- Workspace modification is bounded to validated PlanPatch operations; material "
        "changes require explicit confirmation.",
        "- This is a local Compose service without a production identity provider or HA setup.",
        "- Complete details: `docs/KNOWN_LIMITATIONS.md`.",
        "",
        "No deployment, booking, payment, purchase, or external message was performed.",
    ]
    (ARTIFACTS / "final-verification.md").write_text("\n".join(lines) + "\n", "utf-8")


if __name__ == "__main__":
    raise SystemExit(main())
