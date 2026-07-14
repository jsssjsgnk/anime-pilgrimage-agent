"""Workspace API exposes progressive projections with namespace isolation."""

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from datetime import date, timedelta

import httpx
import pytest

from pilgrimage_agent.agent.mcp_client import FixtureAgentToolClient
from pilgrimage_agent.agent.workspace import WorkspaceAgent, WorkspaceStartRequest
from pilgrimage_agent.api import main as api_main
from pilgrimage_agent.domain.models import SubjectIntent, TripRequest
from pilgrimage_agent.memory.store import InMemoryProjectStore, ProjectStore


@pytest.mark.asyncio
async def test_workspace_api_start_confirm_plan_and_evidence_projection(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    store = InMemoryProjectStore()
    agent = WorkspaceAgent(FixtureAgentToolClient())

    @asynccontextmanager
    async def fake_workspace_runtime(
    ) -> AsyncIterator[tuple[WorkspaceAgent, ProjectStore]]:
        yield agent, store

    monkeypatch.setattr(api_main, "_workspace_runtime", fake_workspace_runtime)
    start_date = date.today() + timedelta(days=40)
    start_request = WorkspaceStartRequest(
        owner_user_id="user-a",
        thread_id="thread-a",
        request_summary="两天巡礼《孤独摇滚》。",
        requirements=TripRequest(
            origin="京都",
            destination="东京",
            start_date=start_date,
            end_date=start_date + timedelta(days=1),
            anime_query="孤独摇滚",
            subject_intents=(
                SubjectIntent(query="孤独摇滚", priority=5, is_primary=True),
            ),
        ),
    )

    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=api_main.app), base_url="http://test"
    ) as client:
        started = await client.post(
            "/api/workspaces", json=start_request.model_dump(mode="json")
        )
        started_body = started.json()
        trip_id = started_body["trip_id"]
        group = started_body["subject_groups"][0]
        confirmed = await client.post(
            f"/api/workspaces/{trip_id}/subjects/confirm",
            json={
                "owner_user_id": "user-a",
                "thread_id": "thread-a",
                "expected_state_version": started_body["state_version"],
                "confirmations": [
                    {
                        "intent_id": group["intent"]["intent_id"],
                        "decision": "accept",
                        "selected_subject_id": group["candidates"][0]["subject_id"],
                    }
                ],
            },
        )
        confirmed_body = confirmed.json()
        recovered = await client.get(
            f"/api/workspaces/{trip_id}",
            params={"owner_user_id": "user-a", "thread_id": "thread-a"},
        )
        isolated = await client.get(
            f"/api/workspaces/{trip_id}",
            params={"owner_user_id": "user-a", "thread_id": "thread-b"},
        )
        evidence = await client.get(
            f"/api/workspaces/{trip_id}/evidence",
            params={"owner_user_id": "user-a", "thread_id": "thread-a"},
        )
        planned = await client.post(
            f"/api/workspaces/{trip_id}/plan",
            json={
                "owner_user_id": "user-a",
                "thread_id": "thread-a",
                "expected_state_version": confirmed_body["state_version"],
                "base_id": confirmed_body["base_candidates"][0]["base_id"],
            },
        )
        stale = await client.post(
            f"/api/workspaces/{trip_id}/plan",
            json={
                "owner_user_id": "user-a",
                "thread_id": "thread-a",
                "expected_state_version": confirmed_body["state_version"],
                "base_id": confirmed_body["base_candidates"][0]["base_id"],
            },
        )

    assert started.status_code == 200
    assert "evidence" not in started_body
    assert confirmed.status_code == 200
    assert confirmed_body["counts"]["raw_scene_records"] == 3
    assert confirmed_body["counts"]["canonical_places"] >= 1
    assert recovered.status_code == 200
    assert isolated.status_code == 404
    assert evidence.status_code == 200
    assert len(evidence.json()["evidence"]) == 3
    assert planned.status_code == 200
    assert len(planned.json()["itineraries"]) == 2
    assert stale.status_code == 409
    assert [event.event_type for event in store.events[start_request.trip_id]] == [
        "workspace_started",
        "workspace_subjects_confirmed",
        "workspace_planned",
    ]
