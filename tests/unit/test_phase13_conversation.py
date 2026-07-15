"""Durable bounded conversation behavior and namespace-safe HTTP recovery."""

# ruff: noqa: RUF001 -- Chinese test inputs preserve realistic punctuation.

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from uuid import uuid4

import httpx
from pytest import MonkeyPatch

from pilgrimage_agent.agent.conversation import (
    ConversationContext,
    DeterministicConversationAgent,
    ResilientConversationAgent,
)
from pilgrimage_agent.agent.schemas import (
    ConfirmationRequest,
    ConversationDecision,
    ConversationEventPayload,
    ConversationIntent,
    ConversationMessage,
    WorkflowResponse,
    WorkflowStatus,
)
from pilgrimage_agent.api import main as api_main
from pilgrimage_agent.memory.schemas import StoredTrip
from pilgrimage_agent.memory.store import InMemoryProjectStore


def waiting_context() -> ConversationContext:
    return ConversationContext(
        phase="requirements_confirmation",
        status="waiting_confirmation",
        pending_confirmation="requirements",
        route_a_point_count=0,
        route_b_day_count=0,
        daily_walking_meters=(),
        weather_summary=(),
        evidence_count=0,
        omitted_point_count=0,
        warning_summary=(),
        validation_summary=(),
        revision_count=0,
    )


async def test_deterministic_agent_supports_questions_and_typed_changes() -> None:
    agent = DeterministicConversationAgent()

    help_result = await agent.respond(waiting_context(), (), "下一步怎么继续？")
    change_result = await agent.respond(
        waiting_context().model_copy(
            update={"pending_confirmation": None, "route_b_day_count": 3}
        ),
        (),
        "第二天少走 25%，其他天别动",
    )

    assert help_result.intent is ConversationIntent.CONFIRMATION_HELP
    assert "不会替你静默确认" in help_result.answer
    assert change_result.intent is ConversationIntent.MODIFY_PLAN
    assert change_result.modification is not None
    assert change_result.modification.target_day == 2
    assert change_result.modification.walking_reduction_percent == 25


async def test_recognized_safe_intent_does_not_wait_for_llm() -> None:
    class UnexpectedLlm:
        async def respond(
            self,
            context: ConversationContext,
            recent_messages: tuple[ConversationMessage, ...],
            message: str,
            *,
            memory_summary: str | None = None,
            critical_decisions: tuple[str, ...] = (),
        ) -> ConversationDecision:
            del context, recent_messages, message, memory_summary, critical_decisions
            raise AssertionError("recognized modifications must not call the LLM")

    agent = ResilientConversationAgent(UnexpectedLlm())
    result = await agent.respond(
        waiting_context().model_copy(update={"pending_confirmation": None}),
        (),
        "第二天少走 20%",
    )

    assert result.intent is ConversationIntent.MODIFY_PLAN
    assert result.modification is not None


async def test_conversation_api_persists_and_recovers_only_inside_namespace(
    monkeypatch: MonkeyPatch,
) -> None:
    store = InMemoryProjectStore()
    trip_id = uuid4()
    workflow = WorkflowResponse(
        trip_id=trip_id,
        thread_id="thread-a",
        status=WorkflowStatus.WAITING,
        phase="requirements_confirmation",
        pending_confirmation=ConfirmationRequest(
            kind="requirements",
            title="Confirm requirements",
            summary="Review every critical field.",
            requires_explicit_choice=True,
        ),
    )
    await store.save_trip(
        StoredTrip(
            trip_id=trip_id,
            owner_user_id="user-a",
            thread_id="thread-a",
            state=workflow.model_dump(mode="json"),
        )
    )

    @asynccontextmanager
    async def fake_conversation_runtime(
    ) -> AsyncIterator[tuple[DeterministicConversationAgent, InMemoryProjectStore]]:
        yield DeterministicConversationAgent(), store

    @asynccontextmanager
    async def fake_store() -> AsyncIterator[InMemoryProjectStore]:
        yield store

    monkeypatch.setattr(api_main, "_conversation_runtime", fake_conversation_runtime)
    monkeypatch.setattr(api_main, "_project_store", fake_store)

    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=api_main.app), base_url="http://test"
    ) as client:
        sent = await client.post(
            f"/api/workflows/{trip_id}/messages",
            json={
                "owner_user_id": "user-a",
                "thread_id": "thread-a",
                "message": "现在进度如何？",
            },
        )
        recovered = await client.get(
            f"/api/workflows/{trip_id}/messages",
            params={"owner_user_id": "user-a", "thread_id": "thread-a"},
        )
        isolated = await client.get(
            f"/api/workflows/{trip_id}/messages",
            params={"owner_user_id": "user-a", "thread_id": "thread-b"},
        )

    assert sent.status_code == 200
    assert [item["role"] for item in sent.json()["messages"]] == ["user", "assistant"]
    assert sent.json()["assistant_message"]["intent"] == "status"
    assert len(recovered.json()) == 2
    assert recovered.json()[0]["created_at"]
    assert isolated.status_code == 404


async def test_conversation_compaction_keeps_traceable_hard_constraints() -> None:
    store = InMemoryProjectStore()
    trip_id = uuid4()
    await store.save_trip(
        StoredTrip(
            trip_id=trip_id,
            owner_user_id="user-a",
            thread_id="thread-a",
            state={},
        )
    )
    for index in range(26):
        content = (
            "这次每天必须少走路，不要自动补地点"
            if index == 0
            else f"普通对话第 {index} 条"
        )
        await api_main._append_conversation_message(
            store,
            "user-a",
            trip_id,
            ConversationEventPayload(
                role="user",
                content=content,
                intent=ConversationIntent.GENERAL,
            ),
        )

    events = await store.list_events("user-a", trip_id)
    summaries = [
        api_main._conversation_summary(event)
        for event in events
        if event.event_type == api_main.CONVERSATION_SUMMARY_EVENT
    ]
    window = await api_main._conversation_prompt_window(store, "user-a", trip_id)

    assert summaries and summaries[-1] is not None
    assert summaries[-1].summarized_message_count == 16
    assert summaries[-1].source_first_message_id
    assert summaries[-1].through_message_id
    assert "这次每天必须少走路，不要自动补地点" in window.critical_decisions
    assert len(window.recent_messages) == 8
    assert window.summary is not None
