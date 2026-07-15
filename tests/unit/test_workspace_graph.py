"""The product Workspace is checkpointed and reviewed by its real graph."""

import asyncio
from collections.abc import Mapping
from datetime import UTC, date, datetime, timedelta
from typing import cast
from uuid import NAMESPACE_URL, UUID, uuid4, uuid5

import pytest
from langchain_core.runnables import RunnableConfig
from langgraph.checkpoint.memory import InMemorySaver
from langgraph.types import Command, Interrupt

from pilgrimage_agent.agent.mcp_client import FixtureAgentToolClient
from pilgrimage_agent.agent.schemas import (
    ReviewerInput,
    ReviewerOutput,
    WorkspaceReplannerInput,
    WorkspaceReplannerOutput,
)
from pilgrimage_agent.agent.workspace import (
    ConfirmWorkspaceSubjectsRequest,
    PlanWorkspaceRequest,
    SubjectConfirmation,
    WorkspaceAgent,
    WorkspaceStartRequest,
    WorkspaceState,
    WorkspaceStatus,
)
from pilgrimage_agent.agent.workspace_graph import (
    WorkspaceGraphState,
    _handoff_time,
    build_workspace_graph,
)
from pilgrimage_agent.domain.models import (
    ConfirmedSubject,
    GeoCoordinate,
    SubjectIntent,
    TripRequest,
)
from pilgrimage_agent.domain.workspace import (
    AgentHandoff,
    AgentRole,
    SubjectAppearance,
    VisitPlace,
)
from pilgrimage_agent.rag.rules import (
    KnowledgeRuleProposal,
    KnowledgeRuleProposalBatch,
    KnowledgeRuleProposalInput,
)
from pilgrimage_agent.rag.schemas import KnowledgeSearchResult, RetrievedEvidence


def test_handoff_transition_time_never_precedes_lifecycle_bounds() -> None:
    created_at = datetime.now(UTC) + timedelta(seconds=2)
    pending = AgentHandoff(
        run_id=uuid4(),
        sender=AgentRole.SUBJECT,
        receiver=AgentRole.EVIDENCE_COLLECTOR,
        task_type="collect_fixture",
        goal="Exercise monotonic handoff timestamps.",
        input_refs=(),
        expected_output_schema="Fixture",
        status="pending",
        created_at=created_at,
    )
    started_at = _handoff_time(pending)
    assert started_at >= created_at
    running = pending.model_copy(update={"status": "running", "started_at": started_at})
    assert _handoff_time(running, terminal=True) >= started_at


class CountingReviewer:
    def __init__(self, *, revise: bool = False) -> None:
        self.calls: list[ReviewerInput] = []
        self.revise = revise
        self.active_calls = 0
        self.max_active_calls = 0

    async def review(self, request: ReviewerInput) -> ReviewerOutput:
        self.calls.append(request)
        should_revise = self.revise and len(self.calls) == 1
        self.active_calls += 1
        self.max_active_calls = max(self.max_active_calls, self.active_calls)
        try:
            await asyncio.sleep(0.005)
            if should_revise:
                return ReviewerOutput(
                    action="revise",
                    target_day=1,
                    explanation="Inspect only day one and preserve every stable day.",
                )
            return ReviewerOutput(
                action="accept", explanation="The bounded plan is coherent."
            )
        finally:
            self.active_calls -= 1


class TargetedReplanner:
    def __init__(self) -> None:
        self.calls: list[WorkspaceReplannerInput] = []

    async def replan(
        self, request: WorkspaceReplannerInput
    ) -> WorkspaceReplannerOutput:
        self.calls.append(request)
        return WorkspaceReplannerOutput(
            action="apply_targeted_revision",
            target_day=request.target_day,
            explanation="Apply only the bounded target-day repair.",
        )


class FixtureKnowledgeRetriever:
    async def retrieve(
        self,
        *,
        owner_user_id: str,
        trip_id: UUID,
        request: TripRequest,
        subject: ConfirmedSubject,
    ) -> KnowledgeSearchResult:
        del owner_user_id, trip_id, request, subject
        return KnowledgeSearchResult(
            status="sufficient_evidence",
            evidence=(
                RetrievedEvidence(
                    evidence_id="K-a1b2c3d4e5f6",
                    chunk_id=uuid4(),
                    document_id=uuid4(),
                    excerpt="Official fixture asks visitors to avoid photography here.",
                    title="Official visitor notice",
                    source_type="official_notice",
                    authority_level=5,
                    accessed_at=date.today(),
                    rrf_score=0.03,
                    freshness="current",
                ),
            ),
        )


