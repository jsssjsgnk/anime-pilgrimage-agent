"""Multi-subject workspace Agent with typed role handoffs and bounded projections."""

from __future__ import annotations

import re
from datetime import UTC, date, datetime, timedelta
from enum import StrEnum
from typing import Literal
from uuid import UUID, uuid4

from pydantic import Field, model_validator

from pilgrimage_agent.agent.context import RoleContextBuilder
from pilgrimage_agent.agent.llm import DeterministicRequirementExtractor, RequirementExtractor
from pilgrimage_agent.agent.mcp_client import AgentToolClient
from pilgrimage_agent.curation.resolution import evidence_from_point, resolve_places
from pilgrimage_agent.domain.models import (
    ConfirmedSubject,
    DataProvenance,
    DataStatus,
    GeoCoordinate,
    PilgrimagePointQuery,
    PilgrimagePointResult,
    StrictModel,
    SubjectCandidate,
    SubjectIntent,
    SubjectSearchResult,
    TripRequest,
)
from pilgrimage_agent.domain.planning import AccessSelection, BaseCandidate
from pilgrimage_agent.domain.workspace import (
    AgentHandoff,
    AgentRole,
    AmbiguousPlaceMerge,
    AreaCluster,
    DerivedKnowledgeRule,
    EntityRef,
    EvidenceQuarantine,
    ImpactAnalysis,
    ItineraryVersion,
    KnowledgeOperation,
    PlaceOperation,
    PlaceResolutionOverride,
    PlanningStrategy,
    PlanPatch,
    PlanVersionDiff,
    RoleContext,
    SceneEvidence,
    SelectionOperation,
    SubjectIntentOperation,
    TripCandidateGraph,
    UpdateRequirementOperation,
    VisitPlace,
)
from pilgrimage_agent.planning.areas import cluster_places
from pilgrimage_agent.planning.geo import haversine_meters
from pilgrimage_agent.planning.hierarchical import (
    HierarchicalPlanningRequest,
    plan_hierarchical_itineraries,
)
from pilgrimage_agent.planning.patches import (
    PlanPatchPreview,
    analyze_impact,
    normalize_patch,
)
from pilgrimage_agent.providers.outcomes import invoke_tool

_TITLE = re.compile(r"《([^》]{1,100})》")


class WorkspaceStatus(StrEnum):
    AWAITING_SUBJECTS = "awaiting_subject_confirmation"
    READY = "ready_for_planning"
    PARTIAL_READY = "partial_ready_for_planning"
    PLANNED = "planned"
    PARTIAL = "partial"


class WorkspaceStartRequest(StrictModel):
    owner_user_id: str = Field(min_length=1, max_length=120)
    thread_id: str = Field(min_length=1, max_length=120)
    trip_id: UUID = Field(default_factory=uuid4)
    request_summary: str = Field(min_length=1, max_length=2000)
    requirements: TripRequest | None = None


class SubjectCandidateGroup(StrictModel):
    intent: SubjectIntent
    candidates: tuple[SubjectCandidate, ...]
    status: Literal["ok", "unavailable", "not_found"]
    warning: str | None = Field(default=None, max_length=500)


class ConfirmedWorkspaceSubject(StrictModel):
    intent_id: UUID
    subject: ConfirmedSubject
    evidence_status: Literal["pending", "ok", "partial", "unavailable"]
    warning: str | None = Field(default=None, max_length=500)


class SubjectConfirmation(StrictModel):
    intent_id: UUID
    decision: Literal["accept", "reject"]
    selected_subject_id: str | None = Field(default=None, max_length=50)
    selected_subject_ids: tuple[str, ...] = Field(default=(), max_length=5)

    @model_validator(mode="before")
    @classmethod
    def adapt_single_selected_subject(cls, value: object) -> object:
        if not isinstance(value, dict):
            return value
        adapted = dict(value)
        single = adapted.get("selected_subject_id")
        multiple = adapted.get("selected_subject_ids")
        if single and not multiple:
            adapted["selected_subject_ids"] = (single,)
        elif multiple and not single and isinstance(multiple, (tuple, list)) and multiple:
            adapted["selected_subject_id"] = multiple[0]
        return adapted

    @model_validator(mode="after")
    def selected_id_matches_decision(self) -> SubjectConfirmation:
        if len(self.selected_subject_ids) != len(set(self.selected_subject_ids)):
            raise ValueError("selected subject IDs must be unique")
        if (self.decision == "accept") != bool(self.selected_subject_ids):
            raise ValueError("accepted subject confirmations require selected IDs")
        if (
            self.selected_subject_id is not None
            and self.selected_subject_id not in self.selected_subject_ids
        ):
            raise ValueError("the compatibility selected ID must belong to the selected set")
        return self


class ConfirmWorkspaceSubjectsRequest(StrictModel):
    owner_user_id: str = Field(min_length=1, max_length=120)
    thread_id: str = Field(min_length=1, max_length=120)
    expected_state_version: int = Field(ge=1)
    confirmations: tuple[SubjectConfirmation, ...] = Field(min_length=1, max_length=3)


