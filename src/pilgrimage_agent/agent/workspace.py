"""Multi-subject workspace Agent with typed role handoffs and bounded projections."""

from __future__ import annotations

import re
from datetime import UTC, datetime, timedelta
from enum import StrEnum
from typing import Literal
from uuid import UUID, uuid4

from pydantic import Field, model_validator

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
    EntityRef,
    EvidenceQuarantine,
    ItineraryVersion,
    PlanningStrategy,
    SceneEvidence,
    TripCandidateGraph,
    VisitPlace,
)
from pilgrimage_agent.planning.areas import cluster_places
from pilgrimage_agent.planning.geo import haversine_meters
from pilgrimage_agent.planning.hierarchical import (
    HierarchicalPlanningRequest,
    plan_hierarchical_itineraries,
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

    @model_validator(mode="after")
    def selected_id_matches_decision(self) -> SubjectConfirmation:
        if (self.decision == "accept") != (self.selected_subject_id is not None):
            raise ValueError("accepted subject confirmations require exactly one selected ID")
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
    places: tuple[VisitPlace, ...] = ()
    areas: tuple[AreaCluster, ...] = ()
    base_candidates: tuple[BaseCandidate, ...] = ()
    candidate_graph: TripCandidateGraph | None = None
    itineraries: tuple[ItineraryVersion, ...] = ()
    handoffs: tuple[AgentHandoff, ...] = ()
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
    candidate_graph: TripCandidateGraph | None
    itineraries: tuple[ItineraryVersion, ...]
    handoffs: tuple[AgentHandoff, ...]
    counts: WorkspaceCounts
    warnings: tuple[str, ...]


class WorkspaceEvidenceView(StrictModel):
    trip_id: UUID
    evidence: tuple[SceneEvidence, ...]
    quarantined: tuple[EvidenceQuarantine, ...]
    ambiguous_merges: tuple[AmbiguousPlaceMerge, ...]


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
        candidate_graph=state.candidate_graph,
        itineraries=state.itineraries,
        handoffs=state.handoffs,
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
            selected = confirmation.selected_subject_id
            if selected not in candidate_ids:
                raise ValueError("a selected subject must belong to its own candidate group")
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
                warnings.append(f"{intent.query}: {subject_warning}")
                updated_intents.append(intent)
                continue
            subject = subject_outcome.value
            updated_intents.append(
                intent.model_copy(
                    update={
                        "confirmed_subject_id": subject.subject_id,
                        "status": "confirmed",
                    }
                )
            )
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
                evidence.extend(evidence_from_point(item) for item in point_outcome.value.points)
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
                    goal=f"Collect normalized scene evidence for subject {subject.subject_id}.",
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

    def plan(self, state: WorkspaceState, request: PlanWorkspaceRequest) -> WorkspaceState:
        if (request.owner_user_id, request.thread_id) != (
            state.owner_user_id,
            state.thread_id,
        ):
            raise ValueError("workspace namespace mismatch")
        if request.expected_state_version != state.state_version:
            raise ValueError("workspace state version conflict")
        if not state.places or not state.areas:
            raise ValueError("workspace has no canonical places to plan")
        by_base = {item.base_id: item for item in state.base_candidates}
        if request.base_id not in by_base:
            raise ValueError("selected base must belong to the workspace candidates")
        base = by_base[request.base_id]
        timezone = request.timezone or _derived_timezone(base.coordinate)
        run_id = uuid4()
        result = plan_hierarchical_itineraries(
            HierarchicalPlanningRequest(
                trip_id=state.trip_id,
                requirements=state.requirements,
                places=state.places,
                areas=state.areas,
                base=base,
                access=request.access,
                timezone=timezone,
                strategies=request.strategies,
                must_visit_place_ids=request.must_visit_place_ids,
                excluded_place_ids=request.excluded_place_ids,
                graph_version=state.state_version,
                itinerary_version=1,
            )
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
                    for item in result.itineraries
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
                    for item in result.itineraries
                ),
                output_schema="ValidationIssue[]",
                result_refs=tuple(
                    _ref("itinerary", item.itinerary_id, item.version)
                    for item in result.itineraries
                ),
                warning=(
                    "One or more strategy versions retain deterministic violations."
                    if any(item.validation_issues for item in result.itineraries)
                    else None
                ),
            ),
        )
        return state.model_copy(
            update={
                "state_version": state.state_version + 1,
                "status": WorkspaceStatus.PLANNED,
                "candidate_graph": result.candidate_graph,
                "itineraries": result.itineraries,
                "handoffs": handoffs,
            }
        )