class FixtureKnowledgeRuleProposer:
    async def propose(
        self, request: KnowledgeRuleProposalInput
    ) -> KnowledgeRuleProposalBatch:
        target = next(
            item for item in request.allowed_target_refs if item.entity_type == "place"
        )
        return KnowledgeRuleProposalBatch(
            proposals=(
                KnowledgeRuleProposal(
                    rule_type="photography_restriction",
                    target_refs=(target,),
                    value={"photography_allowed": False},
                    evidence_ids=(request.evidence[0].evidence_id,),
                ),
            )
        )


class RecordingFixtureTools(FixtureAgentToolClient):
    def __init__(self) -> None:
        super().__init__()
        self.calls: list[tuple[str, dict[str, object]]] = []
        self.active_calls = 0
        self.max_active_calls = 0

    async def call(
        self, name: str, arguments: Mapping[str, object]
    ) -> dict[str, object]:
        self.calls.append((name, dict(arguments)))
        self.active_calls += 1
        self.max_active_calls = max(self.max_active_calls, self.active_calls)
        try:
            await asyncio.sleep(0.005)
            if name == "geocode_place":
                provenance = {
                    "provider": "fixture-geocoder",
                    "fetched_at": datetime.now(UTC).isoformat(),
                    "status": "estimated",
                }
                return {
                    "candidates": (
                        {
                            "label": "新宿",
                            "coordinate": {
                                "latitude": 35.6909,
                                "longitude": 139.7003,
                            },
                            "provenance": provenance,
                        },
                    ),
                    "provenance": provenance,
                }
            return await super().call(name, arguments)
        finally:
            self.active_calls -= 1


def _start_request() -> WorkspaceStartRequest:
    start = date.today() + timedelta(days=45)
    return WorkspaceStartRequest(
        owner_user_id="graph-user",
        thread_id="graph-thread",
        request_summary="用两天巡礼《孤独摇滚》, 少走路。",
        requirements=TripRequest(
            origin="京都",
            destination="东京",
            base_preference="新宿",
            start_date=start,
            end_date=start + timedelta(days=1),
            subject_intents=(
                SubjectIntent(query="孤独摇滚", priority=5, is_primary=True),
            ),
            walking_preference="low",
        ),
    )


def _config() -> RunnableConfig:
    return {"configurable": {"thread_id": "workspace-graph-test"}}


def _workspace(result: object) -> WorkspaceState:
    state = cast(WorkspaceGraphState, result)
    return WorkspaceState.model_validate(state["workspace"])


def _interrupt_kind(result: object) -> str:
    raw = cast(dict[str, object], result)
    interrupts = cast(tuple[Interrupt, ...], raw["__interrupt__"])
    value = cast(dict[str, object], interrupts[0].value)
    return cast(str, value["kind"])


def _area_place(key: str, latitude: float) -> VisitPlace:
    evidence_id = uuid5(NAMESPACE_URL, f"workspace-area-evidence:{key}")
    return VisitPlace(
        place_id=uuid5(NAMESPACE_URL, f"workspace-area-place:{key}"),
        canonical_name=key,
        coordinate=GeoCoordinate(latitude=latitude, longitude=139.668),
        verification_status="community",
        scene_evidence_ids=(evidence_id,),
        subject_appearances=(
            SubjectAppearance(subject_id="328609", evidence_ids=(evidence_id,)),
        ),
        merge_confidence=1,
        resolution_version="fixture-v1",
        provenance_label="fixture",
    )


@pytest.mark.asyncio
async def test_area_builder_adds_bounded_transit_edges_between_nearby_areas() -> None:
    tools = RecordingFixtureTools()
    agent = WorkspaceAgent(tools)
    start = date.today() + timedelta(days=5)
    state = WorkspaceState(
        owner_user_id="area-user",
        thread_id="area-thread",
        trip_id=UUID(int=999),
        request_summary="two nearby travel areas",
        state_version=1,
        status=WorkspaceStatus.READY,
        requirements=TripRequest(
            origin="Kyoto",
            destination="Tokyo",
            start_date=start,
            end_date=start,
            subject_intents=(SubjectIntent(query="Bocchi", is_primary=True),),
            transit_route_preference="fewer_transfers",
        ),
        subject_groups=(),
        places=(_area_place("west", 35.66), _area_place("east", 35.68)),
    )

    coarse = agent.build_travel_areas(state)
    calibrated = await agent.calibrate_travel_areas(coarse)

    assert len(calibrated.areas) == 2
    assert len(calibrated.area_transit_edges) == 1
    assert calibrated.area_transit_edges[0].duration_seconds == 2520
    assert any(item.kind == "area_transit" for item in calibrated.provider_snapshots)
    transit_arguments = next(
        arguments for name, arguments in tools.calls if name == "search_transit_options"
    )
    assert transit_arguments["route"] == "fewer_transfers"


