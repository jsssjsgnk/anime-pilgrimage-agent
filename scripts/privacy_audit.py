"""Measure secret, conversation, and forbidden-tool leakage in deliverable outputs."""

from __future__ import annotations

import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
OUTPUT = ROOT / "artifacts" / "security-metrics.json"
SCOPES = (ROOT / "artifacts", ROOT / "apps" / "web" / "dist")
FORBIDDEN_TOOL_TERMS = ("book", "pay", "purchase", "shell", "filesystem", "arbitrary_url")


def _secret_values() -> tuple[bytes, ...]:
    env = ROOT / ".env"
    if not env.exists():
        return ()
    values: list[bytes] = []
    for line in env.read_text("utf-8").splitlines():
        if "=" not in line or line.lstrip().startswith("#"):
            continue
        name, value = line.split("=", 1)
        if any(token in name.upper() for token in ("KEY", "TOKEN", "SECRET")):
            cleaned = value.strip().strip("\"'")
            if len(cleaned) >= 8:
                values.append(cleaned.encode())
    return tuple(values)


def main() -> int:
    files = sorted(
        path
        for scope in SCOPES
        if scope.exists()
        for path in scope.rglob("*")
        if path.is_file() and path.stat().st_size <= 10_000_000
    )
    secret_values = _secret_values()
    kickoff = (ROOT / "CODEX_KICKOFF.txt").read_bytes().strip()
    secret_exposures = 0
    conversation_exposures = 0
    for path in files:
        payload = path.read_bytes()
        secret_exposures += sum(1 for value in secret_values if value in payload)
        if kickoff and kickoff in payload:
            conversation_exposures += 1
    tools = cast_tool_list(
        json.loads((ROOT / "artifacts" / "mcp-tools-schema.json").read_text("utf-8"))
    )
    forbidden_tools = [
        str(tool.get("name", ""))
        for tool in tools
        if any(term in str(tool.get("name", "")).casefold() for term in FORBIDDEN_TOOL_TERMS)
    ]
    metrics = {
        "schema_version": "1",
        "files_scanned": len(files),
        "local_secret_exposures": secret_exposures,
        "conversation_body_exposures": conversation_exposures,
        "mcp_tool_count": len(tools),
        "forbidden_mcp_tool_count": len(forbidden_tools),
        "forbidden_mcp_tools": forbidden_tools,
    }
    OUTPUT.write_text(json.dumps(metrics, indent=2) + "\n", "utf-8")
    passed = secret_exposures == 0 and conversation_exposures == 0 and not forbidden_tools
    print(
        f"Privacy audit scanned {len(files)} deliverables: secret exposures={secret_exposures}, "
        f"conversation exposures={conversation_exposures}, "
        f"forbidden MCP tools={len(forbidden_tools)}."
    )
    return 0 if passed else 1


def cast_tool_list(value: object) -> list[dict[str, object]]:
    if not isinstance(value, list) or not all(isinstance(item, dict) for item in value):
        raise ValueError("MCP schema snapshot must be a list of objects")
    return [dict(item) for item in value]


if __name__ == "__main__":
    raise SystemExit(main())