class PlanWorkspaceRequest(StrictModel):
    owner_user_id: str = Field(min_length=1, max_length=120)
    thread_id: str = Field(min_length=1, max_length=120)
    expected_state_version: int = Field(ge=1)
    base_id: str = Field(min_length=1, max_length=100)
    access: AccessSelection | None = None
    timezone: str | None = Field(default=None, max_length=80)
    strategies: tuple[PlanningStrategy, ...] = (
        PlanningStrategy.PRIMARY_SUBJECT_FIRST,
        PlanningStrategy.LOW_WALKING,
    )
    must_visit_place_ids: frozenset[UUID] = frozenset()
    excluded_place_ids: frozenset[UUID] = frozenset()


class WorkspaceCounts(StrictModel):
    raw_scene_records: int = Field(ge=0)
    quarantined_records: int = Field(ge=0)
    canonical_places: int = Field(ge=0)
    areas: int = Field(ge=0)
    recommended_places: int = Field(ge=0)
    scheduled_places: int = Field(ge=0)


class WorkspaceState(StrictModel):
    schema_version: Literal["2"] = "2"
    owner_user_id: str
    thread_id: str
    trip_id: UUID
    request_summary: str
    state_version: int = Field(ge=1)
    status: WorkspaceStatus
    requirements: TripRequest
    subject_groups: tuple[SubjectCandidateGroup, ...]
    confirmed_subjects: tuple[ConfirmedWorkspaceSubject, ...] = ()
    evidence: tuple[SceneEvidence, ...] = ()
    quarantined: tuple[EvidenceQuarantine, ...] = ()
    ambiguous_merges: tuple[AmbiguousPlaceMerge, ...] = ()
    resolution_overrides: tuple[PlaceResolutionOverride, ...] = ()
    places: tuple[VisitPlace, ...] = ()
    areas: tuple[AreaCluster, ...] = ()
    base_candidates: tuple[BaseCandidate, ...] = ()
    selected_base_id: str | None = None
    selected_access: AccessSelection | None = None
    planning_strategies: tuple[PlanningStrategy, ...] = (
        PlanningStrategy.PRIMARY_SUBJECT_FIRST,
        PlanningStrategy.LOW_WALKING,
    )
    must_visit_place_ids: frozenset[UUID] = frozenset()
    excluded_place_ids: frozenset[UUID] = frozenset()
    fixed_day_assignments: dict[UUID, int] = Field(default_factory=dict)
    fixed_positions: dict[UUID, int] = Field(default_factory=dict)
    attached_knowledge_ids: frozenset[UUID] = frozenset()
    knowledge_rules: tuple[DerivedKnowledgeRule, ...] = ()
    knowledge_evidence_documents: dict[str, UUID] = Field(default_factory=dict)
    candidate_graph: TripCandidateGraph | None = None
    itineraries: tuple[ItineraryVersion, ...] = ()
    handoffs: tuple[AgentHandoff, ...] = ()
    contexts: tuple[RoleContext, ...] = ()
    patches: tuple[PlanPatch, ...] = ()
    impacts: tuple[ImpactAnalysis, ...] = ()
    diffs: tuple[PlanVersionDiff, ...] = ()
    pending_patch_id: UUID | None = None
    warnings: tuple[str, ...] = ()


class WorkspaceView(StrictModel):
    schema_version: Literal["2"] = "2"
    thread_id: str
    trip_id: UUID
    state_version: int
    status: WorkspaceStatus
    requirements: TripRequest
    subject_groups: tuple[SubjectCandidateGroup, ...]
    confirmed_subjects: tuple[ConfirmedWorkspaceSubject, ...]
    places: tuple[VisitPlace, ...]
    areas: tuple[AreaCluster, ...]
    base_candidates: tuple[BaseCandidate, ...]
    selected_base_id: str | None
    planning_strategies: tuple[PlanningStrategy, ...]
    must_visit_place_ids: frozenset[UUID]
    excluded_place_ids: frozenset[UUID]
    candidate_graph: TripCandidateGraph | None
    itineraries: tuple[ItineraryVersion, ...]
    handoffs: tuple[AgentHandoff, ...]
    contexts: tuple[RoleContext, ...]
    patches: tuple[PlanPatch, ...]
    impacts: tuple[ImpactAnalysis, ...]
    diffs: tuple[PlanVersionDiff, ...]
    pending_patch_id: UUID | None
    knowledge_rules: tuple[DerivedKnowledgeRule, ...]
    counts: WorkspaceCounts
    warnings: tuple[str, ...]


class WorkspaceEvidenceView(StrictModel):
    trip_id: UUID
    evidence: tuple[SceneEvidence, ...]
    quarantined: tuple[EvidenceQuarantine, ...]
    ambiguous_merges: tuple[AmbiguousPlaceMerge, ...]


class WorkspacePatchPreview(StrictModel):
    workspace: WorkspaceView
    preview: PlanPatchPreview


