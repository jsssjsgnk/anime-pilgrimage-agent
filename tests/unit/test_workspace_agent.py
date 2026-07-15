"""The remediated workspace Agent keeps multi-subject work explicit and partial-safe."""

# ruff: noqa: RUF001 -- Chinese test inputs preserve realistic punctuation.

from collections.abc import Mapping
from datetime import UTC, date, datetime, timedelta
from typing import ClassVar
from uuid import UUID, uuid4

import pytest

from pilgrimage_agent.agent.workspace import (
    ClearWorkspaceDayRequest,
    ConfirmWorkspaceSubjectsRequest,
    PlanWorkspaceRequest,
    SubjectConfirmation,
    WorkspaceAgent,
    WorkspaceMutationRequest,
    WorkspaceStartRequest,
    WorkspaceState,
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
from pilgrimage_agent.domain.workspace import (
    AgentRole,
    BatchPlaceOperation,
    PlaceOperation,
    PlanPatch,
    SubjectIntentOperation,
    UpdateRequirementOperation,
)


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

    async def call(self, name: str, arguments: Mapping[str, object]) -> dict[str, object]:
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


class MultiSeasonTools:
    async def call(self, name: str, arguments: Mapping[str, object]) -> dict[str, object]:
        if name == "search_anime_subjects":
            search_result = SubjectSearchResult(
                candidates=tuple(
                    SubjectCandidate(
                        subject_id=subject_id,
                        name=title,
                        name_cn=title,
                        provenance=_provenance("bangumi"),
                    )
                    for subject_id, title in (
                        ("1424", "轻音少女"),
                        ("3774", "轻音少女 第二季"),
                    )
                ),
                provenance=_provenance("bangumi"),
            )
            return search_result.model_dump(mode="json")
        subject_id = str(arguments["subject_id"])
        if name == "get_anime_subject":
            confirmed_result = ConfirmedSubject(
                subject_id=subject_id,
                name=subject_id,
                provenance=_provenance("bangumi"),
            )
            return confirmed_result.model_dump(mode="json")
        if name != "fetch_pilgrimage_points":
            raise ValueError("unexpected test tool")
        point = PilgrimagePoint(
            id=UUID(int=1 if subject_id == "1424" else 2),
            subject_id=subject_id,
            name="学校正门",
            latitude=35.00001,
            longitude=135.00001,
            confidence="community",
            provenance=_provenance("anitabi"),
        )
        return PilgrimagePointResult(
            points=(point,),
            is_complete=True,
            provenance=_provenance("anitabi"),
        ).model_dump(mode="json")


def _requirements() -> TripRequest:
    start = date.today() + timedelta(days=30)
    return TripRequest(
        origin="京都",
        destination="东京",
        start_date=start,
        end_date=start + timedelta(days=1),
        anime_query="孤独摇滚",
        subject_intents=(SubjectIntent(query="孤独摇滚", is_primary=True, priority=5),),
        walking_preference="medium",
    )


@pytest.mark.asyncio
async def test_explicit_dates_and_subjects_do_not_replace_natural_requirements() -> None:
    agent = WorkspaceAgent(MultiSubjectTools())
    start = date.today() + timedelta(days=30)

    requirements = await agent.extract_requirements(
        WorkspaceStartRequest(
            owner_user_id="user-1",
            thread_id="thread-1",
            request_summary=(
                "从京都出发去东京，住新宿附近，巡礼《孤独摇滚！》和《莉可丽丝》，"
                "每天尽量少走路。"
            ),
            requirements=TripRequest(
                start_date=start,
                end_date=start + timedelta(days=2),
                subject_intents=(
                    SubjectIntent(query="孤独摇滚！", is_primary=True, priority=5),
                    SubjectIntent(query="莉可丽丝", priority=4),
                ),
            ),
        )
    )

    assert requirements.origin == "京都"
    assert requirements.destination == "东京"
    assert requirements.base_preference == "新宿附近"
    assert requirements.walking_preference == "low"
    assert requirements.transit_route_preference == "less_walking"
    assert requirements.start_date == start
    assert requirements.end_date == start + timedelta(days=2)
    assert [item.query for item in requirements.subject_intents] == [
        "孤独摇滚！",
        "莉可丽丝",
    ]


@pytest.mark.asyncio
async def test_one_intent_can_confirm_multiple_seasons_and_merge_their_place() -> None:
    agent = WorkspaceAgent(MultiSeasonTools())
    start = date.today() + timedelta(days=30)
    initial = await agent.start(
        WorkspaceStartRequest(
            owner_user_id="user-1",
            thread_id="thread-1",
            request_summary="一天巡礼《轻音少女》的多个季度。",
            requirements=TripRequest(
                destination="京都",
                start_date=start,
                end_date=start,
                subject_intents=(SubjectIntent(query="轻音少女", is_primary=True, priority=5),),
            ),
        )
    )
    group = initial.subject_groups[0]
    confirmed = await agent.confirm_subjects(
        initial,
        ConfirmWorkspaceSubjectsRequest(
            owner_user_id="user-1",
            thread_id="thread-1",
            expected_state_version=initial.state_version,
            confirmations=(
                SubjectConfirmation(
                    intent_id=group.intent.intent_id,
                    decision="accept",
                    selected_subject_ids=("1424", "3774"),
                ),
            ),
        ),
    )

    assert len(confirmed.confirmed_subjects) == 2
    assert all(item.point_collection is not None for item in confirmed.confirmed_subjects)
    assert all(
        item.point_collection.loaded_count == item.point_collection.expected_count == 1
        for item in confirmed.confirmed_subjects
        if item.point_collection is not None
    )
    assert confirmed.requirements.subject_intents[0].catalog_subject_ids == (
        "1424",
        "3774",
    )
    assert confirmed.subject_groups[0].intent.catalog_subject_ids == ("1424", "3774")
    assert workspace_view(confirmed).subject_groups[0].intent.catalog_subject_ids == (
        "1424",
        "3774",
    )
    assert len(confirmed.evidence) == 2
    assert len(confirmed.places) == 1
    assert {item.subject_id for item in confirmed.places[0].subject_appearances} == {
        "1424",
        "3774",
    }


async def _planned_workspace() -> tuple[WorkspaceAgent, WorkspaceState]:
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
    return agent, agent.plan(
        curated,
        PlanWorkspaceRequest(
            owner_user_id="user-1",
            thread_id="thread-1",
            expected_state_version=curated.state_version,
            base_id=curated.base_candidates[0].base_id,
        ),
    )


@pytest.mark.asyncio
async def test_work_collection_add_confirm_and_remove_preserves_other_subjects() -> None:
    agent, planned = await _planned_workspace()
    original_subject_ids = {item.subject.subject_id for item in planned.confirmed_subjects}
    original_evidence_ids = {item.evidence_id for item in planned.evidence}
    added_intent = SubjectIntent(query="天气之子", priority=3)
    add_patch = PlanPatch(
        trip_id=planned.trip_id,
        expected_base_version=planned.state_version,
        rationale="添加天气之子",
        requires_confirmation=True,
        idempotency_key=f"test-add:{uuid4()}",
        created_at=datetime.now(UTC),
        operations=(SubjectIntentOperation(action="add", intent=added_intent),),
    )
    proposed, preview = agent.propose_patch(planned, add_patch)
    awaiting = await agent.apply_patch(proposed, preview.patch.patch_id, confirm=True)

    assert awaiting.status is WorkspaceStatus.AWAITING_SUBJECTS
    assert {item.subject.subject_id for item in awaiting.confirmed_subjects} == (
        original_subject_ids
    )
    assert awaiting.itineraries == planned.itineraries
    added_group = next(
        item for item in awaiting.subject_groups if item.intent.intent_id == added_intent.intent_id
    )
    refreshed = await agent.confirm_subjects(
        awaiting,
        ConfirmWorkspaceSubjectsRequest(
            owner_user_id="user-1",
            thread_id="thread-1",
            expected_state_version=awaiting.state_version,
            confirmations=(
                SubjectConfirmation(
                    intent_id=added_intent.intent_id,
                    decision="accept",
                    selected_subject_id=added_group.candidates[0].subject_id,
                ),
            ),
        ),
    )

    assert original_subject_ids.issubset(
        {item.subject.subject_id for item in refreshed.confirmed_subjects}
    )
    assert original_evidence_ids.issubset({item.evidence_id for item in refreshed.evidence})
    assert refreshed.itineraries

    remove_patch = PlanPatch(
        trip_id=refreshed.trip_id,
        expected_base_version=refreshed.state_version,
        rationale="移除天气之子",
        requires_confirmation=True,
        idempotency_key=f"test-remove:{uuid4()}",
        created_at=datetime.now(UTC),
        operations=(SubjectIntentOperation(action="remove", intent_id=added_intent.intent_id),),
    )
    proposed_remove, remove_preview = agent.propose_patch(refreshed, remove_patch)
    removed = await agent.apply_patch(proposed_remove, remove_preview.patch.patch_id, confirm=True)

    assert {item.subject.subject_id for item in removed.confirmed_subjects} == (
        original_subject_ids
    )
    assert all(
        item.intent_id != added_intent.intent_id for item in removed.requirements.subject_intents
    )
    assert removed.itineraries


@pytest.mark.asyncio
async def test_three_subject_workspace_degrades_one_subject_without_data_loss() -> None:
    agent = WorkspaceAgent(MultiSubjectTools())
    state = await agent.start(
        WorkspaceStartRequest(
            owner_user_id="user-1",
            thread_id="thread-1",
            request_summary=("两天巡礼《孤独摇滚》《莉可丽丝》《天气之子》,主要巡礼《孤独摇滚》。"),
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
        item.subject.subject_id: item.evidence_status for item in confirmed.confirmed_subjects
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
        item.sender is AgentRole.EVIDENCE_COLLECTOR and item.receiver is AgentRole.PLACE_CURATOR
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


@pytest.mark.asyncio
async def test_clear_schedule_stays_empty_and_history_can_be_restored() -> None:
    agent, planned = await _planned_workspace()
    source_id = planned.itineraries[0].itinerary_id
    cleared = agent.clear_schedule(
        planned,
        WorkspaceMutationRequest(
            owner_user_id=planned.owner_user_id,
            thread_id=planned.thread_id,
            expected_state_version=planned.state_version,
        ),
    )
    assert cleared.status is WorkspaceStatus.READY_TO_PLAN
    assert cleared.itineraries == ()
    assert cleared.candidate_graph == planned.candidate_graph
    assert {item.itinerary_id for item in cleared.archived_itineraries} == {
        item.itinerary_id for item in planned.itineraries
    }

    restored = agent.restore_itinerary(
        cleared,
        WorkspaceMutationRequest(
            owner_user_id=cleared.owner_user_id,
            thread_id=cleared.thread_id,
            expected_state_version=cleared.state_version,
        ),
        source_id,
    )
    assert restored.itineraries[0].itinerary_id != source_id
    assert restored.itineraries[0].parent_version == planned.itineraries[0].version
    assert restored.itineraries[0].days == planned.itineraries[0].days


@pytest.mark.asyncio
async def test_clear_day_never_refills_and_only_inactive_versions_can_be_deleted() -> None:
    agent, planned = await _planned_workspace()
    active_count = len(planned.planning_strategies)
    prior_ids = {item.itinerary_id for item in planned.itineraries[:active_count]}
    cleared = agent.clear_day(
        planned,
        ClearWorkspaceDayRequest(
            owner_user_id=planned.owner_user_id,
            thread_id=planned.thread_id,
            expected_state_version=planned.state_version,
            day_number=1,
        ),
    )
    assert all(not item.days[0].visits for item in cleared.itineraries[:active_count])
    assert all(
        any(omission.reason_code == "user_removed" for omission in item.omissions)
        for item in cleared.itineraries[:active_count]
    )
    with pytest.raises(ValueError, match="active itinerary"):
        agent.delete_itinerary_version(
            cleared,
            WorkspaceMutationRequest(
                owner_user_id=cleared.owner_user_id,
                thread_id=cleared.thread_id,
                expected_state_version=cleared.state_version,
            ),
            cleared.itineraries[0].itinerary_id,
        )
    deleted = agent.delete_itinerary_version(
        cleared,
        WorkspaceMutationRequest(
            owner_user_id=cleared.owner_user_id,
            thread_id=cleared.thread_id,
            expected_state_version=cleared.state_version,
        ),
        next(item for item in prior_ids),
    )
    assert not prior_ids.issubset({item.itinerary_id for item in deleted.itineraries})


@pytest.mark.asyncio
async def test_patch_preview_apply_revalidate_diff_and_idempotency() -> None:
    agent, planned = await _planned_workspace()
    walking_patch = PlanPatch(
        trip_id=planned.trip_id,
        expected_base_version=planned.state_version,
        operations=(UpdateRequirementOperation(field="walking_preference", value="low"),),
        rationale="减少每天步行",
        requires_confirmation=True,
        idempotency_key="fixture:walking-low",
        created_at=datetime.now(UTC),
    )
    proposed, preview = agent.propose_patch(planned, walking_patch)

    assert proposed.state_version == planned.state_version
    assert preview.patch.requires_confirmation is False
    assert preview.impact.validation_required is True
    changed = await agent.apply_patch(proposed, preview.patch.patch_id, confirm=False)
    assert changed.state_version == planned.state_version + 1
    assert changed.requirements.walking_preference == "low"
    assert changed.diffs[-1].changed_requirements == ("walking_preference",)
    current_versions = tuple(
        item for item in changed.itineraries if item.version == changed.state_version
    )
    historical_versions = tuple(
        item for item in changed.itineraries if item.version != changed.state_version
    )
    assert all(item.applied_patch_id == preview.patch.patch_id for item in current_versions)
    assert all(item.applied_patch_id is None for item in historical_versions)
    assert len(current_versions) == len(historical_versions) == 2
    assert any(item.role is AgentRole.REPLANNER for item in changed.contexts)
    retried = await agent.apply_patch(changed, preview.patch.patch_id, confirm=False)
    assert retried == changed


@pytest.mark.asyncio
async def test_batch_place_patch_applies_atomically_through_the_shared_path() -> None:
    agent, planned = await _planned_workspace()
    place_ids = tuple(item.place_id for item in planned.places)
    assert len(place_ids) > 1
    patch = PlanPatch(
        trip_id=planned.trip_id,
        expected_base_version=planned.state_version,
        operations=(BatchPlaceOperation(action="exclude", place_ids=place_ids),),
        rationale="暂不安排当前区域的全部地点",
        requires_confirmation=False,
        idempotency_key="fixture:batch-exclude",
        created_at=datetime.now(UTC),
    )

    proposed, preview = agent.propose_patch(planned, patch)
    changed = await agent.apply_patch(proposed, preview.patch.patch_id, confirm=False)

    assert set(place_ids).issubset(changed.excluded_place_ids)
    assert preview.impact.invalidated_refs == tuple(
        sorted(f"visit_place:{place_id}" for place_id in place_ids)
    )


@pytest.mark.asyncio
async def test_material_date_and_local_move_patches_preserve_explicit_boundaries() -> None:
    agent, planned = await _planned_workspace()
    original_start = planned.requirements.start_date
    original_end = planned.requirements.end_date
    assert original_start is not None and original_end is not None
    shifted_start = original_start + timedelta(days=7)
    date_patch = PlanPatch(
        trip_id=planned.trip_id,
        expected_base_version=planned.state_version,
        operations=(UpdateRequirementOperation(field="start_date", value=shifted_start),),
        rationale="整段行程延后一周",
        requires_confirmation=False,
        idempotency_key="fixture:shift-dates",
        created_at=datetime.now(UTC),
    )
    proposed, preview = agent.propose_patch(planned, date_patch)
    assert preview.patch.requires_confirmation is True
    with pytest.raises(ValueError, match="explicit confirmation"):
        await agent.apply_patch(proposed, preview.patch.patch_id, confirm=False)
    shifted = await agent.apply_patch(proposed, preview.patch.patch_id, confirm=True)
    assert shifted.requirements.start_date == shifted_start
    assert shifted.requirements.end_date == original_end + timedelta(days=7)

    place_id = shifted.itineraries[0].days[0].visits[0].place_id
    move_patch = PlanPatch(
        trip_id=shifted.trip_id,
        expected_base_version=shifted.state_version,
        operations=(PlaceOperation(action="move_day", place_id=place_id, target_day=2),),
        rationale="把这个地点移到第二天",
        requires_confirmation=False,
        idempotency_key="fixture:move-place",
        created_at=datetime.now(UTC),
    )
    move_proposed, move_preview = agent.propose_patch(shifted, move_patch)
    moved = await agent.apply_patch(move_proposed, move_preview.patch.patch_id, confirm=False)
    current_versions = tuple(
        itinerary for itinerary in moved.itineraries if itinerary.version == moved.state_version
    )
    historical_versions = tuple(
        itinerary for itinerary in moved.itineraries if itinerary.version != moved.state_version
    )
    for itinerary in current_versions:
        assert place_id in {item.place_id for item in itinerary.days[1].visits}
        assert place_id not in {item.place_id for item in itinerary.days[0].visits}
    assert any(
        place_id in {item.place_id for item in itinerary.days[0].visits}
        for itinerary in historical_versions
    )
    assert moved.diffs[-1].changed_day_numbers == (2,)
