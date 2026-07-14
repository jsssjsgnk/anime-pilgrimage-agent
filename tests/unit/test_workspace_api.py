"""Workspace API exposes progressive projections with namespace isolation."""

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from datetime import date, timedelta
from uuid import uuid4

import httpx
import pytest

from pilgrimage_agent.agent.mcp_client import FixtureAgentToolClient
from pilgrimage_agent.agent.workspace import WorkspaceAgent, WorkspaceStartRequest
from pilgrimage_agent.api import main as api_main
from pilgrimage_agent.domain.models import SubjectIntent, TripRequest
from pilgrimage_agent.memory.store import InMemoryProjectStore, ProjectStore
from pilgrimage_agent.rag.schemas import KnowledgeSearchResult, RetrievedEvidence


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
    knowledge_document_id = uuid4()
    knowledge_evidence = RetrievedEvidence(
        evidence_id="K-a1b2c3d4e5f6",
        chunk_id=uuid4(),
        document_id=knowledge_document_id,
        excerpt="Official closure notice for the selected place.",
        title="Official closure",
        source_type="official_notice",
        authority_level=5,
        accessed_at=date.today(),
        rrf_score=0.04,
        freshness="current",
    )

    class FakeKnowledgeRepository:
        async def search(self, _query: object) -> KnowledgeSearchResult:
            return KnowledgeSearchResult(
                status="sufficient_evidence", evidence=(knowledge_evidence,)
            )

    @asynccontextmanager
    async def fake_knowledge_repository() -> AsyncIterator[FakeKnowledgeRepository]:
        yield FakeKnowledgeRepository()

    monkeypatch.setattr(
        api_main, "_knowledge_repository", fake_knowledge_repository
    )
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
        status_message = await client.post(
            f"/api/workspaces/{trip_id}/messages",
            json={
                "owner_user_id": "user-a",
                "thread_id": "thread-a",
                "message": "目前进展如何?",
            },
        )
        restored_messages = await client.get(
            f"/api/workspaces/{trip_id}/messages",
            params={"owner_user_id": "user-a", "thread_id": "thread-a"},
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
        planned_body = planned.json()
        patch_preview = await client.post(
            f"/api/workspaces/{trip_id}/patches/parse",
            json={
                "owner_user_id": "user-a",
                "thread_id": "thread-a",
                "expected_base_version": planned_body["state_version"],
                "instruction": "把步行偏好设为 low",
                "idempotency_key": "api:walking-low",
            },
        )
        patch_id = patch_preview.json()["preview"]["patch"]["patch_id"]
        patch_applied = await client.post(
            f"/api/workspaces/{trip_id}/patches/{patch_id}/apply",
            json={
                "owner_user_id": "user-a",
                "thread_id": "thread-a",
                "confirm": False,
            },
        )
        after_patch = await client.get(
            f"/api/workspaces/{trip_id}",
            params={"owner_user_id": "user-a", "thread_id": "thread-a"},
        )
        after_patch_body = after_patch.json()
        blocked_place_id = after_patch_body["places"][0]["place_id"]
        rule_proposed = await client.post(
            f"/api/workspaces/{trip_id}/knowledge/rules/propose",
            json={
                "owner_user_id": "user-a",
                "thread_id": "thread-a",
                "question": "这个地点在行程日期是否关闭?",
                "proposal": {
                    "rule_type": "closure_date_range",
                    "target_refs": [
                        {"entity_type": "place", "entity_id": blocked_place_id}
                    ],
                    "value": {
                        "closed_from": start_date.isoformat(),
                        "closed_until": (start_date + timedelta(days=1)).isoformat(),
                    },
                    "evidence_ids": [knowledge_evidence.evidence_id],
                },
            },
        )
        rule_accepted = await client.post(
            f"/api/workspaces/{trip_id}/knowledge/rules/"
            f"{rule_proposed.json()['rule_id']}/accept",
            json={
                "owner_user_id": "user-a",
                "thread_id": "thread-a",
                "expected_base_version": after_patch_body["state_version"],
                "idempotency_key": "api:accept-closure-rule",
                "confirm": True,
            },
        )
        conversational_patch = await client.post(
            f"/api/workspaces/{trip_id}/messages",
            json={
                "owner_user_id": "user-a",
                "thread_id": "thread-a",
                "message": "把步行偏好设为 high",
            },
        )
        conversational_add = await client.post(
            f"/api/workspaces/{trip_id}/messages",
            json={
                "owner_user_id": "user-a",
                "thread_id": "thread-a",
                "message": "添加《莉可丽丝》",
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
    assert status_message.status_code == 200
    assert status_message.json()["preview"] is None
    assert "已确认 1 部作品" in status_message.json()["assistant_message"]["content"]
    assert restored_messages.status_code == 200
    assert [item["role"] for item in restored_messages.json()] == [
        "user",
        "assistant",
        "user",
        "assistant",
    ]
    assert stale.status_code == 409
    assert patch_preview.status_code == 200
    assert patch_preview.json()["preview"]["impact"]["validation_required"] is True
    assert patch_applied.status_code == 200
    assert patch_applied.json()["requirements"]["walking_preference"] == "low"
    assert patch_applied.json()["diffs"][-1]["changed_requirements"] == [
        "walking_preference"
    ]
    assert after_patch.json()["state_version"] == planned_body["state_version"] + 1
    assert rule_proposed.status_code == 200
    assert rule_proposed.json()["status"] == "proposed"
    assert rule_accepted.status_code == 200
    assert rule_accepted.json()["knowledge_rules"][-1]["status"] == "active_constraint"
    assert any(
        omission["place_id"] == blocked_place_id
        and omission["reason_code"] == "visit_window"
        for itinerary in rule_accepted.json()["itineraries"]
        for omission in itinerary["omissions"]
    )
    assert conversational_patch.status_code == 200
    assert conversational_patch.json()["preview"]["patch"]["operations"] == [
        {
            "op": "update_requirement",
            "field": "walking_preference",
            "value": "high",
        }
    ]
    assert conversational_add.status_code == 200
    assert conversational_add.json()["preview"]["patch"]["operations"][0][
        "action"
    ] == "add"
    assert conversational_add.json()["preview"]["patch"]["operations"][0][
        "intent"
    ]["query"] == "莉可丽丝"
    assert conversational_patch.json()["workspace"]["pending_patch_id"] is not None
    assistant_copy = conversational_patch.json()["assistant_message"]["content"]
    assert "PlanPatch" not in assistant_copy
    assert "itinerary_planner" not in assistant_copy
    assert [event.event_type for event in store.events[start_request.trip_id]] == [
        "workspace_started",
        "conversation_message",
        "conversation_message",
        "workspace_subjects_confirmed",
        "workspace_planned",
        "conversation_message",
        "conversation_message",
        "workspace_patch_proposed",
        "workspace_patch_applied",
        "workspace_knowledge_rule_proposed",
        "workspace_knowledge_rule_accepted",
        "conversation_message",
        "workspace_patch_proposed",
        "conversation_message",
        "conversation_message",
        "workspace_patch_proposed",
        "conversation_message",
    ]