def workspace_view(state: WorkspaceState) -> WorkspaceView:
    active = state.itineraries[0] if state.itineraries else None
    scheduled = (
        {
            visit.place_id
            for day in active.days
            for visit in day.visits
        }
        if active
        else set()
    )
    recommended = (
        sum(
            item.status in {"included", "recommended"}
            for item in state.candidate_graph.decisions
            if item.entity_type == "place"
        )
        if state.candidate_graph
        else len(state.places)
    )
    return WorkspaceView(
        thread_id=state.thread_id,
        trip_id=state.trip_id,
        state_version=state.state_version,
        status=state.status,
        requirements=state.requirements,
        subject_groups=state.subject_groups,
        confirmed_subjects=state.confirmed_subjects,
        places=state.places,
        areas=state.areas,
        base_candidates=state.base_candidates,
        selected_base_id=state.selected_base_id,
        planning_strategies=state.planning_strategies,
        must_visit_place_ids=state.must_visit_place_ids,
        excluded_place_ids=state.excluded_place_ids,
        candidate_graph=state.candidate_graph,
        itineraries=state.itineraries,
        handoffs=state.handoffs,
        contexts=state.contexts,
        patches=state.patches,
        impacts=state.impacts,
        diffs=state.diffs,
        pending_patch_id=state.pending_patch_id,
        knowledge_rules=state.knowledge_rules,
        counts=WorkspaceCounts(
            raw_scene_records=len(state.evidence),
            quarantined_records=len(state.quarantined),
            canonical_places=len(state.places),
            areas=len(state.areas),
            recommended_places=recommended,
            scheduled_places=len(scheduled),
        ),
        warnings=state.warnings,
    )


def _ref(entity_type: str, entity_id: object, version: int | None = None) -> EntityRef:
    return EntityRef(entity_type=entity_type, entity_id=str(entity_id), version=version)


def _handoff(
    *,
    run_id: UUID,
    sender: AgentRole,
    receiver: AgentRole,
    task_type: str,
    goal: str,
    input_refs: tuple[EntityRef, ...],
    output_schema: str,
    result_refs: tuple[EntityRef, ...] = (),
    warning: str | None = None,
) -> AgentHandoff:
    now = datetime.now(UTC)
    return AgentHandoff(
        run_id=run_id,
        sender=sender,
        receiver=receiver,
        task_type=task_type,
        goal=goal,
        input_refs=input_refs,
        expected_output_schema=output_schema,
        status="partial" if warning else "completed",
        result_refs=result_refs,
        warnings=(warning,) if warning else (),
        created_at=now,
        completed_at=now,
    )


def _multi_subject_request(request: TripRequest, summary: str) -> TripRequest:
    titles = tuple(dict.fromkeys(item.strip() for item in _TITLE.findall(summary)))[:3]
    if len(titles) <= 1 or len(request.subject_intents) > 1:
        return request
    primary_title = next(
        (title for title in titles if f"主要巡礼《{title}》" in summary), titles[0]
    )
    intents = tuple(
        SubjectIntent(
            query=title,
            priority=5 if title == primary_title else 3,
            is_primary=title == primary_title,
        )
        for title in titles
    )
    return request.model_copy(
        update={"anime_query": primary_title, "subject_intents": intents}
    )


def _medoid(places: tuple[VisitPlace, ...]) -> VisitPlace:
    return min(
        places,
        key=lambda candidate: (
            sum(
                haversine_meters(candidate.coordinate, item.coordinate)
                for item in places
            ),
            str(candidate.place_id),
        ),
    )


def _estimated_base(places: tuple[VisitPlace, ...]) -> BaseCandidate:
    medoid = _medoid(places)
    return BaseCandidate(
        base_id="place-medoid-estimate",
        name=f"{medoid.canonical_name} · estimated base area",
        coordinate=medoid.coordinate,
        provenance=DataProvenance(
            provider="deterministic-base",
            fetched_at=datetime.now(UTC),
            expires_at=datetime.now(UTC) + timedelta(hours=12),
            status=DataStatus.ESTIMATED,
        ),
    )


def _derived_timezone(coordinate: GeoCoordinate) -> str:
    if 24 <= coordinate.latitude <= 46 and 122 <= coordinate.longitude <= 146:
        return "Asia/Tokyo"
    if 41 <= coordinate.latitude <= 52 and -5 <= coordinate.longitude <= 10:
        return "Europe/Paris"
    if 24 <= coordinate.latitude <= 50 and -126 <= coordinate.longitude <= -66:
        return "America/New_York"
    return "UTC"


