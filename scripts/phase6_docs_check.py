"""Verify that final operator, architecture, demo, and portfolio docs are complete."""

from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
REQUIRED = {
    "README.md": ("## Architecture", "## Demo", "## Verification", "## Known limitations"),
    "docs/DEMO.md": ("## Preconditions", "## Walkthrough", "## Safety"),
    "docs/KNOWN_LIMITATIONS.md": ("## External data", "## RAG", "## Operations"),
    "docs/RESUME_BULLETS.md": ("## Resume bullets", "## Interview talking points"),
    "docs/adr/0001-provider-and-data-boundaries.md": ("Status: Accepted", "## Decision"),
    "docs/adr/0002-agent-memory-and-rag.md": ("Status: Accepted", "## Decision"),
}


def main() -> int:
    failures: list[str] = []
    for relative, markers in REQUIRED.items():
        path = ROOT / relative
        if not path.exists():
            failures.append(f"missing {relative}")
            continue
        text = path.read_text("utf-8")
        failures.extend(f"{relative} lacks {marker}" for marker in markers if marker not in text)
    if failures:
        print("Documentation contract failed:")
        for failure in failures:
            print(f"- {failure}")
        return 1
    print(f"Documentation contract passed for {len(REQUIRED)} final handoff files.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
