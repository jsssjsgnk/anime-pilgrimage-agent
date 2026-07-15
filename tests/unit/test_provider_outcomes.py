"""Graph-facing provider outcomes normalize success and safe degradation."""

from collections.abc import Mapping
from datetime import UTC, datetime

from pilgrimage_agent.domain.models import DataProvenance, DataStatus, StrictModel
from pilgrimage_agent.providers.base import ProviderError, ProviderErrorKind
from pilgrimage_agent.providers.outcomes import ToolOutcomeStatus, invoke_tool


class ExampleResult(StrictModel):
    label: str
    provenance: DataProvenance


class StubClient:
    def __init__(self, result: dict[str, object] | Exception) -> None:
        self.result = result

    async def call(
        self, name: str, arguments: Mapping[str, object]
    ) -> dict[str, object]:
        del name, arguments
        if isinstance(self.result, Exception):
            raise self.result
        return self.result


def _result() -> ExampleResult:
    return ExampleResult(
        label="verified",
        provenance=DataProvenance(
            provider="fixture",
            fetched_at=datetime.now(UTC),
            status=DataStatus.COMMUNITY,
        ),
    )


async def test_invoke_tool_returns_validated_value_and_provenance() -> None:
    expected = _result()
    outcome = await invoke_tool(
        StubClient(expected.model_dump(mode="json")), "example", {}, ExampleResult
    )

    assert outcome.status is ToolOutcomeStatus.OK
    assert outcome.value == expected
    assert outcome.provenance == expected.provenance


async def test_invoke_tool_normalizes_rate_limit_without_raw_error() -> None:
    outcome = await invoke_tool(
        StubClient(
            ProviderError(
                kind=ProviderErrorKind.RATE_LIMIT,
                provider="openrouteservice",
                safe_message="Request budget is temporarily unavailable.",
                retryable=True,
            )
        ),
        "get_route_matrix",
        {},
        ExampleResult,
    )

    assert outcome.status is ToolOutcomeStatus.RATE_LIMITED
    assert outcome.value is None
    assert outcome.safe_warning == (
        "openrouteservice: Request budget is temporarily unavailable."
    )


async def test_invoke_tool_rejects_invalid_payload_as_unavailable() -> None:
    outcome = await invoke_tool(
        StubClient({"unexpected": "payload"}), "example", {}, ExampleResult
    )

    assert outcome.status is ToolOutcomeStatus.UNAVAILABLE
    assert outcome.value is None
    assert outcome.safe_warning == (
        "example is currently unavailable; no result was invented."
    )