class WorkspaceAgent:
    """Execute typed role steps while deterministic code owns membership and planning."""

    def __init__(
        self,
        tool_client: AgentToolClient,
        requirement_extractor: RequirementExtractor | None = None,
    ) -> None:
        self.tools = tool_client
        self.extractor = requirement_extractor or DeterministicRequirementExtractor()
        self.context_builder = RoleContextBuilder()

    async def start(self, request: WorkspaceStartRequest) -> WorkspaceState:
        extracted = (
            request.requirements
            if request.requirements is not None
            else (await self.extractor.extract(request.request_summary)).requirements
        )
        requirements = _multi_subject_request(extracted, request.request_summary)
        if not requirements.subject_intents:
            raise ValueError("at least one subject intent is required")
        run_id = uuid4()
        groups: list[SubjectCandidateGroup] = []
        handoffs: list[AgentHandoff] = []
        warnings: list[str] = []
        for intent in requirements.subject_intents:
            outcome = await invoke_tool(
                self.tools,
                "search_anime_subjects",
                {"query": intent.query, "limit": 5},
                SubjectSearchResult,
            )
            if outcome.value is None:
                warning = outcome.safe_warning or "Subject search is unavailable."
                group = SubjectCandidateGroup(
                    intent=intent,
                    candidates=(),
                    status="unavailable",
                    warning=warning,
                )
                warnings.append(f"{intent.query}: {warning}")
            elif not outcome.value.candidates:
                warning = "No catalog candidate was found; nothing was guessed."
                group = SubjectCandidateGroup(
                    intent=intent,
                    candidates=(),
                    status="not_found",
                    warning=warning,
                )
                warnings.append(f"{intent.query}: {warning}")
            else:
                warning = None
                group = SubjectCandidateGroup(
                    intent=intent,
                    candidates=outcome.value.candidates,
                    status="ok",
                )
            groups.append(group)
            handoffs.append(
                _handoff(
                    run_id=run_id,
                    sender=AgentRole.REQUIREMENT,
                    receiver=AgentRole.SUBJECT,
                    task_type="resolve_subject_intent",
                    goal=f"Return bounded catalog candidates for intent {intent.intent_id}.",
                    input_refs=(_ref("subject_intent", intent.intent_id),),
                    output_schema="SubjectCandidateGroup",
                    result_refs=tuple(
                        _ref("subject_candidate", item.subject_id)
                        for item in group.candidates
                    ),
                    warning=warning,
                )
            )
        return WorkspaceState(
            owner_user_id=request.owner_user_id,
            thread_id=request.thread_id,
            trip_id=request.trip_id,
            request_summary=request.request_summary,
            state_version=1,
            status=WorkspaceStatus.AWAITING_SUBJECTS,
            requirements=requirements,
            subject_groups=tuple(groups),
            handoffs=tuple(handoffs),
            warnings=tuple(warnings),
        )

    async def confirm_subjects(
        self, state: WorkspaceState, request: ConfirmWorkspaceSubjectsRequest
    ) -> WorkspaceState:
        if (request.owner_user_id, request.thread_id) != (
            state.owner_user_id,
            state.thread_id,
        ):
            raise ValueError("workspace namespace mismatch")
        if request.expected_state_version != state.state_version:
            raise ValueError("workspace state version conflict")
        confirmation_by_intent = {item.intent_id: item for item in request.confirmations}
        if len(confirmation_by_intent) != len(request.confirmations):
            raise ValueError("one confirmation is allowed per subject intent")
        group_by_intent = {item.intent.intent_id: item for item in state.subject_groups}
        if not set(confirmation_by_intent).issubset(group_by_intent):
            raise ValueError("confirmation references an unknown subject intent")
        run_id = uuid4()
        confirmed: list[ConfirmedWorkspaceSubject] = []
        evidence: list[SceneEvidence] = []
        warnings = list(state.warnings)
        handoffs = list(state.handoffs)
        updated_intents: list[SubjectIntent] = []
        for intent in state.requirements.subject_intents:
            confirmation = confirmation_by_intent.get(intent.intent_id)
            if confirmation is None:
                updated_intents.append(intent)
                continue
            if confirmation.decision == "reject":
                updated_intents.append(intent.model_copy(update={"status": "rejected"}))
                continue
            group = group_by_intent[intent.intent_id]
            candidate_ids = {item.subject_id for item in group.candidates}
            selected_ids = confirmation.selected_subject_ids
            if not set(selected_ids).issubset(candidate_ids):
                raise ValueError("selected subjects must belong to their own candidate group")
            confirmed_ids: list[str] = []
            for selected in selected_ids:
                subject_outcome = await invoke_tool(
                    self.tools,
                    "get_anime_subject",
                    {"subject_id": selected},
                    ConfirmedSubject,
                )
                if subject_outcome.value is None:
                    subject_warning = (
                        subject_outcome.safe_warning or "Subject verification failed."
                    )
                    warnings.append(f"{intent.query} ({selected}): {subject_warning}")
                    continue
                subject = subject_outcome.value
                confirmed_ids.append(subject.subject_id)
                point_outcome = await invoke_tool(
                    self.tools,
                    "fetch_pilgrimage_points",
                    PilgrimagePointQuery(
                        subject_id=subject.subject_id, provider="anitabi"
                    ).model_dump(mode="json"),
                    PilgrimagePointResult,
                )
                point_warning: str | None
                evidence_status: Literal["ok", "partial", "unavailable"]
                if point_outcome.value is None:
                    point_warning = (
                        point_outcome.safe_warning or "Scene evidence is unavailable."
                    )
                    evidence_status = "unavailable"
                    warnings.append(f"{intent.query}: {point_warning}")
                else:
                    evidence.extend(
                        evidence_from_point(item, trip_id=state.trip_id)
                        for item in point_outcome.value.points
                    )
                    point_warning = "; ".join(point_outcome.value.warnings) or None
                    evidence_status = (
                        "ok" if point_outcome.value.is_complete else "partial"
                    )
                    if point_warning:
                        warnings.append(f"{intent.query}: {point_warning}")
                confirmed.append(
                    ConfirmedWorkspaceSubject(
                        intent_id=intent.intent_id,
                        subject=subject,
                        evidence_status=evidence_status,
                        warning=point_warning,
                    )
                )
                handoffs.append(
                    _handoff(
                        run_id=run_id,
                        sender=AgentRole.SUBJECT,
                        receiver=AgentRole.EVIDENCE_COLLECTOR,
                        task_type="collect_subject_evidence",
                        goal=(
                            "Collect normalized scene evidence for subject "
                            f"{subject.subject_id}."
                        ),
                        input_refs=(_ref("subject", subject.subject_id),),
                        output_schema="SceneEvidence[]",
                        result_refs=tuple(
                            _ref("scene_evidence", item.evidence_id)
                            for item in evidence
                            if item.subject_id == subject.subject_id
                        ),
                        warning=point_warning,
                    )
                )
            if confirmed_ids:
                updated_intents.append(
                    intent.model_copy(
                        update={
                            "confirmed_subject_id": confirmed_ids[0],
                            "confirmed_subject_ids": tuple(confirmed_ids),
                            "status": "confirmed",
                        }
                    )
                )
            else:
                updated_intents.append(intent)
        requirements = state.requirements.model_copy(
            update={"subject_intents": tuple(updated_intents)}
        )
        places: tuple[VisitPlace, ...] = ()
        areas: tuple[AreaCluster, ...] = ()
        quarantined: tuple[EvidenceQuarantine, ...] = ()
        ambiguous: tuple[AmbiguousPlaceMerge, ...] = ()
        bases: tuple[BaseCandidate, ...] = ()
        if evidence:
            resolution = resolve_places(evidence)
            places = resolution.places
            quarantined = resolution.quarantined
            ambiguous = resolution.ambiguous_merges
            areas = cluster_places(places)
            bases = (_estimated_base(places),)
            handoffs.append(
                _handoff(
                    run_id=run_id,
                    sender=AgentRole.EVIDENCE_COLLECTOR,
                    receiver=AgentRole.PLACE_CURATOR,
                    task_type="resolve_places_and_areas",
                    goal="Resolve evidence to canonical places and stable visit areas.",
                    input_refs=tuple(
                        _ref("scene_evidence", item.evidence_id) for item in evidence
                    ),
                    output_schema="PlaceResolutionResult + AreaCluster[]",
                    result_refs=(
                        *(_ref("visit_place", item.place_id) for item in places),
                        *(_ref("area", item.area_id) for item in areas),
                    ),
                )
            )
        partial = any(item.evidence_status != "ok" for item in confirmed)
        status = (
            WorkspaceStatus.PARTIAL_READY if places and partial else
            WorkspaceStatus.READY if places else WorkspaceStatus.PARTIAL
        )
        return state.model_copy(
            update={
                "state_version": state.state_version + 1,
                "status": status,
                "requirements": requirements,
                "confirmed_subjects": tuple(confirmed),
                "evidence": tuple(evidence),
                "quarantined": quarantined,
                "ambiguous_merges": ambiguous,
                "places": places,
                "areas": areas,
                "base_candidates": bases,
                "handoffs": tuple(handoffs),
                "warnings": tuple(warnings),
            }
        )

    def _execute_plan(
        self,
        state: WorkspaceState,
        *,
        base_id: str,
        access: AccessSelection | None,
        timezone: str | None,
        strategies: tuple[PlanningStrategy, ...],
        next_version: int,
        patch_id: UUID | None = None,
    ) -> WorkspaceState:
        if not state.places or not state.areas:
            raise ValueError("workspace has no canonical places to plan")
        by_base = {item.base_id: item for item in state.base_candidates}
        if base_id not in by_base:
            raise ValueError("selected base must belong to the workspace candidates")
        base = by_base[base_id]
        selected_timezone = timezone or _derived_timezone(base.coordinate)
        run_id = uuid4()
        result = plan_hierarchical_itineraries(
            HierarchicalPlanningRequest(
                trip_id=state.trip_id,
                requirements=state.requirements,
                places=state.places,
                areas=state.areas,
                base=base,
                access=access,
                timezone=selected_timezone,
                strategies=strategies,
                must_visit_place_ids=state.must_visit_place_ids,
                excluded_place_ids=state.excluded_place_ids,
                graph_version=next_version,
                itinerary_version=next_version,
                fixed_day_assignments=state.fixed_day_assignments,
                fixed_positions=state.fixed_positions,
                knowledge_rules=state.knowledge_rules,
            )
        )
        parent_by_strategy = {
            strategy: max(
                item.version for item in state.itineraries if item.strategy == strategy
            )
            for strategy in {item.strategy for item in state.itineraries}
        }
        new_itineraries = tuple(
            item.model_copy(
                update={
                    "parent_version": parent_by_strategy.get(item.strategy),
                    "applied_patch_id": patch_id,
                }
            )
            for item in result.itineraries
        )
        priority_summary = tuple(
            f"{item.query}:priority={item.priority}:minimum={item.minimum_place_count}"
            for item in state.requirements.subject_intents
        )
        contexts = tuple(
            self.context_builder.reviewer(
                run_id=run_id,
                itinerary=item,
                user_priorities=priority_summary,
                evidence_status=result.candidate_graph.evidence_status,
            )
            for item in new_itineraries
        )
        handoffs = (
            *state.handoffs,
            _handoff(
                run_id=run_id,
                sender=AgentRole.PLACE_CURATOR,
                receiver=AgentRole.ITINERARY_PLANNER,
                task_type="build_strategy_versions",
                goal="Build independent hierarchical itinerary alternatives.",
                input_refs=(
                    *(_ref("visit_place", item.place_id) for item in state.places),
                    *(_ref("area", item.area_id) for item in state.areas),
                    _ref("base", base.base_id),
                ),
                output_schema="ItineraryVersion[]",
                result_refs=tuple(
                    _ref("itinerary", item.itinerary_id, item.version)
                    for item in new_itineraries
                ),
            ),
            _handoff(
                run_id=run_id,
                sender=AgentRole.ITINERARY_PLANNER,
                receiver=AgentRole.VALIDATOR,
                task_type="validate_strategy_versions",
                goal="Validate membership, coverage, walking, time and omissions.",
                input_refs=tuple(
                    _ref("itinerary", item.itinerary_id, item.version)
                    for item in new_itineraries
                ),
                output_schema="ValidationIssue[]",
                result_refs=tuple(
                    _ref("itinerary", item.itinerary_id, item.version)
                    for item in new_itineraries
                ),
                warning=(
                    "One or more strategy versions retain deterministic violations."
                    if any(item.validation_issues for item in new_itineraries)
                    else None
                ),
            ),
            _handoff(
                run_id=run_id,
                sender=AgentRole.VALIDATOR,
                receiver=AgentRole.REVIEWER,
                task_type="review_normalized_plan_quality",
                goal="Review coverage, omissions and priorities without overriding validation.",
                input_refs=tuple(
                    _ref("role_context", item.context_id) for item in contexts
                ),
                output_schema="ReviewerAssessment",
                result_refs=tuple(
                    _ref("itinerary", item.itinerary_id, item.version)
                    for item in new_itineraries
                ),
            ),
        )
        return state.model_copy(
            update={
                "state_version": next_version,
                "status": (
                    WorkspaceStatus.PARTIAL
                    if any(item.validation_issues for item in new_itineraries)
                    else WorkspaceStatus.PLANNED
                ),
                "selected_base_id": base_id,
                "selected_access": access,
                "planning_strategies": strategies,
                "candidate_graph": result.candidate_graph,
                "itineraries": (*new_itineraries, *state.itineraries),
                "handoffs": handoffs,
                "contexts": (*state.contexts, *contexts),
            }
        )

    def plan(self, state: WorkspaceState, request: PlanWorkspaceRequest) -> WorkspaceState:
        if (request.owner_user_id, request.thread_id) != (
            state.owner_user_id,
            state.thread_id,
        ):
            raise ValueError("workspace namespace mismatch")
        if request.expected_state_version != state.state_version:
            raise ValueError("workspace state version conflict")
        prepared = state.model_copy(
            update={
                "must_visit_place_ids": request.must_visit_place_ids,
                "excluded_place_ids": request.excluded_place_ids,
            }
        )
        return self._execute_plan(
            prepared,
            base_id=request.base_id,
            access=request.access,
            timezone=request.timezone,
            strategies=request.strategies,
            next_version=state.state_version + 1,
        )

    def propose_patch(
        self, state: WorkspaceState, patch: PlanPatch
    ) -> tuple[WorkspaceState, PlanPatchPreview]:
        if patch.trip_id != state.trip_id:
            raise ValueError("patch trip does not match the workspace")
        existing = next(
            (item for item in state.patches if item.idempotency_key == patch.idempotency_key),
            None,
        )
        if existing is not None:
            impact = next(item for item in state.impacts if item.patch_id == existing.patch_id)
            return state, PlanPatchPreview(patch=existing, impact=impact)
        if patch.expected_base_version != state.state_version:
            raise ValueError("workspace state version conflict")
        normalized = normalize_patch(patch)
        impact = analyze_impact(normalized)
        updated = state.model_copy(
            update={
                "patches": (*state.patches, normalized),
                "impacts": (*state.impacts, impact),
                "pending_patch_id": normalized.patch_id,
            }
        )
        return updated, PlanPatchPreview(patch=normalized, impact=impact)

    async def apply_patch(
        self,
        state: WorkspaceState,
        patch_id: UUID,
        *,
        confirm: bool,
    ) -> WorkspaceState:
        patch = next((item for item in state.patches if item.patch_id == patch_id), None)
        if patch is None:
            raise ValueError("patch was not found in this workspace")
        if patch.status == "applied":
            return state
        if patch.expected_base_version != state.state_version:
            raise ValueError("workspace state version conflict")
        if patch.requires_confirmation and not confirm:
            raise ValueError("material patch requires explicit confirmation")
        impact = next(item for item in state.impacts if item.patch_id == patch.patch_id)
        requirements_data = state.requirements.model_dump(mode="python")
        intents = list(state.requirements.subject_intents)
        groups = list(state.subject_groups)
        confirmed = list(state.confirmed_subjects)
        evidence = list(state.evidence)
        overrides = list(state.resolution_overrides)
        must_visit = set(state.must_visit_place_ids)
        excluded = set(state.excluded_place_ids)
        fixed_days = dict(state.fixed_day_assignments)
        fixed_positions = dict(state.fixed_positions)
        attached_knowledge = set(state.attached_knowledge_ids)
        selected_base_id = state.selected_base_id
        selected_access = state.selected_access
        strategies = list(state.planning_strategies)
        changed_requirements: set[str] = set()
        changed_intents: set[UUID] = set()
        changed_places: set[UUID] = set()
        changed_days: set[int] = set()
        changed_access = False
        changed_base = False
        changed_strategy = False
        recurate = False
        added_unconfirmed = False
        original_start = state.requirements.start_date
        original_end = state.requirements.end_date
        explicit_end_change = any(
            isinstance(item, UpdateRequirementOperation) and item.field == "end_date"
            for item in patch.operations
        )
        for operation in patch.operations:
            if isinstance(operation, UpdateRequirementOperation):
                requirements_data[operation.field] = operation.value
                changed_requirements.add(operation.field)
                if (
                    operation.field == "start_date"
                    and isinstance(operation.value, date)
                    and original_start is not None
                    and original_end is not None
                    and not explicit_end_change
                ):
                    requirements_data["end_date"] = operation.value + (
                        original_end - original_start
                    )
                    changed_requirements.add("end_date")
            elif isinstance(operation, SubjectIntentOperation):
                if operation.action == "add":
                    assert operation.intent is not None
                    if len(intents) >= 3:
                        raise ValueError("a workspace supports at most three subjects")
                    if any(item.query == operation.intent.query for item in intents):
                        raise ValueError("subject intent already exists")
                    intents.append(operation.intent)
                    changed_intents.add(operation.intent.intent_id)
                    outcome = await invoke_tool(
                        self.tools,
                        "search_anime_subjects",
                        {"query": operation.intent.query, "limit": 5},
                        SubjectSearchResult,
                    )
                    groups.append(
                        SubjectCandidateGroup(
                            intent=operation.intent,
                            candidates=outcome.value.candidates if outcome.value else (),
                            status=(
                                "ok"
                                if outcome.value and outcome.value.candidates
                                else "not_found"
                                if outcome.value
                                else "unavailable"
                            ),
                            warning=outcome.safe_warning,
                        )
                    )
                    added_unconfirmed = True
                else:
                    assert operation.intent_id is not None
                    index = next(
                        (
                            index
                            for index, item in enumerate(intents)
                            if item.intent_id == operation.intent_id
                        ),
                        None,
                    )
                    if index is None:
                        raise ValueError("subject intent does not belong to the workspace")
                    current_intent = intents[index]
                    changed_intents.add(current_intent.intent_id)
                    if operation.action == "remove":
                        if len(intents) == 1:
                            raise ValueError("a workspace must retain at least one subject")
                        intents.pop(index)
                        groups = [
                            item
                            for item in groups
                            if item.intent.intent_id != current_intent.intent_id
                        ]
                        confirmed = [
                            item
                            for item in confirmed
                            if item.intent_id != current_intent.intent_id
                        ]
                        if current_intent.catalog_subject_ids:
                            removed_subject_ids = set(
                                current_intent.catalog_subject_ids
                            )
                            evidence = [
                                item
                                for item in evidence
                                if item.subject_id not in removed_subject_ids
                            ]
                            recurate = True
                    elif operation.action == "reprioritize":
                        intents[index] = current_intent.model_copy(
                            update={"priority": operation.priority}
                        )
                    elif operation.action == "reject":
                        intents[index] = current_intent.model_copy(
                            update={
                                "status": "rejected",
                                "confirmed_subject_id": None,
                                "confirmed_subject_ids": (),
                            }
                        )
                    else:
                        raise ValueError(
                            "subject confirmation uses the candidate confirmation endpoint"
                        )
            elif isinstance(operation, PlaceOperation):
                if operation.place_id not in {item.place_id for item in state.places}:
                    raise ValueError("place does not belong to the workspace")
                changed_places.add(operation.place_id)
                if operation.action == "include":
                    excluded.discard(operation.place_id)
                elif operation.action == "exclude":
                    excluded.add(operation.place_id)
                    must_visit.discard(operation.place_id)
                elif operation.action == "move_day":
                    assert operation.target_day is not None
                    fixed_days[operation.place_id] = operation.target_day
                    changed_days.add(operation.target_day)
                else:
                    assert operation.target_day is not None
                    assert operation.target_position is not None
                    fixed_days[operation.place_id] = operation.target_day
                    fixed_positions[operation.place_id] = operation.target_position
                    changed_days.add(operation.target_day)
            elif isinstance(operation, SelectionOperation):
                if operation.action == "change_base":
                    assert operation.selection_id is not None
                    if operation.selection_id not in {
                        item.base_id for item in state.base_candidates
                    }:
                        raise ValueError("base candidate does not belong to the workspace")
                    selected_base_id = operation.selection_id
                    changed_base = True
                elif operation.action == "change_access":
                    if operation.selection_id != "clear":
                        raise ValueError(
                            "only the explicit clear access selection is currently available"
                        )
                    selected_access = None
                    changed_access = True
                elif operation.action == "change_strategy":
                    assert operation.strategy is not None
                    alternatives = [
                        operation.strategy,
                        *(
                            item
                            for item in strategies
                            if item is not operation.strategy
                        ),
                    ]
                    strategies = alternatives[: max(2, len(strategies))]
                    if len(strategies) == 1:
                        strategies.append(PlanningStrategy.BALANCED)
                    changed_strategy = True
                else:
                    changed_strategy = True
            elif isinstance(operation, KnowledgeOperation):
                if operation.action == "attach":
                    attached_knowledge.add(operation.document_id)
                else:
                    attached_knowledge.discard(operation.document_id)
            else:
                action = "merge" if operation.action == "accept_merge" else "split"
                evidence_ids = {item.evidence_id for item in evidence}
                if not set(operation.evidence_ids).issubset(evidence_ids):
                    raise ValueError("merge decision references unknown evidence")
                overrides.append(
                    PlaceResolutionOverride(
                        action=action,
                        evidence_ids=operation.evidence_ids,
                        reason=patch.rationale,
                        created_at=datetime.now(UTC),
                    )
                )
                recurate = True

        if intents and not any(item.is_primary for item in intents):
            selected_primary = max(intents, key=lambda item: (item.priority, str(item.intent_id)))
            intents = [
                item.model_copy(update={"is_primary": item.intent_id == selected_primary.intent_id})
                for item in intents
            ]
        requirements_data["subject_intents"] = tuple(intents)
        requirements_data["anime_query"] = next(
            item.query for item in intents if item.is_primary
        )
        requirements = TripRequest.model_validate(requirements_data)
        places = state.places
        areas = state.areas
        quarantined = state.quarantined
        ambiguous = state.ambiguous_merges
        bases = state.base_candidates
        if recurate:
            resolution = resolve_places(evidence, overrides=tuple(overrides))
            places = resolution.places
            quarantined = resolution.quarantined
            ambiguous = resolution.ambiguous_merges
            areas = cluster_places(places) if places else ()
            bases = (_estimated_base(places),) if places else ()
            if selected_base_id not in {item.base_id for item in bases}:
                selected_base_id = bases[0].base_id if bases else None
                changed_base = True
            current_place_ids = {item.place_id for item in places}
            must_visit.intersection_update(current_place_ids)
            excluded.intersection_update(current_place_ids)
            fixed_days = {
                key: value for key, value in fixed_days.items() if key in current_place_ids
            }
            fixed_positions = {
                key: value
                for key, value in fixed_positions.items()
                if key in current_place_ids
            }
        applied_patch = patch.model_copy(update={"status": "applied"})
        patches = tuple(
            applied_patch if item.patch_id == patch.patch_id else item
            for item in state.patches
        )
        working = state.model_copy(
            update={
                "requirements": requirements,
                "subject_groups": tuple(groups),
                "confirmed_subjects": tuple(confirmed),
                "evidence": tuple(evidence),
                "resolution_overrides": tuple(overrides),
                "places": places,
                "areas": areas,
                "quarantined": quarantined,
                "ambiguous_merges": ambiguous,
                "base_candidates": bases,
                "selected_base_id": selected_base_id,
                "selected_access": selected_access,
                "planning_strategies": tuple(dict.fromkeys(strategies)),
                "must_visit_place_ids": frozenset(must_visit),
                "excluded_place_ids": frozenset(excluded),
                "fixed_day_assignments": fixed_days,
                "fixed_positions": fixed_positions,
                "attached_knowledge_ids": frozenset(attached_knowledge),
                "patches": patches,
                "pending_patch_id": None,
            }
        )
        before_codes = tuple(
            sorted(
                {
                    issue.code
                    for itinerary in state.itineraries
                    for issue in itinerary.validation_issues
                }
            )
        )
        can_plan = bool(
            state.itineraries
            and places
            and areas
            and selected_base_id
            and requirements.start_date
            and requirements.end_date
            and not added_unconfirmed
        )
        if can_plan:
            assert selected_base_id is not None
            updated = self._execute_plan(
                working,
                base_id=selected_base_id,
                access=selected_access,
                timezone=(state.itineraries[0].timezone if state.itineraries else None),
                strategies=tuple(dict.fromkeys(strategies)),
                next_version=state.state_version + 1,
                patch_id=patch.patch_id,
            )
        else:
            updated = working.model_copy(
                update={
                    "state_version": state.state_version + 1,
                    "status": (
                        WorkspaceStatus.AWAITING_SUBJECTS
                        if added_unconfirmed
                        else WorkspaceStatus.PARTIAL
                    ),
                    "candidate_graph": (
                        None
                        if recurate or added_unconfirmed
                        else state.candidate_graph
                    ),
                    "itineraries": () if recurate or added_unconfirmed else state.itineraries,
                }
            )
        after_codes = tuple(
            sorted(
                {
                    issue.code
                    for itinerary in updated.itineraries
                    for issue in itinerary.validation_issues
                }
            )
        )
        diff = PlanVersionDiff(
            from_version=state.state_version,
            to_version=updated.state_version,
            changed_requirements=tuple(sorted(changed_requirements)),
            changed_subject_intents=tuple(sorted(changed_intents, key=str)),
            changed_place_ids=tuple(sorted(changed_places, key=str)),
            changed_day_numbers=tuple(sorted(changed_days)),
            changed_access=changed_access,
            changed_base=changed_base,
            changed_strategy=changed_strategy,
            validation_before=before_codes,
            validation_after=after_codes,
        )
        run_id = uuid4()
        replan_context = self.context_builder.replanner(
            run_id=run_id,
            patch=patch,
            impact=impact,
            validation_before=before_codes,
            validation_after=after_codes,
        )
        return updated.model_copy(
            update={
                "diffs": (*state.diffs, diff),
                "contexts": (*updated.contexts, replan_context),
                "handoffs": (
                    *updated.handoffs,
                    _handoff(
                        run_id=run_id,
                        sender=AgentRole.REPLANNER,
                        receiver=AgentRole.VALIDATOR,
                        task_type="apply_patch_and_revalidate",
                        goal="Apply the confirmed patch and retain deterministic violations.",
                        input_refs=(_ref("patch", patch.patch_id),),
                        output_schema="PlanVersionDiff + ValidationIssue[]",
                        result_refs=(_ref("state", state.trip_id, updated.state_version),),
                        warning=(
                            "Deterministic violations remain visible after replanning."
                            if after_codes
                            else None
                        ),
                    ),
                ),
            }
        )
