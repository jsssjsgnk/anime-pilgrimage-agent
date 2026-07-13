"""Shared provider normalization helpers."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

from pilgrimage_agent.domain.models import DataProvenance, DataStatus


def provenance(
    provider: str,
    source_url: str | None,
    *,
    ttl: timedelta,
    status: DataStatus = DataStatus.LIVE,
    now: datetime | None = None,
) -> DataProvenance:
    fetched_at = now or datetime.now(UTC)
    return DataProvenance(
        provider=provider,
        source_url=source_url,
        fetched_at=fetched_at,
        expires_at=fetched_at + ttl,
        status=status,
    )

