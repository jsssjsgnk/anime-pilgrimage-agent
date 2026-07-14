"""The remediated workspace Agent keeps multi-subject work explicit and partial-safe."""

from collections.abc import Mapping
from datetime import UTC, date, datetime, timedelta
from typing import ClassVar
from uuid import UUID

import pytest

from pilgrimage_agent.agent.workspace import (
    ConfirmWorkspaceSubjectsRequest,
    PlanWorkspaceRequest,
    SubjectConfirmation,
    WorkspaceAgent,
    WorkspaceStartRequest,
    WorkspaceStatus,
    workspace_view,
)
from pilgrimage_agent.domain.models import (
    ConfirmedSubject,
    DataProvenance,
    DataStatus,
    PilgrimagePoint,
    PilgrimagePointResult,
    SubjectCandidate,
    SubjectIntent,
    SubjectSearchResult,
    TripRequest,
)
from pilgrimage_agent.domain.workspace import AgentRole


def _provenance(provider: str) -> DataProvenance:
    return DataProvenance(
        provider=provider,
        fetched_at=datetime.now(UTC),
        status=DataStatus.COMMUNITY,
    )


class MultiSubjectTools:
    """Return two complete Anitabi subjects and one isolated failure."""

    subject_ids: ClassVar[dict[str, str]] = {
        "孤独摇滚": "bocchi",
        "莉可丽丝": "lycoris",
        "天气之子": "weathering",
    }

    async def call(
        self, name: str, arguments: Mapping[str, object]
    ) -> dict[str, object]:
        if name == "search_anime_subjects":
            query = str(arguments["query"])
            subject_id = self.subject_ids[query]
            search_result = SubjectSearchResult(
                candidates=(
                    SubjectCandidate(
                        subject_id=subject_id,
                        name=query,
                        name_cn=query,
                        provenance=_provenance("bangumi"),
                    ),
                ),
                provenance=_provenance("bangumi"),
            )
            return search_result.model_dump(mode="json")
        if name == "get_anime_subject":
            subject_id = str(arguments["subject_id"])
            confirmed_result = ConfirmedSubject(
                subject_id=subject_id,
                name=subject_id,
                provenance=_provenance("bangumi"),
            )
            return confirmed_result.model_dump(mode="json")
        if name != "fetch_pilgrimage_points":
            raise ValueError("unexpected test tool")
        subject_id = str(arguments["subject_id"])
        if subject_id == "weathering":
            raise RuntimeError("isolated Anitabi failure")
        offset = 0 if subject_id == "bocchi" else 10
        unique_latitude = 35.66400 if subject_id == "bocchi" else 35.65800
        points = (
            PilgrimagePoint(
                id=UUID(int=offset + 1),
                subject_id=subject_id,
                name="下北泽站共享地点",
                latitude=35.66100,
                longitude=139.66680,
                episode_refs=("第1话",),
                confidence="community",
                source_label="下北泽站共享地点",
                provenance=_provenance("anitabi"),
            ),
            PilgrimagePoint(
                id=UUID(int=offset + 2),
                subject_id=subject_id,
                name=f"{subject_id} 独有地点",
                latitude=unique_latitude,
                longitude=139.66730,
                episode_refs=("第2话",),
                confidence="community",
                source_label=f"{subject_id} 独有地点",
                provenance=_provenance("anitabi"),
            ),
        )
        point_result = PilgrimagePointResult(
            points=points,
            is_complete=True,
            provenance=_provenance("anitabi"),
        )
        return point_result.model_dump(mode="json")


def _requirements() -> TripRequest:
    start = date.today() + timedelta(days=30)
    return TripRequest(
        origin="京都",
        destination="东京",
        start_date=start,
        end_date=start + timedelta(days=1),
        anime_query="孤独摇滚",
        subject_intents=(
            SubjectIntent(query="孤独摇滚", is_primary=True, priority=5),
        ),
        walking_preference="medium",
    )


