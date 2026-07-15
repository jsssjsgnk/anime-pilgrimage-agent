"""Multi-subject workspace Agent with typed role handoffs and bounded projections."""

from __future__ import annotations

import asyncio
import re
from datetime import UTC, date, datetime, time, timedelta
from enum import StrEnum
from itertools import combinations
from typing import Literal
from uuid import UUID, uuid4
from zoneinfo import ZoneInfo

from pydantic import Field, model_validator

from pilgrimage_agent.agent.context import RoleContextBuilder
from pilgrimage_agent.agent.knowledge import (
    EmptyKnowledgeRetriever,
    EmptyKnowledgeRuleProposer,
    KnowledgeRetriever,
    KnowledgeRuleProposer,
)
from pilgrimage_agent.agent.llm import DeterministicRequirementExtractor, RequirementExtractor
from pilgrimage_agent.agent.mcp_client import AgentToolClient
from pilgrimage_agent.curation.resolution import evidence_from_point, resolve_places
from pilgrimage_agent.domain.models import (
    ConfirmedSubject,
    DataProvenance,
    DataStatus,
    FlightOption,
    FlightSearchQuery,
    FlightSearchResult,
    GeoCoordinate,
    MatrixQuery,
    PilgrimagePointQuery,
    PilgrimagePointResult,
    PlaceDetailsQuery,
    PlaceFact,
    PlaceFactsResult,
    PlaceFactsSearchQuery,
    PlaceSearchQuery,
    PlaceSearchResult,
    RouteMatrix,
    StrictModel,
    SubjectCandidate,
    SubjectIntent,
    SubjectSearchResult,
    TransitOption,
    TransitRouteQuery,
    TransitRouteResult,
    TripRequest,
    WeatherForecastQuery,
    WeatherForecastResult,
)
from pilgrimage_agent.domain.planning import (
    AccessMode,
    AccessOption,
    AccessSelection,
    BaseCandidate,
)
from pilgrimage_agent.domain.workspace import (
    AgentHandoff,
    AgentRole,
    AmbiguousPlaceMerge,
    AreaCluster,
    AreaTransitEdge,
    ContextFact,
    DerivedKnowledgeRule,
    EntityRef,
    EvidenceQuarantine,
    ImpactAnalysis,
    ItineraryDay,
    ItineraryVersion,
    KnowledgeOperation,
    PlaceOperation,
    PlaceResolutionOverride,
    PlaceWalkingEdge,
    PlanningStrategy,
    PlanPatch,
    PlanVersionDiff,
    RoleContext,
    SceneEvidence,
    SelectionOperation,
    StructuredOmission,
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
from pilgrimage_agent.providers.cache import request_fingerprint
from pilgrimage_agent.providers.outcomes import ToolOutcome, invoke_tool
from pilgrimage_agent.rag.rules import KnowledgeRuleProposalInput, validate_derived_rule
from pilgrimage_agent.rag.schemas import (
    EvidenceConflict,
    KnowledgeSearchResult,
    RetrievedEvidence,
)

_TITLE = re.compile(r"《([^》]{1,100})》")


class WorkspaceStatus(StrEnum):
    AWAITING_SUBJECTS = "awaiting_subject_confirmation"
    READY = "ready_for_planning"
    PARTIAL_READY = "partial_ready_for_planning"
    PLANNED = "planned"
    PARTIAL = "partial"
    READY_TO_PLAN = "ready_to_plan"
    ARCHIVED = "archived"


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
    point_collection: PointCollectionSummary | None = None


class PointCollectionSummary(StrictModel):
    provider: str = Field(min_length=1, max_length=80)
    is_complete: bool
    expected_count: int = Field(ge=0)
    loaded_count: int = Field(ge=0)
    data_version: str | None = Field(default=None, max_length=120)
    retrieved_at: datetime
    expires_at: datetime | None = None


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
    confirmations: tuple[SubjectConfirmation, ...] = Field(min_length=1, max_length=12)


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


class WorkspaceMutationRequest(StrictModel):
    owner_user_id: str = Field(min_length=1, max_length=120)
    thread_id: str = Field(min_length=1, max_length=120)
    expected_state_version: int = Field(ge=1)


class ClearWorkspaceDayRequest(WorkspaceMutationRequest):
    day_number: int = Field(ge=1, le=30)


class WorkspaceCounts(StrictModel):
    raw_scene_records: int = Field(ge=0)
    quarantined_records: int = Field(ge=0)
    canonical_places: int = Field(ge=0)
    areas: int = Field(ge=0)
    recommended_places: int = Field(ge=0)
    scheduled_places: int = Field(ge=0)


class WorkspaceReviewerAssessment(StrictModel):
    itinerary_id: UUID
    itinerary_version: int = Field(ge=1)
    action: Literal["accept", "revise", "unavailable"]
    target_day: int | None = Field(default=None, ge=1, le=30)
    explanation: str = Field(min_length=1, max_length=500)
    source: Literal["llm", "fixture", "unavailable"]
    created_at: datetime


class ProviderSnapshot(StrictModel):
    snapshot_id: UUID = Field(default_factory=uuid4)
    kind: Literal[
        "flight", "transit", "walking_matrix", "area_transit", "place", "weather"
    ]
    query_fingerprint: str = Field(pattern=r"^[a-f0-9]{64}$")
    status: Literal["ok", "partial", "unavailable"]
    provenance: DataProvenance | None = None
    result_refs: tuple[EntityRef, ...] = ()
    warning: str | None = Field(default=None, max_length=500)


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
    access_candidates: tuple[AccessOption, ...] = ()
    flight_options: tuple[FlightOption, ...] = ()
    transit_options: tuple[TransitOption, ...] = ()
    area_transit_edges: tuple[AreaTransitEdge, ...] = ()
    walking_edges: tuple[PlaceWalkingEdge, ...] = ()
    place_facts: dict[UUID, PlaceFact] = Field(default_factory=dict)
    weather_forecast: WeatherForecastResult | None = None
    provider_snapshots: tuple[ProviderSnapshot, ...] = ()
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
    knowledge_evidence: tuple[RetrievedEvidence, ...] = ()
    knowledge_evidence_documents: dict[str, UUID] = Field(default_factory=dict)
    candidate_graph: TripCandidateGraph | None = None
    itineraries: tuple[ItineraryVersion, ...] = ()
    archived_itineraries: tuple[ItineraryVersion, ...] = ()
    handoffs: tuple[AgentHandoff, ...] = ()
    contexts: tuple[RoleContext, ...] = ()
    reviewer_assessments: tuple[WorkspaceReviewerAssessment, ...] = ()
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
    access_candidates: tuple[AccessOption, ...] = ()
    area_transit_edges: tuple[AreaTransitEdge, ...] = ()
    walking_edges: tuple[PlaceWalkingEdge, ...] = ()
    place_facts: dict[UUID, PlaceFact] = Field(default_factory=dict)
    weather_forecast: WeatherForecastResult | None = None
    planning_strategies: tuple[PlanningStrategy, ...]
    must_visit_place_ids: frozenset[UUID]
    excluded_place_ids: frozenset[UUID]
    candidate_graph: TripCandidateGraph | None
    itineraries: tuple[ItineraryVersion, ...]
    handoffs: tuple[AgentHandoff, ...]
    contexts: tuple[RoleContext, ...]
    reviewer_assessments: tuple[WorkspaceReviewerAssessment, ...]
    patches: tuple[PlanPatch, ...]
    impacts: tuple[ImpactAnalysis, ...]
    diffs: tuple[PlanVersionDiff, ...]
    pending_patch_id: UUID | None
    knowledge_rules: tuple[DerivedKnowledgeRule, ...]
    knowledge_evidence: tuple[RetrievedEvidence, ...] = ()
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
    scheduled = {visit.place_id for day in active.days for visit in day.visits} if active else set()
    recommended = (
        sum(
            item.status in {"included", "recommended"}
            for item in state.candidate_graph.decisions
            if item.entity_type == "place"
        )
        if state.candidate_graph
        else len(state.places)
    )
    intent_by_id = {item.intent_id: item for item in state.requirements.subject_intents}
    projected_groups = tuple(
        group.model_copy(update={"intent": intent_by_id.get(group.intent.intent_id, group.intent)})
        for group in state.subject_groups
    )
    return WorkspaceView(
        thread_id=state.thread_id,
        trip_id=state.trip_id,
        state_version=state.state_version,
        status=state.status,
        requirements=state.requirements,
        subject_groups=projected_groups,
        confirmed_subjects=state.confirmed_subjects,
        places=state.places,
        areas=state.areas,
        base_candidates=state.base_candidates,
        selected_base_id=state.selected_base_id,
        access_candidates=state.access_candidates,
        area_transit_edges=state.area_transit_edges,
        walking_edges=state.walking_edges,
        place_facts=state.place_facts,
        weather_forecast=state.weather_forecast,
        planning_strategies=state.planning_strategies,
        must_visit_place_ids=state.must_visit_place_ids,
        excluded_place_ids=state.excluded_place_ids,
        candidate_graph=state.candidate_graph,
        itineraries=state.itineraries,
        handoffs=state.handoffs,
        contexts=state.contexts,
        reviewer_assessments=state.reviewer_assessments,
        patches=state.patches,
        impacts=state.impacts,
        diffs=state.diffs,
        pending_patch_id=state.pending_patch_id,
        knowledge_rules=state.knowledge_rules,
        knowledge_evidence=state.knowledge_evidence,
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
        started_at=now,
        completed_at=now,
    )


def _multi_subject_request(request: TripRequest, summary: str) -> TripRequest:
    titles = tuple(dict.fromkeys(item.strip() for item in _TITLE.findall(summary)))[:12]
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
    return request.model_copy(update={"anime_query": primary_title, "subject_intents": intents})


def _medoid(places: tuple[VisitPlace, ...]) -> VisitPlace:
    return min(
        places,
        key=lambda candidate: (
            sum(haversine_meters(candidate.coordinate, item.coordinate) for item in places),
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
        knowledge_retriever: KnowledgeRetriever | None = None,
        knowledge_rule_proposer: KnowledgeRuleProposer | None = None,
    ) -> None:
        self.tools = tool_client
        self.extractor = requirement_extractor or DeterministicRequirementExtractor()
        self.knowledge_retriever = knowledge_retriever or EmptyKnowledgeRetriever()
        self.knowledge_rule_proposer = (
            knowledge_rule_proposer or EmptyKnowledgeRuleProposer()
        )
        self.context_builder = RoleContextBuilder()

    async def extract_requirements(self, request: WorkspaceStartRequest) -> TripRequest:
        """Run the Requirement Agent boundary without performing subject lookup."""

        extracted = (await self.extractor.extract(request.request_summary)).requirements
        if request.requirements is not None:
            # ``requirements`` is an explicit-field overlay, not a replacement for the
            # Requirement Agent.  This lets date pickers and selected works coexist with
            # natural language such as "从京都出发、住新宿、尽量少走路" without default
            # model values silently erasing what the user actually said.
            explicit_fields = request.requirements.model_fields_set
            overrides = request.requirements.model_dump(
                mode="python", include=explicit_fields
            )
            extracted = TripRequest.model_validate(
                {**extracted.model_dump(mode="python"), **overrides}
            )
        return _multi_subject_request(extracted, request.request_summary)

    async def start(self, request: WorkspaceStartRequest) -> WorkspaceState:
        """Compatibility entry point; the product API uses the workspace graph."""

        requirements = await self.extract_requirements(request)
        return await self.resolve_subjects(
            request.model_copy(update={"requirements": requirements})
        )

    async def resolve_subjects(self, request: WorkspaceStartRequest) -> WorkspaceState:
        """Search bounded catalog candidates for already-normalized requirements."""

        if request.requirements is None:
            raise ValueError("normalized requirements are required before subject lookup")
        requirements = request.requirements
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
                        _ref("subject_candidate", item.subject_id) for item in group.candidates
                    ),
                    warning=warning,
                )
            )
        missing_fields = tuple(
            field
            for field in (
                "origin",
                "destination",
                "start_date",
                "end_date",
                "base_preference",
                "walking_preference",
            )
            if getattr(requirements, field) is None
        )
        requirement_context = self.context_builder.build(
            role=AgentRole.REQUIREMENT,
            run_id=run_id,
            facts=(
                ContextFact(key="latest_user_message", value=request.request_summary[:2000]),
                ContextFact(key="missing_fields", value=",".join(missing_fields) or "none"),
                ContextFact(
                    key="subject_intent_count",
                    value=len(requirements.subject_intents),
                ),
            ),
            refs=tuple(
                _ref("subject_intent", item.intent_id)
                for item in requirements.subject_intents
            ),
        )
        subject_context = self.context_builder.build(
            role=AgentRole.SUBJECT,
            run_id=run_id,
            facts=tuple(
                ContextFact(
                    key=f"intent_{index}",
                    value=(
                        f"query={group.intent.query};status={group.status};"
                        f"candidate_count={len(group.candidates)}"
                    ),
                )
                for index, group in enumerate(groups, start=1)
            ),
            refs=tuple(
                _ref("subject_candidate", item.subject_id)
                for group in groups
                for item in group.candidates
            ),
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
            contexts=(requirement_context, subject_context),
            warnings=tuple(warnings),
        )

    async def _confirm_subjects(
        self,
        state: WorkspaceState,
        request: ConfirmWorkspaceSubjectsRequest,
        *,
        curate: bool,
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
        changed_intent_ids = set(confirmation_by_intent)
        confirmed: list[ConfirmedWorkspaceSubject] = [
            item for item in state.confirmed_subjects if item.intent_id not in changed_intent_ids
        ]
        preserved_subject_ids = {item.subject.subject_id for item in confirmed}
        evidence: list[SceneEvidence] = [
            item for item in state.evidence if item.subject_id in preserved_subject_ids
        ]
        warnings = list(state.warnings)
        handoffs = list(state.handoffs)
        updated_intents: list[SubjectIntent] = []

        # Validate every requested selection before performing provider I/O, then
        # collect independent subjects concurrently.  Results are consumed below
        # in requirement/selection order so persisted state remains deterministic.
        selected_by_intent: dict[UUID, tuple[str, ...]] = {}
        pending_selections: list[tuple[UUID, str]] = []
        for intent_id, selection_request in confirmation_by_intent.items():
            if selection_request.decision == "reject":
                continue
            group = group_by_intent[intent_id]
            candidate_ids = {item.subject_id for item in group.candidates}
            selected_ids = selection_request.selected_subject_ids
            if not set(selected_ids).issubset(candidate_ids):
                raise ValueError("selected subjects must belong to their own candidate group")
            selected_by_intent[intent_id] = selected_ids
            pending_selections.extend((intent_id, selected) for selected in selected_ids)

        async def collect_selection(
            intent_id: UUID, selected: str
        ) -> tuple[
            UUID,
            str,
            ToolOutcome[ConfirmedSubject],
            ToolOutcome[PilgrimagePointResult] | None,
        ]:
            subject_outcome = await invoke_tool(
                self.tools,
                "get_anime_subject",
                {"subject_id": selected},
                ConfirmedSubject,
            )
            if subject_outcome.value is None:
                return intent_id, selected, subject_outcome, None
            point_outcome = await invoke_tool(
                self.tools,
                "fetch_pilgrimage_points",
                PilgrimagePointQuery(
                    subject_id=subject_outcome.value.subject_id,
                    provider="anitabi",
                ).model_dump(mode="json"),
                PilgrimagePointResult,
            )
            return intent_id, selected, subject_outcome, point_outcome

        collected = await asyncio.gather(
            *(collect_selection(intent_id, selected) for intent_id, selected in pending_selections)
        )
        collected_by_selection = {
            (intent_id, selected): (subject_outcome, point_outcome)
            for intent_id, selected, subject_outcome, point_outcome in collected
        }
        for intent in state.requirements.subject_intents:
            confirmation = confirmation_by_intent.get(intent.intent_id)
            if confirmation is None:
                updated_intents.append(intent)
                continue
            if confirmation.decision == "reject":
                updated_intents.append(intent.model_copy(update={"status": "rejected"}))
                continue
            selected_ids = selected_by_intent[intent.intent_id]
            confirmed_ids: list[str] = []
            for selected in selected_ids:
                subject_outcome, point_outcome = collected_by_selection[
                    (intent.intent_id, selected)
                ]
                if subject_outcome.value is None:
                    subject_warning = subject_outcome.safe_warning or "Subject verification failed."
                    warnings.append(f"{intent.query} ({selected}): {subject_warning}")
                    continue
                subject = subject_outcome.value
                confirmed_ids.append(subject.subject_id)
                assert point_outcome is not None
                point_warning: str | None
                evidence_status: Literal["ok", "partial", "unavailable"]
                if point_outcome.value is None:
                    point_warning = point_outcome.safe_warning or "Scene evidence is unavailable."
                    evidence_status = "unavailable"
                    point_collection = None
                    warnings.append(f"{intent.query}: {point_warning}")
                else:
                    evidence.extend(
                        evidence_from_point(item, trip_id=state.trip_id)
                        for item in point_outcome.value.points
                    )
                    point_warning = "; ".join(point_outcome.value.warnings) or None
                    evidence_status = "ok" if point_outcome.value.is_complete else "partial"
                    point_collection = PointCollectionSummary(
                        provider=point_outcome.value.provenance.provider,
                        is_complete=point_outcome.value.is_complete,
                        expected_count=point_outcome.value.expected_count,
                        loaded_count=point_outcome.value.loaded_count,
                        data_version=point_outcome.value.data_version,
                        retrieved_at=point_outcome.value.provenance.fetched_at,
                        expires_at=point_outcome.value.provenance.expires_at,
                    )
                    if point_warning:
                        warnings.append(f"{intent.query}: {point_warning}")
                confirmed.append(
                    ConfirmedWorkspaceSubject(
                        intent_id=intent.intent_id,
                        subject=subject,
                        evidence_status=evidence_status,
                        warning=point_warning,
                        point_collection=point_collection,
                    )
                )
                handoffs.append(
                    _handoff(
                        run_id=run_id,
                        sender=AgentRole.SUBJECT,
                        receiver=AgentRole.EVIDENCE_COLLECTOR,
                        task_type="collect_subject_evidence",
                        goal=(
                            f"Collect normalized scene evidence for subject {subject.subject_id}."
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
        updated_intent_by_id = {item.intent_id: item for item in requirements.subject_intents}
        groups = tuple(
            group.model_copy(
                update={"intent": updated_intent_by_id.get(group.intent.intent_id, group.intent)}
            )
            for group in state.subject_groups
        )
        places: tuple[VisitPlace, ...] = ()
        areas: tuple[AreaCluster, ...] = ()
        quarantined: tuple[EvidenceQuarantine, ...] = ()
        ambiguous: tuple[AmbiguousPlaceMerge, ...] = ()
        bases: tuple[BaseCandidate, ...] = ()
        if evidence and curate:
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
                    input_refs=tuple(_ref("scene_evidence", item.evidence_id) for item in evidence),
                    output_schema="PlaceResolutionResult + AreaCluster[]",
                    result_refs=(
                        *(_ref("visit_place", item.place_id) for item in places),
                        *(_ref("area", item.area_id) for item in areas),
                    ),
                )
            )
        partial = any(item.evidence_status != "ok" for item in confirmed)
        status = (
            WorkspaceStatus.PARTIAL_READY
            if places and partial
            else WorkspaceStatus.READY
            if places
            else WorkspaceStatus.PARTIAL
        )
        selected_base_id = (
            state.selected_base_id
            if state.selected_base_id in {item.base_id for item in bases}
            else bases[0].base_id
            if bases
            else None
        )
        prepared = state.model_copy(
            update={
                "state_version": state.state_version + 1,
                "status": status,
                "requirements": requirements,
                "subject_groups": groups,
                "confirmed_subjects": tuple(confirmed),
                "evidence": tuple(evidence),
                "quarantined": quarantined,
                "ambiguous_merges": ambiguous,
                "places": places,
                "areas": areas,
                "base_candidates": bases,
                "selected_base_id": selected_base_id,
                "candidate_graph": None,
                "itineraries": (),
                "handoffs": tuple(handoffs),
                "warnings": tuple(warnings),
            }
        )
        if curate and state.itineraries and places and areas and selected_base_id:
            return self._execute_plan(
                prepared.model_copy(update={"itineraries": state.itineraries}),
                base_id=selected_base_id,
                access=state.selected_access,
                timezone=state.itineraries[0].timezone,
                strategies=state.planning_strategies,
                next_version=state.state_version + 1,
            )
        return prepared

    async def confirm_subjects(
        self, state: WorkspaceState, request: ConfirmWorkspaceSubjectsRequest
    ) -> WorkspaceState:
        """Compatibility entry point for callers not yet using the workspace graph."""

        return await self._confirm_subjects(state, request, curate=True)

    async def collect_subject_evidence(
        self, state: WorkspaceState, request: ConfirmWorkspaceSubjectsRequest
    ) -> WorkspaceState:
        """Verify confirmed subjects and fetch evidence without doing place curation."""

        return await self._confirm_subjects(state, request, curate=False)

    def curate_places(self, state: WorkspaceState) -> WorkspaceState:
        """Resolve evidence identity while preserving ambiguous records for review."""

        if not state.evidence:
            return state
        run_id = uuid4()
        resolution = resolve_places(state.evidence)
        now = datetime.now(UTC)
        handoff = AgentHandoff(
            run_id=run_id,
            sender=AgentRole.EVIDENCE_COLLECTOR,
            receiver=AgentRole.PLACE_CURATOR,
            task_type="resolve_canonical_places",
            goal="Resolve scene evidence into canonical visit places.",
            input_refs=tuple(_ref("scene_evidence", item.evidence_id) for item in state.evidence),
            expected_output_schema="PlaceResolutionResult",
            status="completed",
            result_refs=tuple(_ref("visit_place", item.place_id) for item in resolution.places),
            created_at=now,
            started_at=now,
            completed_at=max(now, datetime.now(UTC)),
        )
        context = self.context_builder.build(
            role=AgentRole.PLACE_CURATOR,
            run_id=run_id,
            facts=(
                ContextFact(key="scene_evidence_count", value=len(state.evidence)),
                ContextFact(key="resolved_place_count", value=len(resolution.places)),
                ContextFact(key="quarantined_count", value=len(resolution.quarantined)),
                ContextFact(
                    key="ambiguous_merge_count",
                    value=len(resolution.ambiguous_merges),
                ),
            ),
            refs=(
                *(_ref("scene_evidence", item.evidence_id) for item in state.evidence),
                *(_ref("visit_place", item.place_id) for item in resolution.places),
            ),
        )
        return state.model_copy(
            update={
                "places": resolution.places,
                "quarantined": resolution.quarantined,
                "ambiguous_merges": resolution.ambiguous_merges,
                "handoffs": (*state.handoffs, handoff),
                "contexts": (*state.contexts, context),
            }
        )

    def build_travel_areas(self, state: WorkspaceState) -> WorkspaceState:
        """Build travel areas separately from canonical-place identity resolution."""

        if not state.places:
            return state.model_copy(
                update={
                    "state_version": state.state_version + 1,
                    "status": WorkspaceStatus.PARTIAL,
                }
            )
        run_id = uuid4()
        areas = cluster_places(state.places)
        bases = (_estimated_base(state.places),)
        partial = any(item.evidence_status != "ok" for item in state.confirmed_subjects)
        status = WorkspaceStatus.PARTIAL_READY if partial else WorkspaceStatus.READY
        selected_base_id = (
            state.selected_base_id
            if state.selected_base_id in {item.base_id for item in bases}
            else bases[0].base_id
        )
        now = datetime.now(UTC)
        handoff = AgentHandoff(
            run_id=run_id,
            sender=AgentRole.PLACE_CURATOR,
            receiver=AgentRole.TRAVEL_AREA_BUILDER,
            task_type="build_travel_areas",
            goal="Build stable travel areas independently from map marker clusters.",
            input_refs=tuple(_ref("visit_place", item.place_id) for item in state.places),
            expected_output_schema="AreaCluster[]",
            status="completed",
            result_refs=tuple(_ref("area", item.area_id) for item in areas),
            created_at=now,
            started_at=now,
            completed_at=max(now, datetime.now(UTC)),
        )
        return state.model_copy(
            update={
                "state_version": state.state_version + 1,
                "status": status,
                "areas": areas,
                "base_candidates": bases,
                "selected_base_id": selected_base_id,
                "candidate_graph": None,
                "itineraries": (),
                "handoffs": (*state.handoffs, handoff),
            }
        )

    async def calibrate_travel_areas(self, state: WorkspaceState) -> WorkspaceState:
        """Correct coarse spatial areas with bounded real walking matrices."""

        if not state.areas:
            return state
        by_id = {item.place_id: item for item in state.places}
        eligible = sorted(
            (area for area in state.areas if len(area.place_ids) >= 2),
            key=lambda item: (-len(item.place_ids), str(item.area_id)),
        )
        durations: dict[tuple[UUID, UUID], float] = {}
        walking_edges: list[PlaceWalkingEdge] = []
        warnings = list(state.warnings)
        snapshots = list(state.provider_snapshots)
        queried = 0
        for area in eligible:
            if queried >= 12:
                break
            if len(area.place_ids) > 50:
                warnings.append(
                    f"Walking calibration skipped an area with {len(area.place_ids)} "
                    "places because one bounded matrix supports at most 50."
                )
                continue
            place_ids = tuple(sorted(area.place_ids, key=str))
            query = MatrixQuery(
                coordinates=tuple(by_id[item].coordinate for item in place_ids)
            )
            outcome = await invoke_tool(
                self.tools,
                "get_route_matrix",
                query.model_dump(mode="json"),
                RouteMatrix,
            )
            queried += 1
            refs: tuple[EntityRef, ...] = ()
            warning = outcome.safe_warning
            if outcome.value is not None:
                for row, first in enumerate(place_ids):
                    for column, second in enumerate(place_ids):
                        duration = outcome.value.durations_seconds[row][column]
                        distance = outcome.value.distances_meters[row][column]
                        if duration is not None:
                            durations[(first, second)] = duration
                        if (
                            first != second
                            and duration is not None
                            and distance is not None
                        ):
                            walking_edges.append(
                                PlaceWalkingEdge(
                                    source_place_id=first,
                                    target_place_id=second,
                                    duration_seconds=duration,
                                    distance_meters=distance,
                                    provenance=outcome.value.provenance,
                                )
                            )
                refs = (_ref("area", area.area_id),)
            elif warning:
                warnings.append(warning)
            snapshots.append(
                ProviderSnapshot(
                    kind="walking_matrix",
                    query_fingerprint=request_fingerprint(
                        "openrouteservice-matrix", query
                    ),
                    status="ok" if outcome.value is not None else "unavailable",
                    provenance=outcome.provenance,
                    result_refs=refs,
                    warning=warning,
                )
            )
        if len(eligible) > queried:
            warnings.append(
                f"Walking matrices calibrated {queried} of {len(eligible)} multi-place "
                "areas in this bounded run; remaining areas retain fallback status."
            )
        calibrated = cluster_places(
            state.places,
            walking_durations_seconds=durations or None,
        )
        area_pairs = sorted(
            (
                (
                    haversine_meters(
                        source_area.representative_coordinate,
                        target_area.representative_coordinate,
                    ),
                    source_area,
                    target_area,
                )
                for source_area, target_area in combinations(calibrated, 2)
                if haversine_meters(
                    source_area.representative_coordinate,
                    target_area.representative_coordinate,
                )
                <= 20_000
            ),
            key=lambda item: (item[0], str(item[1].area_id), str(item[2].area_id)),
        )
        area_edges: list[AreaTransitEdge] = []
        if state.requirements.start_date is not None:
            for _distance, source_area, target_area in area_pairs[:4]:
                timezone_name = _derived_timezone(source_area.representative_coordinate)
                transit_query = TransitRouteQuery(
                    origin=(
                        f"{source_area.representative_coordinate.latitude},"
                        f"{source_area.representative_coordinate.longitude}"
                    ),
                    destination=(
                        f"{target_area.representative_coordinate.latitude},"
                        f"{target_area.representative_coordinate.longitude}"
                    ),
                    time_mode="depart_at",
                    at=datetime.combine(
                        state.requirements.start_date,
                        time(10),
                        ZoneInfo(timezone_name),
                    ),
                    route=state.requirements.transit_route_preference,
                    prefer=state.requirements.transit_vehicle_preferences,
                )
                transit_outcome = await invoke_tool(
                    self.tools,
                    "search_transit_options",
                    transit_query.model_dump(mode="json"),
                    TransitRouteResult,
                )
                refs = ()
                warning = transit_outcome.safe_warning
                if transit_outcome.value is not None and transit_outcome.value.options:
                    option = transit_outcome.value.options[0]
                    area_edges.append(
                        AreaTransitEdge(
                            source_area_id=source_area.area_id,
                            target_area_id=target_area.area_id,
                            duration_seconds=option.duration_seconds,
                            walking_seconds=option.walking_seconds,
                            transfers=option.transfers,
                            option_id=option.option_id,
                            provenance=option.provenance,
                        )
                    )
                    refs = (
                        _ref("area", source_area.area_id),
                        _ref("area", target_area.area_id),
                        _ref("transit_option", option.option_id),
                    )
                    warnings.extend(transit_outcome.value.warnings)
                elif warning:
                    warnings.append(warning)
                snapshots.append(
                    ProviderSnapshot(
                        kind="area_transit",
                        query_fingerprint=request_fingerprint(
                            "searchapi-area-transit", transit_query
                        ),
                        status=(
                            "ok"
                            if transit_outcome.value is not None
                            and transit_outcome.value.options
                            else "unavailable"
                        ),
                        provenance=transit_outcome.provenance,
                        result_refs=refs,
                        warning=warning,
                    )
                )
                if transit_outcome.value is None:
                    break
        if len(area_pairs) > 4:
            warnings.append(
                f"Transit calibration checked 4 of {len(area_pairs)} nearby area pairs; "
                "the remaining edges stay unverified until planning needs them."
            )
        bases = state.base_candidates
        selected_base_id = state.selected_base_id
        if state.requirements.base_preference:
            base_query = PlaceSearchQuery(
                text=" ".join(
                    item
                    for item in (
                        state.requirements.base_preference,
                        state.requirements.destination,
                    )
                    if item
                ),
                limit=3,
            )
            base_outcome = await invoke_tool(
                self.tools,
                "geocode_place",
                base_query.model_dump(mode="json"),
                PlaceSearchResult,
            )
            if base_outcome.value is not None and base_outcome.value.candidates:
                candidate = base_outcome.value.candidates[0]
                preferred = BaseCandidate(
                    base_id=(
                        "preferred-"
                        + request_fingerprint("geocode-base", base_query)[:16]
                    ),
                    name=candidate.label,
                    coordinate=candidate.coordinate,
                    provenance=candidate.provenance,
                )
                bases = (preferred, *state.base_candidates)
                selected_base_id = preferred.base_id
            elif base_outcome.safe_warning:
                warnings.append(base_outcome.safe_warning)
        return state.model_copy(
            update={
                "areas": calibrated,
                "base_candidates": bases,
                "selected_base_id": selected_base_id,
                "area_transit_edges": tuple(area_edges),
                "walking_edges": tuple(walking_edges),
                "provider_snapshots": tuple(snapshots),
                "warnings": tuple(dict.fromkeys(warnings)),
            }
        )

    async def collect_access_candidates(self, state: WorkspaceState) -> WorkspaceState:
        """Collect bounded read-only access snapshots before user confirmation."""

        requirements = state.requirements
        warnings = list(state.warnings)
        snapshots = list(state.provider_snapshots)
        flight_options: tuple[FlightOption, ...] = ()
        transit_options: list[TransitOption] = []
        candidates: list[AccessOption] = []
        if (
            requirements.origin_iata
            and requirements.destination_iata
            and requirements.start_date
        ):
            flight_query = FlightSearchQuery(
                departure_id=requirements.origin_iata,
                arrival_id=requirements.destination_iata,
                outbound_date=requirements.start_date,
                return_date=requirements.end_date,
                adults=requirements.adults,
                cabin_class=requirements.cabin_class,
                currency=requirements.currency,
            )
            flight_outcome = await invoke_tool(
                self.tools,
                "search_flight_options",
                flight_query.model_dump(mode="json"),
                FlightSearchResult,
            )
            warning = flight_outcome.safe_warning
            refs: tuple[EntityRef, ...] = ()
            if flight_outcome.value is not None:
                flight_options = flight_outcome.value.options
                refs = tuple(_ref("flight_option", item.option_id) for item in flight_options)
                candidates.extend(
                    AccessOption(
                        option_id=f"flight-{item.option_id}",
                        mode=AccessMode.FLIGHT,
                        origin=item.segments[0].departure_airport,
                        destination=item.segments[-1].arrival_airport,
                        departure_at=item.segments[0].departure_at,
                        arrival_at=item.segments[-1].arrival_at,
                        price=item.price,
                        currency=item.currency,
                        confirmation_url=None,
                        comparison_labels=("recommended",) if index == 0 else (),
                        provenance=item.provenance,
                    )
                    for index, item in enumerate(flight_options)
                )
            elif warning:
                warnings.append(warning)
            snapshots.append(
                ProviderSnapshot(
                    kind="flight",
                    query_fingerprint=request_fingerprint("searchapi-flights", flight_query),
                    status="ok" if flight_outcome.value is not None else "unavailable",
                    provenance=flight_outcome.provenance,
                    result_refs=refs,
                    warning=warning,
                )
            )
        if (
            requirements.origin
            and requirements.destination
            and requirements.start_date
            and state.base_candidates
        ):
            timezone_name = _derived_timezone(state.base_candidates[0].coordinate)
            transit_queries = [
                (
                    "in",
                    TransitRouteQuery(
                        origin=requirements.origin,
                        destination=requirements.destination,
                        time_mode="depart_at",
                        at=datetime.combine(
                            requirements.start_date, time(9), ZoneInfo(timezone_name)
                        ),
                        route=requirements.transit_route_preference,
                        prefer=requirements.transit_vehicle_preferences,
                    ),
                )
            ]
            if requirements.end_date is not None:
                transit_queries.append(
                    (
                        "out",
                        TransitRouteQuery(
                            origin=requirements.destination,
                            destination=requirements.origin,
                            time_mode="depart_at",
                            at=datetime.combine(
                                requirements.end_date, time(17), ZoneInfo(timezone_name)
                            ),
                            route=requirements.transit_route_preference,
                            prefer=requirements.transit_vehicle_preferences,
                        ),
                    )
                )
            warnings.append(
                "Access searches used disclosed 09:00 inbound and 17:00 outbound planning "
                "assumptions; select an option only after checking the times."
            )
            for direction, transit_query in transit_queries:
                transit_outcome = await invoke_tool(
                    self.tools,
                    "search_transit_options",
                    transit_query.model_dump(mode="json"),
                    TransitRouteResult,
                )
                warning = transit_outcome.safe_warning
                refs = ()
                if transit_outcome.value is not None:
                    transit_options.extend(transit_outcome.value.options)
                    refs = tuple(
                        _ref("transit_option", f"{direction}:{item.option_id}")
                        for item in transit_outcome.value.options
                    )
                    candidates.extend(
                        AccessOption(
                            option_id=f"transit-{direction}-{item.option_id}",
                            mode=AccessMode.TRAIN,
                            origin=item.origin,
                            destination=item.destination,
                            departure_at=item.departure_at,
                            arrival_at=item.arrival_at,
                            comparison_labels=(
                                ("fewest_transfers",)
                                if item.transfers == 0
                                else ()
                            ),
                            provenance=item.provenance,
                        )
                        for item in transit_outcome.value.options
                    )
                    warnings.extend(transit_outcome.value.warnings)
                elif warning:
                    warnings.append(warning)
                snapshots.append(
                    ProviderSnapshot(
                        kind="transit",
                        query_fingerprint=request_fingerprint(
                            "searchapi-transit", transit_query
                        ),
                        status="ok" if transit_outcome.value is not None else "unavailable",
                        provenance=transit_outcome.provenance,
                        result_refs=refs,
                        warning=warning,
                    )
                )
        return state.model_copy(
            update={
                "access_candidates": tuple(candidates),
                "flight_options": flight_options,
                "transit_options": tuple(transit_options),
                "provider_snapshots": tuple(snapshots),
                "warnings": tuple(dict.fromkeys(warnings)),
            }
        )

    async def collect_place_facts(self, state: WorkspaceState) -> WorkspaceState:
        """Match bounded canonical places, then fetch details only for confident IDs."""

        ordered = sorted(
            state.places,
            key=lambda item: (
                item.place_id not in state.must_visit_place_ids,
                str(item.place_id),
            ),
        )
        warnings = list(state.warnings)
        facts = dict(state.place_facts)
        snapshots = list(state.provider_snapshots)
        for place in ordered[:12]:
            query = PlaceFactsSearchQuery(
                query=place.canonical_name,
                coordinate_hint=place.coordinate,
                limit=3,
            )
            search_outcome = await invoke_tool(
                self.tools,
                "search_place_facts",
                query.model_dump(mode="json"),
                PlaceFactsResult,
            )
            selected: PlaceFact | None = None
            if search_outcome.value is not None:
                selected = next(
                    (
                        item
                        for item in search_outcome.value.candidates
                        if item.match_confidence >= 0.85
                        and item.coordinate is not None
                        and haversine_meters(place.coordinate, item.coordinate) <= 1_500
                    ),
                    None,
                )
                warnings.extend(search_outcome.value.warnings)
            if selected is None:
                search_warning = search_outcome.safe_warning or (
                    f"Current place facts for {place.canonical_name} were not matched "
                    "confidently; no opening constraint was assumed."
                )
                warnings.append(search_warning)
                snapshots.append(
                    ProviderSnapshot(
                        kind="place",
                        query_fingerprint=request_fingerprint(
                            "searchapi-place-search", query
                        ),
                        status="unavailable",
                        provenance=search_outcome.provenance,
                        warning=search_warning,
                    )
                )
                continue
            detail_query = PlaceDetailsQuery(
                place_id=selected.place_id,
                data_id=None if selected.place_id else selected.data_id,
            )
            detail_outcome = await invoke_tool(
                self.tools,
                "get_place_facts",
                detail_query.model_dump(mode="json"),
                PlaceFactsResult,
            )
            fact = (
                detail_outcome.value.candidates[0]
                if detail_outcome.value is not None and detail_outcome.value.candidates
                else selected
            )
            facts[place.place_id] = fact
            detail_warning = detail_outcome.safe_warning
            if detail_warning:
                warnings.append(detail_warning)
            snapshots.append(
                ProviderSnapshot(
                    kind="place",
                    query_fingerprint=request_fingerprint(
                        "searchapi-place-detail", detail_query
                    ),
                    status="ok" if detail_outcome.value is not None else "partial",
                    provenance=detail_outcome.provenance or search_outcome.provenance,
                    result_refs=(_ref("place_fact", place.place_id),),
                    warning=detail_warning,
                )
            )
        if len(ordered) > 12:
            warnings.append(
                f"Current place facts were checked for 12 of {len(ordered)} places; "
                "remaining places require later refresh."
            )
        return state.model_copy(
            update={
                "place_facts": facts,
                "provider_snapshots": tuple(snapshots),
                "warnings": tuple(dict.fromkeys(warnings)),
            }
        )

    async def collect_weather(
        self, state: WorkspaceState, request: PlanWorkspaceRequest
    ) -> WorkspaceState:
        """Fetch a base forecast or preserve an explicit unknown live constraint."""

        start = state.requirements.start_date
        end = state.requirements.end_date
        by_base = {item.base_id: item for item in state.base_candidates}
        if start is None or end is None or request.base_id not in by_base:
            return state
        warnings = list(state.warnings)
        snapshots = list(state.provider_snapshots)
        if (end - start).days > 15:
            warnings.append(
                "The trip exceeds the live forecast window; weather remains unknown until "
                "a bounded refresh is possible."
            )
            return state.model_copy(update={"warnings": tuple(dict.fromkeys(warnings))})
        query = WeatherForecastQuery(
            coordinate=by_base[request.base_id].coordinate,
            start_date=start,
            end_date=end,
        )
        outcome = await invoke_tool(
            self.tools,
            "get_weather_forecast",
            query.model_dump(mode="json"),
            WeatherForecastResult,
        )
        forecast = outcome.value
        warning = outcome.safe_warning
        status: Literal["ok", "partial", "unavailable"] = "unavailable"
        refs: tuple[EntityRef, ...] = ()
        if forecast is not None:
            status = "ok" if forecast.available else "partial"
            refs = tuple(_ref("weather_window", item.date) for item in forecast.windows)
            if not forecast.available and forecast.reason:
                warning = forecast.reason
        if warning:
            warnings.append(warning)
        snapshots.append(
            ProviderSnapshot(
                kind="weather",
                query_fingerprint=request_fingerprint("open-meteo", query),
                status=status,
                provenance=outcome.provenance,
                result_refs=refs,
                warning=warning,
            )
        )
        return state.model_copy(
            update={
                "weather_forecast": forecast,
                "provider_snapshots": tuple(snapshots),
                "warnings": tuple(dict.fromkeys(warnings)),
            }
        )

    async def collect_knowledge_constraints(self, state: WorkspaceState) -> WorkspaceState:
        """Retrieve scoped evidence and produce reviewable rules, never active constraints."""

        evidence_by_id = {item.evidence_id: item for item in state.knowledge_evidence}
        evidence_documents = dict(state.knowledge_evidence_documents)
        rules = list(state.knowledge_rules)
        existing_rule_keys = {
            (
                item.rule_type,
                tuple((ref.entity_type, ref.entity_id) for ref in item.target_refs),
                item.evidence_ids,
            )
            for item in rules
        }
        warnings = list(state.warnings)
        question = "访问规则、拍摄礼仪、无障碍、安全和长期稳定的换乘注意事项"
        confirmed_subjects = state.confirmed_subjects[:12]

        async def retrieve_subject(
            confirmed: ConfirmedWorkspaceSubject,
        ) -> tuple[ConfirmedWorkspaceSubject, KnowledgeSearchResult | None]:
            try:
                retrieval = await self.knowledge_retriever.retrieve(
                    owner_user_id=state.owner_user_id,
                    trip_id=state.trip_id,
                    request=state.requirements,
                    subject=confirmed.subject,
                )
            except Exception:
                return confirmed, None
            return confirmed, retrieval

        retrieved = await asyncio.gather(
            *(retrieve_subject(confirmed) for confirmed in confirmed_subjects)
        )
        current_evidence: list[RetrievedEvidence] = []
        current_evidence_ids: set[str] = set()
        current_conflicts: list[EvidenceConflict] = []
        allowed_refs: list[EntityRef] = []
        for confirmed, retrieval in retrieved:
            if retrieval is None:
                warnings.append("相关访问资料暂时无法检索; 没有据此添加行程约束。")
                continue
            for evidence in retrieval.evidence:
                evidence_by_id[evidence.evidence_id] = evidence
                evidence_documents[evidence.evidence_id] = evidence.document_id
                if (
                    evidence.evidence_id not in current_evidence_ids
                    and len(current_evidence) < 6
                ):
                    current_evidence.append(evidence)
                    current_evidence_ids.add(evidence.evidence_id)
            current_conflicts.extend(retrieval.conflicts)
            if len(allowed_refs) < 20:
                allowed_refs.append(
                    EntityRef(
                        entity_type="subject",
                        entity_id=confirmed.subject.subject_id,
                    )
                )
            subject_places = tuple(
                place
                for place in state.places
                if any(
                    item.subject_id == confirmed.subject.subject_id
                    for item in place.subject_appearances
                )
            )
            allowed_refs.extend(
                EntityRef(entity_type="place", entity_id=str(place.place_id))
                for place in subject_places[: max(0, 20 - len(allowed_refs))]
            )

        if current_evidence and allowed_refs:
            retained_ids = {item.evidence_id for item in current_evidence}
            retrieval = KnowledgeSearchResult(
                status="sufficient_evidence",
                evidence=tuple(current_evidence),
                conflicts=tuple(
                    conflict
                    for conflict in current_conflicts
                    if set(conflict.evidence_ids).issubset(retained_ids)
                ),
            )
            allowed_refs_tuple = tuple(
                dict.fromkeys((item.entity_type, item.entity_id) for item in allowed_refs)
            )
            normalized_refs = tuple(
                EntityRef(entity_type=entity_type, entity_id=entity_id)
                for entity_type, entity_id in allowed_refs_tuple[:20]
            )
            allowed_keys = {
                (item.entity_type, item.entity_id) for item in normalized_refs
            }
            try:
                proposed = await self.knowledge_rule_proposer.propose(
                    KnowledgeRuleProposalInput(
                        question=question,
                        evidence=retrieval.evidence,
                        allowed_target_refs=normalized_refs,
                        travel_start=state.requirements.start_date,
                        travel_end=state.requirements.end_date,
                    )
                )
            except Exception:
                warnings.append("资料已检索, 但规则提取暂时不可用; 资料不会自动变成约束。")
            else:
                for proposal in proposed.proposals:
                    if any(
                        (ref.entity_type, ref.entity_id) not in allowed_keys
                        for ref in proposal.target_refs
                    ):
                        warnings.append("有一条资料规则指向工作区外实体, 已安全忽略。")
                        continue
                    try:
                        rule = validate_derived_rule(
                            trip_id=state.trip_id,
                            proposal=proposal,
                            retrieval=retrieval,
                        )
                    except ValueError:
                        warnings.append("有一条资料规则缺少当前检索证据, 已安全忽略。")
                        continue
                    key = (
                        rule.rule_type,
                        tuple((ref.entity_type, ref.entity_id) for ref in rule.target_refs),
                        rule.evidence_ids,
                    )
                    if key not in existing_rule_keys:
                        rules.append(rule)
                        existing_rule_keys.add(key)
        return state.model_copy(
            update={
                "knowledge_evidence": tuple(evidence_by_id.values()),
                "knowledge_evidence_documents": evidence_documents,
                "knowledge_rules": tuple(rules),
                "warnings": tuple(dict.fromkeys(warnings)),
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
                walking_edges=state.walking_edges,
                area_transit_edges=state.area_transit_edges,
                place_facts=state.place_facts,
                weather_forecast=state.weather_forecast,
            )
        )
        parent_by_strategy = {
            strategy: max(item.version for item in state.itineraries if item.strategy == strategy)
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
        planner_context = self.context_builder.build(
            role=AgentRole.ITINERARY_PLANNER,
            run_id=run_id,
            facts=(
                ContextFact(key="start_date", value=str(state.requirements.start_date)),
                ContextFact(key="end_date", value=str(state.requirements.end_date)),
                ContextFact(
                    key="walking_preference",
                    value=state.requirements.walking_preference,
                ),
                ContextFact(key="place_count", value=len(state.places)),
                ContextFact(key="area_count", value=len(state.areas)),
                ContextFact(key="walking_edge_count", value=len(state.walking_edges)),
                ContextFact(
                    key="area_transit_edge_count",
                    value=len(state.area_transit_edges),
                ),
                ContextFact(key="place_fact_count", value=len(state.place_facts)),
                ContextFact(
                    key="active_knowledge_rule_count",
                    value=sum(
                        item.status == "active_constraint"
                        for item in state.knowledge_rules
                    ),
                ),
            ),
            refs=(
                *(_ref("visit_place", item.place_id) for item in state.places),
                *(_ref("area", item.area_id) for item in state.areas),
                _ref("base", base.base_id),
                *(
                    _ref("knowledge_rule", item.rule_id)
                    for item in state.knowledge_rules
                    if item.status == "active_constraint"
                ),
            ),
        )
        validator_contexts = tuple(
            self.context_builder.build(
                role=AgentRole.VALIDATOR,
                run_id=run_id,
                facts=(
                    ContextFact(key="strategy", value=item.strategy.value),
                    ContextFact(
                        key="hard_violation_codes",
                        value=",".join(issue.code for issue in item.validation_issues)
                        or "none",
                    ),
                    ContextFact(
                        key="scheduled_count",
                        value=sum(len(day.visits) for day in item.days),
                    ),
                ),
                refs=(_ref("itinerary", item.itinerary_id, item.version),),
            )
            for item in new_itineraries
        )
        reviewer_contexts = tuple(
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
                    _ref("itinerary", item.itinerary_id, item.version) for item in new_itineraries
                ),
            ),
            _handoff(
                run_id=run_id,
                sender=AgentRole.ITINERARY_PLANNER,
                receiver=AgentRole.VALIDATOR,
                task_type="validate_strategy_versions",
                goal="Validate membership, coverage, walking, time and omissions.",
                input_refs=tuple(
                    _ref("itinerary", item.itinerary_id, item.version) for item in new_itineraries
                ),
                output_schema="ValidationIssue[]",
                result_refs=tuple(
                    _ref("itinerary", item.itinerary_id, item.version) for item in new_itineraries
                ),
                warning=(
                    "One or more strategy versions retain deterministic violations."
                    if any(item.validation_issues for item in new_itineraries)
                    else None
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
                "contexts": (
                    *state.contexts,
                    planner_context,
                    *validator_contexts,
                    *reviewer_contexts,
                ),
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

    def replan_target_day(self, state: WorkspaceState, target_day: int) -> WorkspaceState:
        """Run a deterministic repair while freezing every non-target day."""

        if not state.itineraries or state.selected_base_id is None:
            raise ValueError("workspace has no active itinerary to replan")
        active = state.itineraries[: len(state.planning_strategies)]
        anchor = active[0]
        if target_day > len(anchor.days):
            raise ValueError("replanner target day is outside the itinerary")
        fixed_days: dict[UUID, int] = {}
        fixed_positions: dict[UUID, int] = {}
        for day_number, day in enumerate(anchor.days, start=1):
            for position, visit in enumerate(day.visits):
                fixed_days[visit.place_id] = day_number
                fixed_positions[visit.place_id] = (
                    len(day.visits) - position - 1 if day_number == target_day else position
                )
        prepared = state.model_copy(
            update={
                "fixed_day_assignments": fixed_days,
                "fixed_positions": fixed_positions,
            }
        )
        replanned = self._execute_plan(
            prepared,
            base_id=state.selected_base_id,
            access=state.selected_access,
            timezone=anchor.timezone,
            strategies=state.planning_strategies,
            next_version=state.state_version + 1,
        )
        prior_by_strategy = {item.strategy: item for item in active}
        generated = replanned.itineraries[: len(state.planning_strategies)]
        bounded: list[ItineraryVersion] = []
        for itinerary in generated:
            prior = prior_by_strategy[itinerary.strategy]
            prior_by_date = {item.date: item for item in prior.days}
            days = tuple(
                day if number == target_day else prior_by_date.get(day.date, day)
                for number, day in enumerate(itinerary.days, start=1)
            )
            bounded.append(
                itinerary.model_copy(
                    update={
                        "parent_version": prior.version,
                        "days": days,
                        "total_walking_meters": sum(item.walking_distance_meters for item in days),
                        "total_duration_minutes": sum(item.duration_minutes for item in days),
                        "warnings": (
                            *itinerary.warnings,
                            f"Only day {target_day} was eligible for replanning.",
                        ),
                    }
                )
            )
        diff = PlanVersionDiff(
            from_version=state.state_version,
            to_version=replanned.state_version,
            changed_day_numbers=(target_day,),
            validation_before=tuple(
                issue.code for item in active for issue in item.validation_issues
            ),
            validation_after=tuple(
                issue.code for item in bounded for issue in item.validation_issues
            ),
        )
        return replanned.model_copy(
            update={
                "itineraries": (*bounded, *state.itineraries),
                "diffs": (*state.diffs, diff),
            }
        )

    @staticmethod
    def _validate_mutation(state: WorkspaceState, request: WorkspaceMutationRequest) -> None:
        if (request.owner_user_id, request.thread_id) != (
            state.owner_user_id,
            state.thread_id,
        ):
            raise ValueError("workspace namespace mismatch")
        if request.expected_state_version != state.state_version:
            raise ValueError("workspace state version conflict")

    def clear_schedule(
        self, state: WorkspaceState, request: WorkspaceMutationRequest
    ) -> WorkspaceState:
        """Clear the visible schedule while retaining candidates and audit history."""

        self._validate_mutation(state, request)
        archived_by_id = {
            item.itinerary_id: item for item in (*state.archived_itineraries, *state.itineraries)
        }
        return state.model_copy(
            update={
                "state_version": state.state_version + 1,
                "status": WorkspaceStatus.READY_TO_PLAN,
                "itineraries": (),
                "archived_itineraries": tuple(archived_by_id.values()),
                "diffs": (
                    *state.diffs,
                    PlanVersionDiff(
                        from_version=state.state_version,
                        to_version=state.state_version + 1,
                        changed_day_numbers=tuple(range(1, len(state.itineraries[0].days) + 1))
                        if state.itineraries
                        else (),
                    ),
                ),
            }
        )

    def archive_workspace(
        self, state: WorkspaceState, request: WorkspaceMutationRequest
    ) -> WorkspaceState:
        """Archive without deleting any trip-owned history or checkpoint."""

        self._validate_mutation(state, request)
        return state.model_copy(
            update={
                "state_version": state.state_version + 1,
                "status": WorkspaceStatus.ARCHIVED,
            }
        )

    def clear_day(self, state: WorkspaceState, request: ClearWorkspaceDayRequest) -> WorkspaceState:
        """Create auditable versions with one explicit empty day and no refill."""

        self._validate_mutation(state, request)
        if not state.itineraries:
            raise ValueError("workspace has no active itinerary")
        active_count = min(len(state.planning_strategies), len(state.itineraries))
        active = state.itineraries[:active_count]
        if any(request.day_number > len(item.days) for item in active):
            raise ValueError("day number is outside the active itinerary")
        version = state.state_version + 1
        cleared: list[ItineraryVersion] = []
        for itinerary in active:
            original_day = itinerary.days[request.day_number - 1]
            removed_ids = {item.place_id for item in original_day.visits}
            days = tuple(
                ItineraryDay(
                    date=day.date,
                    area_ids=(),
                    visits=(),
                    walking_distance_meters=0,
                    duration_minutes=0,
                )
                if number == request.day_number
                else day
                for number, day in enumerate(itinerary.days, start=1)
            )
            coverage = tuple(
                item.model_copy(
                    update={
                        "scheduled_place_ids": tuple(
                            place_id
                            for place_id in item.scheduled_place_ids
                            if place_id not in removed_ids
                        ),
                        "minimum_satisfied": (
                            item.minimum_place_count is None
                            or len(
                                tuple(
                                    place_id
                                    for place_id in item.scheduled_place_ids
                                    if place_id not in removed_ids
                                )
                            )
                            >= item.minimum_place_count
                        ),
                    }
                )
                for item in itinerary.subject_coverage
            )
            omitted_by_id = {item.place_id: item for item in itinerary.omissions}
            for visit in original_day.visits:
                omitted_by_id[visit.place_id] = StructuredOmission(
                    place_id=visit.place_id,
                    reason_code="user_removed",
                    detail=f"User cleared day {request.day_number}; no automatic refill ran.",
                )
            cleared.append(
                itinerary.model_copy(
                    update={
                        "itinerary_id": uuid4(),
                        "version": version,
                        "parent_version": itinerary.version,
                        "days": days,
                        "subject_coverage": coverage,
                        "total_walking_meters": sum(item.walking_distance_meters for item in days),
                        "total_duration_minutes": sum(item.duration_minutes for item in days),
                        "omissions": tuple(omitted_by_id.values()),
                        "warnings": (
                            *itinerary.warnings,
                            f"Day {request.day_number} was explicitly cleared.",
                        ),
                        "created_at": datetime.now(UTC),
                    }
                )
            )
        return state.model_copy(
            update={
                "state_version": version,
                "status": WorkspaceStatus.PARTIAL,
                "itineraries": (*cleared, *state.itineraries),
                "diffs": (
                    *state.diffs,
                    PlanVersionDiff(
                        from_version=state.state_version,
                        to_version=version,
                        changed_day_numbers=(request.day_number,),
                    ),
                ),
            }
        )

    def restore_itinerary(
        self,
        state: WorkspaceState,
        request: WorkspaceMutationRequest,
        itinerary_id: UUID,
    ) -> WorkspaceState:
        """Restore a historical version by creating a new immutable child version."""

        self._validate_mutation(state, request)
        source = next(
            (
                item
                for item in (*state.itineraries, *state.archived_itineraries)
                if item.itinerary_id == itinerary_id
            ),
            None,
        )
        if source is None:
            raise ValueError("itinerary version does not belong to this workspace")
        version = state.state_version + 1
        restored = source.model_copy(
            update={
                "itinerary_id": uuid4(),
                "version": version,
                "parent_version": source.version,
                "created_at": datetime.now(UTC),
                "warnings": (*source.warnings, "Restored from an immutable prior version."),
            }
        )
        return state.model_copy(
            update={
                "state_version": version,
                "status": (
                    WorkspaceStatus.PARTIAL
                    if restored.validation_issues
                    else WorkspaceStatus.PLANNED
                ),
                "itineraries": (restored, *state.itineraries),
                "diffs": (
                    *state.diffs,
                    PlanVersionDiff(
                        from_version=state.state_version,
                        to_version=version,
                        changed_day_numbers=tuple(range(1, len(restored.days) + 1)),
                    ),
                ),
            }
        )

    def delete_itinerary_version(
        self,
        state: WorkspaceState,
        request: WorkspaceMutationRequest,
        itinerary_id: UUID,
    ) -> WorkspaceState:
        """Delete only a non-active version; active schedules require clear first."""

        self._validate_mutation(state, request)
        active_count = min(len(state.planning_strategies), len(state.itineraries))
        active_ids = {item.itinerary_id for item in state.itineraries[:active_count]}
        if itinerary_id in active_ids:
            raise ValueError("active itinerary must be cleared before deletion")
        all_ids = {item.itinerary_id for item in (*state.itineraries, *state.archived_itineraries)}
        if itinerary_id not in all_ids:
            raise ValueError("itinerary version does not belong to this workspace")
        return state.model_copy(
            update={
                "state_version": state.state_version + 1,
                "itineraries": tuple(
                    item for item in state.itineraries if item.itinerary_id != itinerary_id
                ),
                "archived_itineraries": tuple(
                    item for item in state.archived_itineraries if item.itinerary_id != itinerary_id
                ),
            }
        )

    def _replace_knowledge_rules(
        self,
        state: WorkspaceState,
        request: WorkspaceMutationRequest,
        rules: tuple[DerivedKnowledgeRule, ...],
    ) -> WorkspaceState:
        """Revalidate the plan whenever active knowledge constraints change."""

        self._validate_mutation(state, request)
        next_version = state.state_version + 1
        working = state.model_copy(update={"knowledge_rules": rules})
        if (
            state.itineraries
            and state.selected_base_id
            and state.requirements.start_date
            and state.requirements.end_date
        ):
            updated = self._execute_plan(
                working,
                base_id=state.selected_base_id,
                access=state.selected_access,
                timezone=state.itineraries[0].timezone,
                strategies=state.planning_strategies,
                next_version=next_version,
            )
        else:
            updated = working.model_copy(update={"state_version": next_version})
        return updated.model_copy(
            update={
                "diffs": (
                    *updated.diffs,
                    PlanVersionDiff(
                        from_version=state.state_version,
                        to_version=next_version,
                        validation_before=tuple(
                            sorted(
                                {
                                    issue.code
                                    for item in state.itineraries
                                    for issue in item.validation_issues
                                }
                            )
                        ),
                        validation_after=tuple(
                            sorted(
                                {
                                    issue.code
                                    for item in updated.itineraries[
                                        : len(updated.planning_strategies)
                                    ]
                                    for issue in item.validation_issues
                                }
                            )
                        ),
                    ),
                )
            }
        )

    def deactivate_knowledge_rule(
        self,
        state: WorkspaceState,
        request: WorkspaceMutationRequest,
        rule_id: UUID,
    ) -> WorkspaceState:
        rule = next((item for item in state.knowledge_rules if item.rule_id == rule_id), None)
        if rule is None:
            raise ValueError("knowledge rule does not belong to this workspace")
        if rule.status != "active_constraint":
            raise ValueError("only an active knowledge rule can be deactivated")
        rules = tuple(
            item.model_copy(update={"status": "proposed"})
            if item.rule_id == rule_id
            else item
            for item in state.knowledge_rules
        )
        return self._replace_knowledge_rules(state, request, rules)

    def delete_knowledge_rule(
        self,
        state: WorkspaceState,
        request: WorkspaceMutationRequest,
        rule_id: UUID,
    ) -> WorkspaceState:
        if rule_id not in {item.rule_id for item in state.knowledge_rules}:
            raise ValueError("knowledge rule does not belong to this workspace")
        rules = tuple(item for item in state.knowledge_rules if item.rule_id != rule_id)
        return self._replace_knowledge_rules(state, request, rules)

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
                    if len(intents) >= 12:
                        raise ValueError("a workspace supports at most twelve subjects")
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
                            item for item in confirmed if item.intent_id != current_intent.intent_id
                        ]
                        if current_intent.catalog_subject_ids:
                            removed_subject_ids = set(current_intent.catalog_subject_ids)
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
                        *(item for item in strategies if item is not operation.strategy),
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
        requirements_data["anime_query"] = next(item.query for item in intents if item.is_primary)
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
                key: value for key, value in fixed_positions.items() if key in current_place_ids
            }
        applied_patch = patch.model_copy(update={"status": "applied"})
        patches = tuple(
            applied_patch if item.patch_id == patch.patch_id else item for item in state.patches
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
                    "candidate_graph": None if recurate else state.candidate_graph,
                    "itineraries": () if recurate else state.itineraries,
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
