"""Initialize the internal MCP server and inspect its allowlisted tools."""

from __future__ import annotations

import asyncio
import sys

from mcp import ClientSession
from mcp.client.streamable_http import streamablehttp_client


async def smoke(url: str) -> None:
    async with streamablehttp_client(url) as streams:
        read_stream, write_stream, _ = streams
        async with ClientSession(read_stream, write_stream) as session:
            await session.initialize()
            tools = await session.list_tools()
            names = sorted(tool.name for tool in tools.tools)
            if names != ["service_status"]:
                raise RuntimeError(
                    "Phase 1 MCP allowlist differs from the expected read-only schema"
                )
            print("MCP initialize/tools-list passed with one read-only status tool")


def main() -> int:
    url = sys.argv[1] if len(sys.argv) > 1 else "http://127.0.0.1:8001/mcp"
    asyncio.run(smoke(url))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
