"""Allowlisted, read-only MCP service entrypoint."""

from mcp.server.fastmcp import FastMCP

mcp = FastMCP(
    "anime-pilgrimage-readonly-tools",
    instructions=(
        "Read-only normalized travel data tools. Booking, payment, writes, shell, "
        "filesystem, arbitrary URL fetches, and raw database access are unavailable."
    ),
    host="0.0.0.0",
    port=8001,
)


@mcp.tool()
def service_status() -> dict[str, object]:
    """Return non-sensitive service readiness metadata."""

    return {
        "status": "ok",
        "service": "mcp-tools",
        "read_only": True,
        "write_capabilities": [],
    }


def main() -> None:
    """Run the MCP server using Streamable HTTP."""

    mcp.run(transport="streamable-http")


if __name__ == "__main__":
    main()

