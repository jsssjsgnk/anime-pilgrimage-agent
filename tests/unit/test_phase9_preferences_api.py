"""Product-visible preference lifecycle through the HTTP boundary."""

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

import httpx
from pytest import MonkeyPatch

from pilgrimage_agent.api import main as api_main
from pilgrimage_agent.memory.store import InMemoryProjectStore


async def test_preferences_require_consent_and_support_view_edit_delete(
    monkeypatch: MonkeyPatch,
) -> None:
    store = InMemoryProjectStore()

    @asynccontextmanager
    async def fake_store() -> AsyncIterator[InMemoryProjectStore]:
        yield store

    monkeypatch.setattr(api_main, "_project_store", fake_store)
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=api_main.app), base_url="http://test"
    ) as client:
        saved = await client.put(
            "/api/preferences/max_walking_meters_per_day",
            json={
                "owner_user_id": "preference-user",
                "value": 4200,
                "explicit_consent": True,
            },
        )
        listed = await client.get(
            "/api/preferences", params={"owner_user_id": "preference-user"}
        )
        deleted = await client.delete(
            "/api/preferences", params={"owner_user_id": "preference-user"}
        )

    assert saved.status_code == 200
    assert saved.json()["value"] == {"value": 4200.0}
    assert len(listed.json()) == 1
    assert deleted.json() == {"deleted_count": 1}