@pytest.mark.asyncio
async def test_three_subject_workspace_degrades_one_subject_without_data_loss() -> None:
    agent = WorkspaceAgent(MultiSubjectTools())
    state = await agent.start(
        WorkspaceStartRequest(
            owner_user_id="user-1",
            thread_id="thread-1",
            request_summary=(
                "两天巡礼《孤独摇滚》《莉可丽丝》《天气之子》,"
                "主要巡礼《孤独摇滚》。"
            ),
            requirements=_requirements(),
        )
    )

    assert state.status is WorkspaceStatus.AWAITING_SUBJECTS
    assert [item.intent.query for item in state.subject_groups] == [
        "孤独摇滚",
        "莉可丽丝",
        "天气之子",
    ]
    assert sum(item.intent.is_primary for item in state.subject_groups) == 1

    confirmations = tuple(
        SubjectConfirmation(
            intent_id=group.intent.intent_id,
            decision="accept",
            selected_subject_id=group.candidates[0].subject_id,
        )
        for group in state.subject_groups
    )
    confirmed = await agent.confirm_subjects(
        state,
        ConfirmWorkspaceSubjectsRequest(
            owner_user_id="user-1",
            thread_id="thread-1",
            expected_state_version=state.state_version,
            confirmations=confirmations,
        ),
    )

    assert confirmed.status is WorkspaceStatus.PARTIAL_READY
    assert len(confirmed.confirmed_subjects) == 3
    evidence_statuses = {
        item.subject.subject_id: item.evidence_status
        for item in confirmed.confirmed_subjects
    }
    assert evidence_statuses == {
        "bocchi": "ok",
        "lycoris": "ok",
        "weathering": "unavailable",
    }
    assert len(confirmed.evidence) == 4
    assert len(confirmed.places) == 3
    assert sum(len(item.scene_evidence_ids) for item in confirmed.places) == 4
    shared = next(item for item in confirmed.places if len(item.subject_appearances) == 2)
    assert {item.subject_id for item in shared.subject_appearances} == {
        "bocchi",
        "lycoris",
    }
    assert confirmed.areas
    assert any("天气之子" in item for item in confirmed.warnings)
    assert any(
        item.sender is AgentRole.EVIDENCE_COLLECTOR
        and item.receiver is AgentRole.PLACE_CURATOR
        for item in confirmed.handoffs
    )


@pytest.mark.asyncio
async def test_workspace_plans_two_independent_versions_and_progressive_counts() -> None:
    agent = WorkspaceAgent(MultiSubjectTools())
    initial = await agent.start(
        WorkspaceStartRequest(
            owner_user_id="user-1",
            thread_id="thread-1",
            request_summary="两天巡礼《孤独摇滚》和《莉可丽丝》。",
            requirements=_requirements(),
        )
    )
    curated = await agent.confirm_subjects(
        initial,
        ConfirmWorkspaceSubjectsRequest(
            owner_user_id="user-1",
            thread_id="thread-1",
            expected_state_version=1,
            confirmations=tuple(
                SubjectConfirmation(
                    intent_id=group.intent.intent_id,
                    decision="accept",
                    selected_subject_id=group.candidates[0].subject_id,
                )
                for group in initial.subject_groups
            ),
        ),
    )
    planned = agent.plan(
        curated,
        PlanWorkspaceRequest(
            owner_user_id="user-1",
            thread_id="thread-1",
            expected_state_version=curated.state_version,
            base_id=curated.base_candidates[0].base_id,
        ),
    )
    view = workspace_view(planned)

    assert planned.status is WorkspaceStatus.PLANNED
    assert len(planned.itineraries) == 2
    assert planned.itineraries[0].itinerary_id != planned.itineraries[1].itinerary_id
    assert view.counts.raw_scene_records == 4
    assert view.counts.canonical_places == 3
    assert view.counts.scheduled_places == 3
    shared = next(item for item in planned.places if len(item.subject_appearances) == 2)
    for itinerary in planned.itineraries:
        scheduled = [visit.place_id for day in itinerary.days for visit in day.visits]
        assert scheduled.count(shared.place_id) == 1
        coverage = {item.subject_id: item for item in itinerary.subject_coverage}
        assert shared.place_id in coverage["bocchi"].scheduled_place_ids
        assert shared.place_id in coverage["lycoris"].scheduled_place_ids
    assert any(item.receiver is AgentRole.VALIDATOR for item in planned.handoffs)
