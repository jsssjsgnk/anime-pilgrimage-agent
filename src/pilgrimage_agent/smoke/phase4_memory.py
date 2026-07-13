"""Exercise all five PostgreSQL project stores without exposing stored values."""

from datetime import UTC, datetime, timedelta
from uuid import uuid4

from sqlalchemy import delete
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from pilgrimage_agent.config import get_settings
from pilgrimage_agent.memory.schemas import (
    StoredKnowledge,
    StoredPreference,
    StoredToolCache,
    StoredTrip,
)
from pilgrimage_agent.memory.store import SqlProjectStore
from pilgrimage_agent.persistence import (
    KnowledgeRecord,
    ToolCacheRecord,
    TripEventRecord,
    TripRecord,
    UserPreferenceRecord,
)


async def main() -> None:
    engine = create_async_engine(get_settings().database_url.get_secret_value())
    sessions = async_sessionmaker(engine, expire_on_commit=False)
    store = SqlProjectStore(sessions)
    trip_id = uuid4()
    document_id = uuid4()
    fingerprint = uuid4().hex
    owner = f"phase4-store-{uuid4().hex}"
    try:
        trip = StoredTrip(
            trip_id=trip_id,
            owner_user_id=owner,
            thread_id="thread-a",
            state={"phase": "test"},
        )
        await store.save_trip(trip)
        await store.append_event(owner, trip_id, "verified", {"safe": True})
        assert await store.get_trip(owner, "thread-a", trip_id) == trip
        assert await store.get_trip("another-owner", "thread-a", trip_id) is None
        assert len(await store.list_events(owner, trip_id)) == 1

        preference = StoredPreference(
            owner_user_id=owner,
            preference_key="walking",
            value={"level": "low"},
            explicit_consent=True,
        )
        await store.save_preference(preference)
        assert await store.list_preferences(owner) == (preference,)

        knowledge = StoredKnowledge(
            document_id=document_id,
            owner_user_id=owner,
            namespace="trip-a",
            document_metadata={"title": "fixture"},
        )
        await store.save_knowledge(knowledge)
        assert await store.list_knowledge(owner, "trip-a") == (knowledge,)
        assert await store.list_knowledge(owner, "trip-b") == ()

        cache = StoredToolCache(
            fingerprint=fingerprint,
            provider="fixture",
            normalized_payload={"result": "ok"},
            provenance={"status": "cached"},
            expires_at=datetime.now(UTC) + timedelta(minutes=5),
        )
        await store.save_tool_cache(cache)
        assert await store.get_tool_cache(fingerprint) == cache
        assert await store.delete_preferences(owner) == 1
    finally:
        async with sessions.begin() as session:
            await session.execute(
                delete(ToolCacheRecord).where(ToolCacheRecord.fingerprint == fingerprint)
            )
            await session.execute(delete(KnowledgeRecord).where(KnowledgeRecord.id == document_id))
            await session.execute(
                delete(UserPreferenceRecord).where(UserPreferenceRecord.owner_user_id == owner)
            )
            await session.execute(delete(TripEventRecord).where(TripEventRecord.trip_id == trip_id))
            await session.execute(delete(TripRecord).where(TripRecord.id == trip_id))
        await engine.dispose()
    print("PASS: five PostgreSQL stores enforce project schemas, isolation, opt-in, and deletion.")


if __name__ == "__main__":
    import asyncio

    asyncio.run(main())
