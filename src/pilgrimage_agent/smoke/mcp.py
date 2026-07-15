"""Initialize the internal MCP server and validate its exact read-only allowlist."""

from __future__ import annotations

import asyncio
import hashlib
import json
import sys
from typing import Any

from mcp import ClientSession
from mcp.client.streamable_http import streamablehttp_client

EXPECTED_TOOLS = [
    "fetch_pilgrimage_points",
    "geocode_place",
    "get_anime_subject",
    "get_place_facts",
    "get_route_directions",
    "get_route_matrix",
    "get_weather_forecast",
    "search_anime_subjects",
    "search_flexible_flight_dates",
    "search_flight_options",
    "search_place_facts",
    "search_transit_options",
]


async def inspect(url: str) -> list[dict[str, Any]]:
    async with streamablehttp_client(url) as streams:
        read_stream, write_stream, _ = streams
        async with ClientSession(read_stream, write_stream) as session:
            await session.initialize()
            tools = await session.list_tools()
            snapshot = [tool.model_dump(mode="json") for tool in tools.tools]
            names = sorted(tool["name"] for tool in snapshot)
            if names != EXPECTED_TOOLS:
                raise RuntimeError("MCP allowlist differs from the expected read-only tools")
            for tool in snapshot:
                schema = tool.get("inputSchema")
                if not isinstance(schema, dict) or schema.get("type") != "object":
                    raise RuntimeError(f"MCP tool {tool['name']} lacks an object input schema")
            return sorted(snapshot, key=lambda item: str(item["name"]))


def main() -> int:
    url = sys.argv[1] if len(sys.argv) > 1 else "http://127.0.0.1:8001/mcp"
    snapshot = asyncio.run(inspect(url))
    canonical = json.dumps(snapshot, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    if "--snapshot" in sys.argv:
        print(canonical)
    else:
        digest = hashlib.sha256(canonical.encode()).hexdigest()[:16]
        print(f"MCP initialize/tools-list passed with 12 read-only tools; schema digest {digest}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
