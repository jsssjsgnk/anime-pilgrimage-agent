"""Typed graph-facing outcomes for every read-only provider invocation."""

from __future__ import annotations

from collections.abc import Mapping
from enum import StrEnum
from typing import Protocol

from pydantic import BaseModel, Field, model_validator

from pilgrimage_agent.domain.models import DataProvenance, StrictModel
from pilgrimage_agent.providers.base import ProviderError, ProviderErrorKind


class StructuredToolClient(Protocol):
    async def call(self, name: str, arguments: Mapping[str, object]) -> dict[str, object]: ...


class ToolOutcomeStatus(StrEnum):
    OK = "ok"
    PARTIAL = "partial"
    UNAVAILABLE = "unavailable"
    STALE = "stale"
    RATE_LIMITED = "rate_limited"
    AUTH_ERROR = "auth_error"


class ToolOutcome[T: BaseModel](StrictModel):
    """Normalized value or safe failure; raw tool payloads never cross this boundary."""

    status: ToolOutcomeStatus
    value: T | None = None
    safe_warning: str | None = Field(default=None, max_length=500)
    provenance: DataProvenance | None = None
    retry_count: int = Field(default=0, ge=0, le=5)

    @model_validator(mode="after")
    def value_matches_status(self) -> ToolOutcome[T]:
        if self.status is ToolOutcomeStatus.OK and self.value is None:
            raise ValueError("successful tool outcomes require a value")
        if self.status not in {ToolOutcomeStatus.OK, ToolOutcomeStatus.PARTIAL} and self.value:
            raise ValueError("failed tool outcomes cannot carry a value")
        return self


def _failure_status(error: ProviderError) -> ToolOutcomeStatus:
    if error.kind in {ProviderErrorKind.QUOTA, ProviderErrorKind.RATE_LIMIT}:
        return ToolOutcomeStatus.RATE_LIMITED
    if error.kind is ProviderErrorKind.AUTH:
        return ToolOutcomeStatus.AUTH_ERROR
    if error.kind is ProviderErrorKind.PARTIAL_DATA:
        return ToolOutcomeStatus.PARTIAL
    return ToolOutcomeStatus.UNAVAILABLE


async def invoke_tool[T: BaseModel](
    client: StructuredToolClient,
    name: str,
    arguments: Mapping[str, object],
    output_schema: type[T],
) -> ToolOutcome[T]:
    """Invoke and validate one tool with consistent, value-safe degradation."""

    try:
        raw = await client.call(name, arguments)
        value = output_schema.model_validate(raw)
    except ProviderError as error:
        return ToolOutcome(
            status=_failure_status(error),
            safe_warning=f"{error.provider}: {error.safe_message}",
        )
    except (TimeoutError, RuntimeError, ValueError, TypeError):
        return ToolOutcome(
            status=ToolOutcomeStatus.UNAVAILABLE,
            safe_warning=f"{name} is currently unavailable; no result was invented.",
        )
    except Exception:
        # Third-party MCP adapters use their own exception classes. Normalize the
        # boundary without copying raw tool content, headers, or upstream details.
        return ToolOutcome(
            status=ToolOutcomeStatus.UNAVAILABLE,
            safe_warning=f"{name} is currently unavailable; no result was invented.",
        )
    provenance = getattr(value, "provenance", None)
    return ToolOutcome(
        status=ToolOutcomeStatus.OK,
        value=value,
        provenance=provenance if isinstance(provenance, DataProvenance) else None,
    )
