"""Normalized provider errors and reusable request policy."""

from dataclasses import dataclass
from enum import StrEnum
from typing import Protocol


class ProviderErrorKind(StrEnum):
    VALIDATION = "validation"
    AUTH = "auth"
    QUOTA = "quota"
    RATE_LIMIT = "rate_limit"
    TIMEOUT = "timeout"
    UPSTREAM = "upstream"
    NOT_FOUND = "not_found"
    PARTIAL_DATA = "partial_data"


@dataclass(slots=True)
class ProviderError(Exception):
    kind: ProviderErrorKind
    provider: str
    safe_message: str
    retryable: bool = False

    def __str__(self) -> str:
        return f"{self.provider}: {self.kind.value}: {self.safe_message}"


class Provider[Q_contra, T_co](Protocol):
    """All providers expose one typed, read-only query boundary."""

    async def fetch(self, query: Q_contra) -> T_co:
        """Return validated normalized data or a normalized error."""
        ...
