"""Namespace-safe implementations of the five project memory stores."""

from __future__ import annotations

from collections import defaultdict
from collections.abc import Sequence
from datetime import UTC, datetime
from typing import Any, Protocol, cast
from uuid import UUID, uuid4

from sqlalchemy import delete, select, text
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.engine import CursorResult
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from pilgrimage_agent.memory.schemas import (
    StoredEvent,
    StoredKnowledge,
    StoredPreference,
    StoredToolCache,
    StoredTrip,
)
from pilgrimage_agent.persistence import (
    KnowledgeRecord,
    ToolCacheRecord,
    TripEventRecord,
    TripRecord,
    UserPreferenceRecord,
)


class NamespaceViolation(LookupError):
    """A record exists but not inside the caller's explicit namespace."""


class ProjectStore(Protocol):
    async def save_trip(self, trip: StoredTrip) -> None: ...

    async def get_trip(
        self, owner_user_id: str, thread_id: str, trip_id: UUID
    ) -> StoredTrip | None: ...

    async def delete_trip(
        self,
        owner_user_id: str,
        thread_id: str,
        trip_id: UUID,
        *,
        checkpoint_thread_id: str | None = None,
    ) -> bool: ...

    async def append_event(
        self, owner_user_id: str, trip_id: UUID, event_type: str, payload: dict[str, object]
    ) -> StoredEvent: ...

    async def list_events(self, owner_user_id: str, trip_id: UUID) -> Sequence[StoredEvent]: ...

    async def save_preference(self, preference: StoredPreference) -> None: ...

    async def list_preferences(self, owner_user_id: str) -> Sequence[StoredPreference]: ...

    async def delete_preferences(self, owner_user_id: str) -> int: ...

    async def save_knowledge(self, document: StoredKnowledge) -> None: ...

    async def list_knowledge(
        self, owner_user_id: str, namespace: str
    ) -> Sequence[StoredKnowledge]: ...

    async def save_tool_cache(self, entry: StoredToolCache) -> None: ...

    async def get_tool_cache(self, fingerprint: str) -> StoredToolCache | None: ...


class InMemoryProjectStore:
    """Deterministic test store with the same isolation semantics as PostgreSQL."""

    def __init__(self) -> None:
        self.trips: dict[UUID, StoredTrip] = {}
        self.events: dict[UUID, list[StoredEvent]] = defaultdict(list)
        self.preferences: dict[tuple[str, str], StoredPreference] = {}
        self.knowledge: dict[UUID, StoredKnowledge] = {}
        self.tool_cache: dict[str, StoredToolCache] = {}

    async def save_trip(self, trip: StoredTrip) -> None:
        existing = self.trips.get(trip.trip_id)
        if existing and (existing.owner_user_id, existing.thread_id) != (
            trip.owner_user_id,
            trip.thread_id,
        ):
            raise NamespaceViolation("trip belongs to another namespace")
        self.trips[trip.trip_id] = trip

    async def get_trip(
        self, owner_user_id: str, thread_id: str, trip_id: UUID
    ) -> StoredTrip | None:
        trip = self.trips.get(trip_id)
        if trip and (trip.owner_user_id, trip.thread_id) == (owner_user_id, thread_id):
            return trip
        return None

    async def delete_trip(
        self,
        owner_user_id: str,
        thread_id: str,
        trip_id: UUID,
        *,
        checkpoint_thread_id: str | None = None,
    ) -> bool:
        del checkpoint_thread_id
        trip = self.trips.get(trip_id)
        if trip is None or (trip.owner_user_id, trip.thread_id) != (
            owner_user_id,
            thread_id,
        ):
            return False
        del self.trips[trip_id]
        self.events.pop(trip_id, None)
        return True

    async def append_event(
        self, owner_user_id: str, trip_id: UUID, event_type: str, payload: dict[str, object]
    ) -> StoredEvent:
        trip = self.trips.get(trip_id)
        if trip is None or trip.owner_user_id != owner_user_id:
            raise NamespaceViolation("trip event namespace is unavailable")
        event = StoredEvent(
            event_id=uuid4(),
            trip_id=trip_id,
            owner_user_id=owner_user_id,
            event_type=event_type,
            payload=payload,
            created_at=datetime.now(UTC),
        )
        self.events[trip_id].append(event)
        return event

    async def list_events(self, owner_user_id: str, trip_id: UUID) -> Sequence[StoredEvent]:
        return tuple(
            event for event in self.events[trip_id] if event.owner_user_id == owner_user_id
        )

    async def save_preference(self, preference: StoredPreference) -> None:
        if not preference.explicit_consent:
            raise ValueError("preferences require explicit opt-in")
        self.preferences[(preference.owner_user_id, preference.preference_key)] = preference

    async def list_preferences(self, owner_user_id: str) -> Sequence[StoredPreference]:
        return tuple(
            preference
            for (owner, _), preference in self.preferences.items()
            if owner == owner_user_id
        )

    async def delete_preferences(self, owner_user_id: str) -> int:
        keys = [key for key in self.preferences if key[0] == owner_user_id]
        for key in keys:
            del self.preferences[key]
        return len(keys)

    async def save_knowledge(self, document: StoredKnowledge) -> None:
        self.knowledge[document.document_id] = document

    async def list_knowledge(self, owner_user_id: str, namespace: str) -> Sequence[StoredKnowledge]:
        return tuple(
            document
            for document in self.knowledge.values()
            if (document.owner_user_id, document.namespace) == (owner_user_id, namespace)
        )

    async def save_tool_cache(self, entry: StoredToolCache) -> None:
        self.tool_cache[entry.fingerprint] = entry

    async def get_tool_cache(self, fingerprint: str) -> StoredToolCache | None:
        return self.tool_cache.get(fingerprint)


