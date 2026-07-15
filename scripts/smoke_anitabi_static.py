"""Read-only live smoke for MiriaGo-compatible Anitabi static metadata."""

from __future__ import annotations

import argparse
import asyncio
import json
from datetime import timedelta

from pilgrimage_agent.domain.models import PilgrimagePointQuery
from pilgrimage_agent.providers.anitabi_static import AnitabiStaticAdapter
from pilgrimage_agent.providers.http import SafeHttpClient


async def _run(subject_id: str, *, diagnostics: bool) -> int:
    http = SafeHttpClient(
        provider="anitabi_static",
        timeout_seconds=20,
        max_attempts=3,
        max_response_bytes=64 * 1024 * 1024,
    )
    try:
        result = await AnitabiStaticAdapter(
            http=http,
            cache_ttl=timedelta(hours=6),
        ).fetch(PilgrimagePointQuery(subject_id=subject_id, provider="anitabi"))
    finally:
        await http.close()
    payload: dict[str, object] = {
        "subject_id": subject_id,
        "provider": result.provenance.provider,
        "data_version": result.data_version,
        "expected_count": result.expected_count,
        "loaded_count": result.loaded_count,
        "is_complete": result.is_complete,
        "warning_count": len(result.warnings),
    }
    if diagnostics:
        payload["warnings"] = result.warnings
    print(json.dumps(payload, ensure_ascii=False))
    return 0 if result.is_complete else 1


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--subject-id", default="328609")
    parser.add_argument("--diagnostics", action="store_true")
    arguments = parser.parse_args()
    return asyncio.run(_run(arguments.subject_id, diagnostics=arguments.diagnostics))


if __name__ == "__main__":
    raise SystemExit(main())
