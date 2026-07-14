"""LangChain MCP adapter result and allowlist contracts."""

import pytest
from langchain_core.messages import ToolMessage

from pilgrimage_agent.agent.mcp_client import (
    ALLOWED_AGENT_TOOLS,
    FixtureAgentToolClient,
    LangChainMcpToolClient,
    normalized_tool_result,
)


def test_normalized_tool_result_accepts_structured_artifact_and_json_text() -> None:
    message = ToolMessage(
        content="ignored human-readable content",
        tool_call_id="fixture-call",
        artifact={"structured_content": {"points": [], "is_complete": True}},
    )
    assert normalized_tool_result(message) == {"points": [], "is_complete": True}
    assert normalized_tool_result('{"status":"ok"}') == {"status": "ok"}
    text_message = ToolMessage(
        content=[{"type": "text", "text": '{"available":false}'}],
        tool_call_id="text-call",
    )
    assert normalized_tool_result(text_message) == {"available": False}
    with pytest.raises(ValueError, match="invalid structured content"):
        normalized_tool_result(["not", "an", "object"])


async def test_fixture_agent_client_calls_normalized_allowlisted_tools() -> None:
    client = FixtureAgentToolClient()
    subjects = await client.call(
        "search_anime_subjects", {"query": "孤独摇滚", "limit": 5}
    )
    points = await client.call(
        "fetch_pilgrimage_points", {"subject_id": "328609", "provider": "fixture"}
    )
    assert subjects["candidates"]
    assert isinstance(points["points"], list)
    assert len(points["points"]) == 3
    with pytest.raises(ValueError, match="non-allowlisted"):
        await client.call("book_flight", {})


async def test_langchain_client_loads_exact_allowlist_and_invokes_structured_tool() -> None:
    class FakeTool:
        def __init__(self, name: str) -> None:
            self.name = name

        async def ainvoke(self, _call: object) -> dict[str, object]:
            return {"tool": self.name}

    class FakeMcpClient:
        async def get_tools(self, *, server_name: str) -> list[FakeTool]:
            assert server_name == "pilgrimage"
            return [FakeTool(name) for name in ALLOWED_AGENT_TOOLS]

    client = LangChainMcpToolClient(url="http://127.0.0.1:8001/mcp")
    client.client = FakeMcpClient()  # type: ignore[assignment]
    result = await client.call("get_weather_forecast", {"fixture": True})
    assert result == {"tool": "get_weather_forecast"}
    assert await client._load_tools()
