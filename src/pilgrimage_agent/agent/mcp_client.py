"""Typed allowlisted LangChain MCP adapter boundary for the runtime Agent."""

from __future__ import annotations

import json
from collections.abc import Mapping
from typing import Any, Protocol, cast
from uuid import uuid4

from langchain_core.messages import ToolMessage
from langchain_mcp_adapters.client import MultiServerMCPClient
from langchain_mcp_adapters.sessions import StreamableHttpConnection
from pydantic import BaseModel, TypeAdapter, ValidationError

from pilgrimage_agent.config import Settings
from pilgrimage_agent.domain.models import (
    FlexibleFlightQuery,
    FlightSearchQuery,
    MatrixQuery,
    PilgrimagePointQuery,
    PlaceSearchQuery,
    SubjectSearchQuery,
    WeatherForecastQuery,
)
from pilgrimage_agent.providers.service import ProviderServices

ALLOWED_AGENT_TOOLS = frozenset(
    {
        "search_anime_subjects",
        "get_anime_subject",
        "fetch_pilgrimage_points",
        "geocode_place",
        "get_route_directions",
        "get_route_matrix",
        "get_weather_forecast",
        "search_flight_options",
        "search_flexible_flight_dates",
    }
)
_DICT = TypeAdapter(dict[str, object])


class AgentToolClient(Protocol):
    async def call(self, name: str, arguments: Mapping[str, object]) -> dict[str, object]: ...


def _content_text(content: object) -> str:
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        texts: list[str] = []
        for block in content:
            if isinstance(block, str):
                texts.append(block)
            elif isinstance(block, dict) and isinstance(block.get("text"), str):
                texts.append(cast(str, block["text"]))
        return "".join(texts)
    raise ValueError("MCP tool returned unsupported content")


def normalized_tool_result(result: object) -> dict[str, object]:
    """Extract one structured object without passing raw tool payloads to the Agent state."""

    candidate: object = result
    if isinstance(result, ToolMessage):
        artifact = result.artifact
        if isinstance(artifact, dict) and isinstance(artifact.get("structured_content"), dict):
            candidate = artifact["structured_content"]
        else:
            candidate = _content_text(result.content)
    if isinstance(candidate, str):
        candidate = json.loads(candidate)
    try:
        return _DICT.validate_python(candidate)
    except (ValidationError, json.JSONDecodeError, ValueError, TypeError):
        raise ValueError("MCP tool returned invalid structured content") from None


class LangChainMcpToolClient:
    """Load and invoke only the project's internal read-only MCP tools."""

    def __init__(self, *, url: str, timeout_seconds: float = 10.0) -> None:
        connection: StreamableHttpConnection = {
            "transport": "streamable_http",
            "url": url,
            "timeout": timeout_seconds,
            "sse_read_timeout": timeout_seconds,
            "terminate_on_close": True,
        }
        self.client = MultiServerMCPClient(
            {"pilgrimage": connection},
            handle_tool_errors=False,
        )
        self._tools: dict[str, Any] | None = None

    async def _load_tools(self) -> dict[str, Any]:
        if self._tools is None:
            loaded = await self.client.get_tools(server_name="pilgrimage")
            tools = {tool.name: tool for tool in loaded if tool.name in ALLOWED_AGENT_TOOLS}
            if set(tools) != ALLOWED_AGENT_TOOLS:
                raise RuntimeError("MCP tool allowlist does not match the Agent contract")
            self._tools = tools
        return self._tools

    async def call(self, name: str, arguments: Mapping[str, object]) -> dict[str, object]:
        if name not in ALLOWED_AGENT_TOOLS:
            raise ValueError("Agent requested a non-allowlisted MCP tool")
        tools = await self._load_tools()
        result = await tools[name].ainvoke(
            {
                "name": name,
                "args": dict(arguments),
                "id": str(uuid4()),
                "type": "tool_call",
            }
        )
        return normalized_tool_result(result)


class FixtureAgentToolClient:
    """In-process normalized fixture double for deterministic graph tests."""

    def __init__(self) -> None:
        self.services = ProviderServices(
            Settings(_env_file=None, provider_mode="fixture", PILGRIMAGE_POINT_MODE="fixture")
        )

    async def call(self, name: str, arguments: Mapping[str, object]) -> dict[str, object]:
        if name not in ALLOWED_AGENT_TOOLS:
            raise ValueError("Agent requested a non-allowlisted MCP tool")
        result: BaseModel
        if name == "search_anime_subjects":
            result = await self.services.bangumi.fetch(
                SubjectSearchQuery.model_validate(arguments)
            )
        elif name == "get_anime_subject":
            subject_id = TypeAdapter(str).validate_python(arguments.get("subject_id"))
            result = await self.services.bangumi.get_subject(subject_id)
        elif name == "fetch_pilgrimage_points":
            result = await self.services.points.fetch(
                PilgrimagePointQuery.model_validate(arguments)
            )
        elif name == "get_route_matrix":
            result = await self.services.ors.matrix(MatrixQuery.model_validate(arguments))
        elif name == "geocode_place":
            result = await self.services.ors.geocode(
                PlaceSearchQuery.model_validate(arguments)
            )
        elif name == "get_weather_forecast":
            result = await self.services.weather.fetch(
                WeatherForecastQuery.model_validate(arguments)
            )
        elif name == "search_flight_options":
            result = await self.services.flights.fetch(
                FlightSearchQuery.model_validate(arguments)
            )
        elif name == "search_flexible_flight_dates":
            result = await self.services.flights.flexible(
                FlexibleFlightQuery.model_validate(arguments)
            )
        else:
            raise NotImplementedError(f"Fixture tool {name} is not needed by this graph path")
        return _DICT.validate_python(result.model_dump(mode="json"))
