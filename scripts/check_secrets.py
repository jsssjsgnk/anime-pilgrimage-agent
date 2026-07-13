"""Fail if local secret values or obvious credential assignments enter project outputs."""

from __future__ import annotations

import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SKIP_DIRS = {".git", ".venv", ".tmp", "node_modules", "dist", "playwright-report"}
SKIP_FILES = {".env"}
TEXT_SUFFIXES = {
    "",
    ".css",
    ".html",
    ".ini",
    ".json",
    ".jsonl",
    ".md",
    ".mjs",
    ".py",
    ".toml",
    ".ts",
    ".tsx",
    ".txt",
    ".yaml",
    ".yml",
}
SECRET_NAMES = {
    "LLM_API_KEY",
    "BANGUMI_ACCESS_TOKEN",
    "ORS_API_KEY",
    "SEARCHAPI_API_KEY",
}


def local_secret_values() -> list[str]:
    env_path = ROOT / ".env"
    if not env_path.exists():
        return []
    values: list[str] = []
    for line in env_path.read_text(encoding="utf-8").splitlines():
        if "=" not in line or line.lstrip().startswith("#"):
            continue
        name, value = line.split("=", 1)
        if name.strip() in SECRET_NAMES and len(value.strip()) >= 8:
            values.append(value.strip().strip("\"'"))
    return values


def candidate_files() -> list[Path]:
    files: list[Path] = []
    for path in ROOT.rglob("*"):
        if not path.is_file() or path.name in SKIP_FILES:
            continue
        if any(part in SKIP_DIRS for part in path.relative_to(ROOT).parts):
            continue
        if path.suffix.lower() in TEXT_SUFFIXES and path.stat().st_size <= 5_000_000:
            files.append(path)
    return files


def main() -> int:
    secret_values = local_secret_values()
    assignment = re.compile(
        r"(?i)(api[_-]?key|access[_-]?token|authorization|cookie)"
        r"[\t ]*[:=][\t ]*(?:['\"][^'\"]{12,}['\"]|[A-Za-z0-9_-]{20,})"
    )
    violations: list[str] = []
    for path in candidate_files():
        try:
            text = path.read_text(encoding="utf-8")
        except UnicodeDecodeError:
            continue
        relative = path.relative_to(ROOT).as_posix()
        if any(value and value in text for value in secret_values):
            violations.append(f"{relative}: contains a local secret value")
        if relative != "scripts/check_secrets.py":
            for line in text.splitlines():
                if assignment.search(line) and "fixture" not in line.casefold():
                    violations.append(f"{relative}: contains a credential-like assignment")
                    break
    if violations:
        print("Secret scan failed (values redacted):")
        for violation in sorted(set(violations)):
            print(f"- {violation}")
        return 1
    count = len(candidate_files())
    print(f"Secret scan passed across {count} text files; values were never printed.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
