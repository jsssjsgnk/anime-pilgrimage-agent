"""Strict schemas for project-owned memory records."""

from datetime import UTC, datetime
from uuid import UUID

from pydantic import Field

from pilgrimage_agent.domain.models import StrictModel


class StoredTrip(StrictModel):
    trip_id: UUID
    owner_user_id: str = Field(min_length=1, max_length=120)
    thread_id: str = Field(min_length=1, max_length=120)
    state: dict[str, object]


class StoredEvent(StrictModel):
    event_id: UUID
    trip_id: UUID
    owner_user_id: str
    event_type: str = Field(min_length=1, max_length=80)
    payload: dict[str, object]
    created_at: datetime = Field(default_factory=lambda: datetime.now(UTC))


class StoredPreference(StrictModel):
    owner_user_id: str
    preference_key: str = Field(min_length=1, max_length=80)
    value: dict[str, object]
    explicit_consent: bool


class StoredKnowledge(StrictModel):
    document_id: UUID
    owner_user_id: str
    namespace: str
    source_url: str | None = None
    document_metadata: dict[str, object]


class StoredToolCache(StrictModel):
    fingerprint: str = Field(min_length=16, max_length=128)
    provider: str = Field(min_length=1, max_length=80)
    normalized_payload: dict[str, object]
    provenance: dict[str, object]
    expires_at: datetime