@pytest.mark.asyncio
async def test_workspace_graph_resumes_checkpoint_and_calls_reviewer() -> None:
    saver = InMemorySaver()
    reviewer = CountingReviewer()
    tools = RecordingFixtureTools()
    agent = WorkspaceAgent(
        tools,
        knowledge_retriever=FixtureKnowledgeRetriever(),
        knowledge_rule_proposer=FixtureKnowledgeRuleProposer(),
    )
    graph = build_workspace_graph(
        agent, saver, reviewer=reviewer, reviewer_source="fixture"
    )
    request = _start_request()
    first = await graph.ainvoke(
        {"start_request": request.model_dump(mode="json")}, _config()
    )
    assert _interrupt_kind(first) == "subjects"
    initial = _workspace(first)
    group = initial.subject_groups[0]

    second = await graph.ainvoke(
        Command(
            resume=ConfirmWorkspaceSubjectsRequest(
                owner_user_id=request.owner_user_id,
                thread_id=request.thread_id,
                expected_state_version=initial.state_version,
                confirmations=(
                    SubjectConfirmation(
                        intent_id=group.intent.intent_id,
                        decision="accept",
                        selected_subject_id=group.candidates[0].subject_id,
                    ),
                ),
            ).model_dump(mode="json")
        ),
        _config(),
    )
    assert _interrupt_kind(second) == "access_and_base"
    ready = _workspace(second)
    assert ready.places
    assert ready.areas
    assert any(item.kind == "walking_matrix" for item in ready.provider_snapshots)
    assert ready.access_candidates
    assert ready.selected_base_id is not None
    assert ready.selected_base_id.startswith("preferred-")
    assert any(item.kind == "transit" for item in ready.provider_snapshots)
    access_handoff = next(
        item for item in ready.handoffs if item.receiver.value == "access"
    )
    assert access_handoff.status == "completed"

    # Recompile around the same saver to prove resume does not depend on an
    # in-memory graph object or on replaying the previous API call.
    reloaded = build_workspace_graph(
        agent, saver, reviewer=reviewer, reviewer_source="fixture"
    )
    final = await reloaded.ainvoke(
        Command(
            resume=PlanWorkspaceRequest(
                owner_user_id=request.owner_user_id,
                thread_id=request.thread_id,
                expected_state_version=ready.state_version,
                base_id=ready.base_candidates[0].base_id,
            ).model_dump(mode="json")
        ),
        _config(),
    )
    planned = _workspace(final)
    assert reviewer.calls
    assert reviewer.max_active_calls == len(planned.planning_strategies)
    assert planned.reviewer_assessments
    assert {item.role.value for item in planned.contexts} >= {
        "requirement",
        "subject",
        "place_curator",
        "itinerary_planner",
        "validator",
        "reviewer",
    }
    assert all(item.source == "fixture" for item in planned.reviewer_assessments)
    assert set(planned.place_facts) == {item.place_id for item in planned.places}
    assert planned.weather_forecast is not None
    assert not planned.weather_forecast.available
    assert {item.kind for item in planned.provider_snapshots} >= {
        "transit",
        "place",
        "weather",
    }
    assert next(
        item for item in planned.handoffs if item.receiver.value == "place_facts"
    ).status == "completed"
    assert next(
        item for item in planned.handoffs if item.receiver.value == "weather"
    ).status == "partial"
    assert planned.knowledge_evidence
    assert tools.max_active_calls >= 2
    assert planned.knowledge_rules[0].status == "proposed"
    assert next(
        item for item in planned.handoffs if item.receiver.value == "knowledge"
    ).status == "completed"
    review_handoff = next(
        item for item in reversed(planned.handoffs) if item.receiver.value == "reviewer"
    )
    assert review_handoff.status == "completed"
    assert review_handoff.started_at is not None
    assert review_handoff.completed_at is not None
    assert review_handoff.created_at <= review_handoff.started_at
    phases = [
        checkpoint.checkpoint["channel_values"].get("phase")
        async for checkpoint in saver.alist(_config())
    ]
    assert "reviewer_handoff_pending" in phases
    assert "reviewer_handoff_running" in phases
    assert "access_handoff_pending" in phases
    assert "access_handoff_running" in phases
    assert "live_constraint_handoffs_pending" in phases
    assert "live_constraint_handoffs_running" in phases


