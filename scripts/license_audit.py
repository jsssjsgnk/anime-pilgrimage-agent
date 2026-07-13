"""Inventory locked Python/Node licenses and reject strongly restricted terms."""

from __future__ import annotations

import json
import shutil
import subprocess
from importlib import metadata
from pathlib import Path
from typing import Any, cast

ROOT = Path(__file__).resolve().parents[1]
OUTPUT = ROOT / "artifacts" / "dependency-licenses.json"
DENIED = ("AGPL", "SSPL", "BUSL", "BUSINESS SOURCE")


def _python_license(distribution: metadata.Distribution) -> str:
    expression = distribution.metadata.get("License-Expression")
    if expression:
        return expression.strip()
    value = distribution.metadata.get("License")
    if value and len(value.strip()) <= 160:
        return value.strip()
    classifiers = distribution.metadata.get_all("Classifier", [])
    licenses = [
        item.removeprefix("License :: ")
        for item in classifiers
        if item.startswith("License :: ")
    ]
    return " OR ".join(licenses) if licenses else "UNKNOWN"


def _node_licenses() -> tuple[list[dict[str, str]], set[str]]:
    executable = shutil.which("pnpm")
    if executable is None:
        raise RuntimeError("pnpm is required for the Node license inventory")
    completed = subprocess.run(
        (executable, "licenses", "list", "--json"),
        cwd=ROOT,
        capture_output=True,
        text=True,
        check=False,
    )
    if completed.returncode != 0:
        raise RuntimeError("pnpm license inventory failed")
    grouped = cast(dict[str, list[dict[str, Any]]], json.loads(completed.stdout))
    packages: list[dict[str, str]] = []
    license_names: set[str] = set()
    for license_name, entries in grouped.items():
        license_names.add(license_name)
        for entry in entries:
            versions = cast(list[str], entry.get("versions", []))
            packages.append(
                {
                    "name": str(entry.get("name", "unknown")),
                    "version": ",".join(versions),
                    "license": license_name,
                }
            )
    return sorted(packages, key=lambda item: (item["name"], item["version"])), license_names


def main() -> int:
    python_packages = []
    license_names: set[str] = set()
    for distribution in metadata.distributions():
        name = distribution.metadata.get("Name")
        if not name:
            continue
        license_name = _python_license(distribution)
        license_names.add(license_name)
        python_packages.append(
            {"name": name, "version": distribution.version, "license": license_name}
        )
    node_packages, node_license_names = _node_licenses()
    license_names.update(node_license_names)
    denied = sorted(
        license_name
        for license_name in license_names
        if any(term in license_name.upper() for term in DENIED)
    )
    payload = {
        "schema_version": "1",
        "python_package_count": len(python_packages),
        "node_package_count": len(node_packages),
        "denied_license_count": len(denied),
        "denied_licenses": denied,
        "review_note": "UNKNOWN metadata requires human review before redistribution.",
        "python": sorted(
            python_packages,
            key=lambda item: (item["name"].casefold(), item["version"]),
        ),
        "node": node_packages,
    }
    OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    OUTPUT.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", "utf-8")
    print(
        f"License inventory passed: {len(python_packages)} Python and "
        f"{len(node_packages)} Node package records; denied={len(denied)}."
    )
    return 1 if denied else 0


if __name__ == "__main__":
    raise SystemExit(main())
