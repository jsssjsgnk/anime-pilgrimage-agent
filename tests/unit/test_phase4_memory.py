"""Five-store namespace, opt-in, and deletion behavior."""

from datetime import UTC, datetime, timedelta
from uuid import uuid4

import pytest

from pilgrimage_agent.memory.schemas import (
    StoredKnowledge,
    StoredPreference,
    StoredToolCache,
    StoredTrip,
)
from pilgrimage_agent.memory.store import InMemoryProjectStore, NamespaceViolation


async def test_trip_and_event_namespaces_do_not_leak() -> None:
    store = InMemoryProjectStore()
    trip_id = uuid4()
    await store.save_trip(
        StoredTrip(
            trip_id=trip_id,
            owner_user_id="user-a",
            thread_id="thread-a",
            state={"phase": "requirement"},
        )
    )
    await store.append_event("user-a", trip_id, "created", {"safe": True})
    assert await store.get_trip("user-a", "thread-a", trip_id) is not None
    assert await store.get_trip("user-b", "thread-a", trip_id) is None
    assert len(await store.list_events("user-b", trip_id)) == 0
    with pytest.raises(NamespaceViolation):
        await store.append_event("user-b", trip_id, "read", {})


async def test_preferences_are_opt_in_and_deletable() -> None:
    store = InMemoryProjectStore()
    preference = StoredPreference(
        owner_user_id="user-a",
        preference_key="walking",
        value={"level": "low"},
        explicit_consent=False,
    )
    with pytest.raises(ValueError, match="explicit opt-in"):
        await store.save_preference(preference)
    await store.save_preference(preference.model_copy(update={"explicit_consent": True}))
    assert len(await store.list_preferences("user-a")) == 1
    assert len(await store.list_preferences("user-b")) == 0
    assert await store.delete_preferences("user-a") == 1
    assert await store.list_preferences("user-a") == ()


async def test_knowledge_and_cache_are_separate_stores() -> None:
    store = InMemoryProjectStore()
    document = StoredKnowledge(
        document_id=uuid4(),
        owner_user_id="user-a",
        namespace="trip-a",
        document_metadata={"title": "Access note"},
    )
    await store.save_knowledge(document)
    assert await store.list_knowledge("user-a", "trip-a") == (document,)
    assert await store.list_knowledge("user-a", "trip-b") == ()

    entry = StoredToolCache(
        fingerprint="a" * 64,
        provider="fixture",
        normalized_payload={"value": 1},
        provenance={"status": "cached"},
        expires_at=datetime.now(UTC) + timedelta(minutes=5),
    )
    await store.save_tool_cache(entry)
    assert await store.get_tool_cache(entry.fingerprint) == entry