@pytest.mark.asyncio
async def test_missing_llm_is_reported_without_fabricated_review() -> None:
    saver = InMemorySaver()
    agent = WorkspaceAgent(FixtureAgentToolClient())
    graph = build_workspace_graph(agent, saver, reviewer=None)
    request = _start_request()
    first = await graph.ainvoke(
        {"start_request": request.model_dump(mode="json")}, _config()
    )
    initial = _workspace(first)
    group = initial.subject_groups[0]
    second = await graph.ainvoke(
        Command(
            resume=ConfirmWorkspaceSubjectsRequest(
                owner_user_id=request.owner_user_id,
                thread_id=request.thread_id,
                expected_state_version=initial.state_version,
                confirmations=(
                    SubjectConfirmation(
                        intent_id=group.intent.intent_id,
                        decision="accept",
                        selected_subject_id=group.candidates[0].subject_id,
                    ),
                ),
            ).model_dump(mode="json")
        ),
        _config(),
    )
    ready = _workspace(second)
    final = await graph.ainvoke(
        Command(
            resume=PlanWorkspaceRequest(
                owner_user_id=request.owner_user_id,
                thread_id=request.thread_id,
                expected_state_version=ready.state_version,
                base_id=ready.base_candidates[0].base_id,
            ).model_dump(mode="json")
        ),
        _config(),
    )
    planned = _workspace(final)
    assert planned.reviewer_assessments
    assert {item.action for item in planned.reviewer_assessments} == {"unavailable"}
    review_handoff = next(
        item for item in reversed(planned.handoffs) if item.receiver.value == "reviewer"
    )
    assert review_handoff.status == "partial"
    assert "not configured" in review_handoff.warnings[0]


@pytest.mark.asyncio
async def test_replanner_versions_only_the_reviewer_target_day() -> None:
    saver = InMemorySaver()
    reviewer = CountingReviewer(revise=True)
    replanner = TargetedReplanner()
    agent = WorkspaceAgent(FixtureAgentToolClient())
    graph = build_workspace_graph(
        agent,
        saver,
        reviewer=reviewer,
        replanner=replanner,
        reviewer_source="fixture",
    )
    request = _start_request()
    first = await graph.ainvoke(
        {"start_request": request.model_dump(mode="json")}, _config()
    )
    initial = _workspace(first)
    group = initial.subject_groups[0]
    second = await graph.ainvoke(
        Command(
            resume=ConfirmWorkspaceSubjectsRequest(
                owner_user_id=request.owner_user_id,
                thread_id=request.thread_id,
                expected_state_version=initial.state_version,
                confirmations=(
                    SubjectConfirmation(
                        intent_id=group.intent.intent_id,
                        decision="accept",
                        selected_subject_id=group.candidates[0].subject_id,
                    ),
                ),
            ).model_dump(mode="json")
        ),
        _config(),
    )
    ready = _workspace(second)
    final = await graph.ainvoke(
        Command(
            resume=PlanWorkspaceRequest(
                owner_user_id=request.owner_user_id,
                thread_id=request.thread_id,
                expected_state_version=ready.state_version,
                base_id=ready.base_candidates[0].base_id,
            ).model_dump(mode="json")
        ),
        _config(),
    )
    planned = _workspace(final)
    assert any(item.role.value == "replanner" for item in planned.contexts)
    assert len(reviewer.calls) >= 2
    assert len(replanner.calls) == 1
    assert planned.diffs[-1].changed_day_numbers == (1,)
    latest = planned.itineraries[0]
    parent = next(
        item
        for item in planned.itineraries[1:]
        if item.strategy == latest.strategy and item.version == latest.parent_version
    )
    assert tuple(day.model_dump() for day in latest.days[1:]) == tuple(
        day.model_dump() for day in parent.days[1:]
    )
    replan_handoff = next(
        item for item in reversed(planned.handoffs) if item.receiver.value == "replanner"
    )
    assert replan_handoff.status == "completed"
    assert replan_handoff.started_at is not None
    assert replan_handoff.completed_at is not None
