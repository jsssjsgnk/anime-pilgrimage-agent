"""Normalized workspace projection emits every persisted entity family."""

from datetime import UTC, date, datetime, timedelta
from typing import cast

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from pilgrimage_agent.agent.mcp_client import FixtureAgentToolClient
from pilgrimage_agent.agent.workspace import (
    ConfirmWorkspaceSubjectsRequest,
    PlanWorkspaceRequest,
    SubjectConfirmation,
    WorkspaceAgent,
    WorkspaceStartRequest,
)
from pilgrimage_agent.domain.models import SubjectIntent, TripRequest
from pilgrimage_agent.domain.workspace import (
    DerivedKnowledgeRule,
    EntityRef,
    PlanPatch,
    UpdateRequirementOperation,
)
from pilgrimage_agent.memory.workspace_repository import SqlWorkspaceRepository


class RecordingSession:
    def __init__(self) -> None:
        self.statements: list[object] = []

    async def execute(self, statement: object) -> None:
        self.statements.append(statement)


class RecordingBegin:
    def __init__(self, session: RecordingSession) -> None:
        self.session = session

    async def __aenter__(self) -> RecordingSession:
        return self.session

    async def __aexit__(self, *_error: object) -> None:
        return None


class RecordingSessions:
    def __init__(self) -> None:
        self.session = RecordingSession()

    def begin(self) -> RecordingBegin:
        return RecordingBegin(self.session)


async def test_projection_emits_normalized_graph_patch_handoff_and_rule_rows() -> None:
    start = date.today() + timedelta(days=20)
    agent = WorkspaceAgent(FixtureAgentToolClient())
    initial = await agent.start(
        WorkspaceStartRequest(
            owner_user_id="projection-user",
            thread_id="projection-thread",
            request_summary="巡礼《孤独摇滚》。",
            requirements=TripRequest(
                start_date=start,
                end_date=start + timedelta(days=1),
                anime_query="孤独摇滚",
                subject_intents=(
                    SubjectIntent(query="孤独摇滚", priority=5, is_primary=True),
                ),
            ),
        )
    )
    group = initial.subject_groups[0]
    curated = await agent.confirm_subjects(
        initial,
        ConfirmWorkspaceSubjectsRequest(
            owner_user_id=initial.owner_user_id,
            thread_id=initial.thread_id,
            expected_state_version=initial.state_version,
            confirmations=(
                SubjectConfirmation(
                    intent_id=group.intent.intent_id,
                    decision="accept",
                    selected_subject_id=group.candidates[0].subject_id,
                ),
            ),
        ),
    )
    planned = agent.plan(
        curated,
        PlanWorkspaceRequest(
            owner_user_id=curated.owner_user_id,
            thread_id=curated.thread_id,
            expected_state_version=curated.state_version,
            base_id=curated.base_candidates[0].base_id,
        ),
    )
    patch = PlanPatch(
        trip_id=planned.trip_id,
        expected_base_version=planned.state_version,
        operations=(
            UpdateRequirementOperation(field="walking_preference", value="low"),
        ),
        rationale="projection fixture",
        requires_confirmation=False,
        idempotency_key="projection:walking",
        created_at=datetime.now(UTC),
    )
    proposed, _preview = agent.propose_patch(planned, patch)
    rule = DerivedKnowledgeRule(
        trip_id=planned.trip_id,
        rule_type="closure_date_range",
        target_refs=(
            EntityRef(entity_type="place", entity_id=str(planned.places[0].place_id)),
        ),
        value={"closed_from": start.isoformat(), "closed_until": start.isoformat()},
        evidence_ids=("K-a1b2c3d4e5f6",),
        authority_level=5,
        status="active_constraint",
        created_at=datetime.now(UTC),
    )
    state = proposed.model_copy(update={"knowledge_rules": (rule,)})
    sessions = RecordingSessions()
    repository = SqlWorkspaceRepository(
        cast(async_sessionmaker[AsyncSession], sessions)
    )

    await repository.save_projection(state)

    assert len(sessions.session.statements) >= 25
    rendered = "\n".join(str(item) for item in sessions.session.statements)
    for table in (
        "subjects",
        "scene_evidence",
        "visit_places",
        "area_clusters",
        "candidate_graph_versions",
        "itinerary_versions",
        "plan_patches",
        "agent_handoffs",
        "derived_knowledge_rules",
    ):
        assert table in rendered