class SqlProjectStore:
    """PostgreSQL project store; every personal query includes its namespace."""

    def __init__(self, sessions: async_sessionmaker[AsyncSession]) -> None:
        self.sessions = sessions

    async def save_trip(self, trip: StoredTrip) -> None:
        async with self.sessions.begin() as session:
            existing = await session.get(TripRecord, trip.trip_id)
            if existing and (existing.owner_user_id, existing.thread_id) != (
                trip.owner_user_id,
                trip.thread_id,
            ):
                raise NamespaceViolation("trip belongs to another namespace")
            statement = insert(TripRecord).values(
                id=trip.trip_id,
                owner_user_id=trip.owner_user_id,
                thread_id=trip.thread_id,
                state=trip.state,
            )
            await session.execute(
                statement.on_conflict_do_update(
                    index_elements=[TripRecord.id], set_={"state": statement.excluded.state}
                )
            )

    async def get_trip(
        self, owner_user_id: str, thread_id: str, trip_id: UUID
    ) -> StoredTrip | None:
        async with self.sessions() as session:
            record = await session.scalar(
                select(TripRecord).where(
                    TripRecord.id == trip_id,
                    TripRecord.owner_user_id == owner_user_id,
                    TripRecord.thread_id == thread_id,
                )
            )
        if record is None:
            return None
        return StoredTrip(
            trip_id=record.id,
            owner_user_id=record.owner_user_id,
            thread_id=record.thread_id,
            state=record.state,
        )

    async def delete_trip(
        self,
        owner_user_id: str,
        thread_id: str,
        trip_id: UUID,
        *,
        checkpoint_thread_id: str | None = None,
    ) -> bool:
        """Delete one namespaced trip and its graph state in one DB transaction."""

        async with self.sessions.begin() as session:
            record = await session.scalar(
                select(TripRecord).where(
                    TripRecord.id == trip_id,
                    TripRecord.owner_user_id == owner_user_id,
                    TripRecord.thread_id == thread_id,
                )
            )
            if record is None:
                return False
            if checkpoint_thread_id is not None:
                params = {"thread_id": checkpoint_thread_id}
                for table in ("checkpoint_writes", "checkpoint_blobs", "checkpoints"):
                    await session.execute(
                        text(f"DELETE FROM {table} WHERE thread_id = :thread_id"),  # noqa: S608
                        params,
                    )
            await session.delete(record)
        return True

    async def append_event(
        self, owner_user_id: str, trip_id: UUID, event_type: str, payload: dict[str, object]
    ) -> StoredEvent:
        async with self.sessions.begin() as session:
            trip = await session.scalar(
                select(TripRecord).where(
                    TripRecord.id == trip_id, TripRecord.owner_user_id == owner_user_id
                )
            )
            if trip is None:
                raise NamespaceViolation("trip event namespace is unavailable")
            record = TripEventRecord(
                owner_user_id=owner_user_id,
                trip_id=trip_id,
                event_type=event_type,
                payload=payload,
            )
            session.add(record)
            await session.flush()
            await session.refresh(record, attribute_names=["created_at"])
            return StoredEvent(
                event_id=record.id,
                trip_id=trip_id,
                owner_user_id=owner_user_id,
                event_type=event_type,
                payload=payload,
                created_at=record.created_at,
            )

    async def list_events(self, owner_user_id: str, trip_id: UUID) -> Sequence[StoredEvent]:
        async with self.sessions() as session:
            records = (
                await session.scalars(
                    select(TripEventRecord)
                    .where(
                        TripEventRecord.owner_user_id == owner_user_id,
                        TripEventRecord.trip_id == trip_id,
                    )
                    .order_by(TripEventRecord.created_at)
                )
            ).all()
        return tuple(
            StoredEvent(
                event_id=record.id,
                trip_id=record.trip_id,
                owner_user_id=record.owner_user_id,
                event_type=record.event_type,
                payload=record.payload,
                created_at=record.created_at,
            )
            for record in records
        )

    async def save_preference(self, preference: StoredPreference) -> None:
        if not preference.explicit_consent:
            raise ValueError("preferences require explicit opt-in")
        async with self.sessions.begin() as session:
            statement = insert(UserPreferenceRecord).values(
                owner_user_id=preference.owner_user_id,
                preference_key=preference.preference_key,
                value=preference.value,
                explicit_consent=True,
            )
            await session.execute(
                statement.on_conflict_do_update(
                    constraint="uq_preference_namespace_key",
                    set_={"value": statement.excluded.value, "explicit_consent": True},
                )
            )

    async def list_preferences(self, owner_user_id: str) -> Sequence[StoredPreference]:
        async with self.sessions() as session:
            records = (
                await session.scalars(
                    select(UserPreferenceRecord).where(
                        UserPreferenceRecord.owner_user_id == owner_user_id,
                        UserPreferenceRecord.explicit_consent.is_(True),
                    )
                )
            ).all()
        return tuple(
            StoredPreference(
                owner_user_id=record.owner_user_id,
                preference_key=record.preference_key,
                value=record.value,
                explicit_consent=record.explicit_consent,
            )
            for record in records
        )

    async def delete_preferences(self, owner_user_id: str) -> int:
        async with self.sessions.begin() as session:
            result = cast(
                CursorResult[Any],
                await session.execute(
                    delete(UserPreferenceRecord).where(
                        UserPreferenceRecord.owner_user_id == owner_user_id
                    )
                ),
            )
            return result.rowcount or 0

    async def save_knowledge(self, document: StoredKnowledge) -> None:
        async with self.sessions.begin() as session:
            session.add(
                KnowledgeRecord(
                    id=document.document_id,
                    owner_user_id=document.owner_user_id,
                    namespace=document.namespace,
                    source_url=document.source_url,
                    document_metadata=document.document_metadata,
                )
            )

    async def list_knowledge(self, owner_user_id: str, namespace: str) -> Sequence[StoredKnowledge]:
        async with self.sessions() as session:
            records = (
                await session.scalars(
                    select(KnowledgeRecord).where(
                        KnowledgeRecord.owner_user_id == owner_user_id,
                        KnowledgeRecord.namespace == namespace,
                    )
                )
            ).all()
        return tuple(
            StoredKnowledge(
                document_id=record.id,
                owner_user_id=record.owner_user_id,
                namespace=record.namespace,
                source_url=record.source_url,
                document_metadata=record.document_metadata,
            )
            for record in records
        )

    async def save_tool_cache(self, entry: StoredToolCache) -> None:
        async with self.sessions.begin() as session:
            statement = insert(ToolCacheRecord).values(**entry.model_dump(mode="python"))
            await session.execute(
                statement.on_conflict_do_update(
                    index_elements=[ToolCacheRecord.fingerprint],
                    set_={
                        "normalized_payload": statement.excluded.normalized_payload,
                        "provenance": statement.excluded.provenance,
                        "expires_at": statement.excluded.expires_at,
                    },
                )
            )

    async def get_tool_cache(self, fingerprint: str) -> StoredToolCache | None:
        async with self.sessions() as session:
            record = await session.get(ToolCacheRecord, fingerprint)
        if record is None:
            return None
        return StoredToolCache(
            fingerprint=record.fingerprint,
            provider=record.provider,
            normalized_payload=record.normalized_payload,
            provenance=record.provenance,
            expires_at=record.expires_at,
        )
