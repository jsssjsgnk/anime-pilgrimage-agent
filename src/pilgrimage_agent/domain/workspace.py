"""Remediated evidence, workspace, Agent handoff, patch, and plan schemas."""

from __future__ import annotations

from datetime import date, datetime
from enum import StrEnum
from typing import Annotated, Literal
from uuid import UUID, uuid4

from pydantic import Field, HttpUrl, model_validator

from pilgrimage_agent.domain.models import DataProvenance, GeoCoordinate, StrictModel, SubjectIntent
from pilgrimage_agent.domain.planning import AccessSelection, BaseCandidate, ValidationIssue


class EvidenceResolutionStatus(StrEnum):
    PENDING = "pending"
    RESOLVED = "resolved"
    QUARANTINED = "quarantined"
    SUPERSEDED = "superseded"


class SceneEvidence(StrictModel):
    evidence_id: UUID
    subject_id: str = Field(min_length=1, max_length=50)
    provider: str = Field(min_length=1, max_length=80)
    provider_record_id: str = Field(min_length=1, max_length=200)
    coordinate: GeoCoordinate | None = None
    names: tuple[str, ...] = Field(min_length=1, max_length=12)
    description: str | None = Field(default=None, max_length=2000)
    episode_refs: tuple[str, ...] = ()
    image_url: HttpUrl | None = None
    source_url: HttpUrl | None = None
    source_label: str | None = Field(default=None, max_length=200)
    provenance: DataProvenance
    raw_fingerprint: str = Field(pattern=r"^[a-f0-9]{64}$")
    resolution_status: EvidenceResolutionStatus = EvidenceResolutionStatus.PENDING
    quarantine_reason: str | None = Field(default=None, max_length=500)

    @model_validator(mode="after")
    def quarantine_is_explained(self) -> SceneEvidence:
        if self.resolution_status is EvidenceResolutionStatus.QUARANTINED:
            if self.quarantine_reason is None:
                raise ValueError("quarantined evidence requires a reason")
        elif self.quarantine_reason is not None:
            raise ValueError("only quarantined evidence can carry a quarantine reason")
        return self


class EvidenceQuarantine(StrictModel):
    evidence_id: UUID
    reason_code: Literal["invalid_coordinate", "missing_identity", "invalid_source"]
    detail: str = Field(min_length=1, max_length=500)


class SubjectAppearance(StrictModel):
    subject_id: str = Field(min_length=1, max_length=50)
    evidence_ids: tuple[UUID, ...] = Field(min_length=1)


class VisitPlace(StrictModel):
    place_id: UUID
    canonical_name: str = Field(min_length=1, max_length=300)
    coordinate: GeoCoordinate
    place_type: Literal[
        "poi", "station", "station_exit", "facility", "street", "viewpoint", "unknown"
    ] = "unknown"
    address: str | None = Field(default=None, max_length=500)
    transport_node: str | None = Field(default=None, max_length=300)
    visitability: Literal["visitable", "restricted", "unknown"] = "unknown"
    verification_status: Literal[
        "verified", "community", "unverified", "user_provided"
    ]
    scene_evidence_ids: tuple[UUID, ...] = ()
    subject_appearances: tuple[SubjectAppearance, ...] = ()
    merge_confidence: float = Field(ge=0, le=1)
    resolution_version: str = Field(min_length=1, max_length=40)
    applied_override_ids: tuple[UUID, ...] = ()
    provenance_label: str = Field(min_length=1, max_length=120)

    @model_validator(mode="after")
    def source_and_appearance_invariants(self) -> VisitPlace:
        if not self.scene_evidence_ids and self.verification_status != "user_provided":
            raise ValueError("a visit place requires evidence or user-provided provenance")
        appearance_evidence = {
            evidence_id
            for appearance in self.subject_appearances
            for evidence_id in appearance.evidence_ids
        }
        if not appearance_evidence.issubset(set(self.scene_evidence_ids)):
            raise ValueError("subject appearances must reference linked scene evidence")
        subjects = [item.subject_id for item in self.subject_appearances]
        if len(subjects) != len(set(subjects)):
            raise ValueError("one place has at most one appearance record per subject")
        return self


class PlaceResolutionOverride(StrictModel):
    override_id: UUID = Field(default_factory=uuid4)
    action: Literal["merge", "split"]
    evidence_ids: tuple[UUID, ...] = Field(min_length=2)
    reason: str = Field(min_length=1, max_length=500)
    created_at: datetime


class AmbiguousPlaceMerge(StrictModel):
    evidence_ids: tuple[UUID, UUID]
    distance_meters: float = Field(ge=0)
    name_similarity: float = Field(ge=0, le=1)
    reason: str = Field(min_length=1, max_length=500)


class PlaceResolutionResult(StrictModel):
    policy_version: str
    evidence: tuple[SceneEvidence, ...]
    places: tuple[VisitPlace, ...]
    quarantined: tuple[EvidenceQuarantine, ...] = ()
    ambiguous_merges: tuple[AmbiguousPlaceMerge, ...] = ()
    overrides: tuple[PlaceResolutionOverride, ...] = ()

    @model_validator(mode="after")
    def every_evidence_is_accounted_for(self) -> PlaceResolutionResult:
        all_ids = {item.evidence_id for item in self.evidence}
        linked = {item for place in self.places for item in place.scene_evidence_ids}
        quarantined = {item.evidence_id for item in self.quarantined}
        if linked & quarantined or linked | quarantined != all_ids:
            raise ValueError("every evidence record must be linked or quarantined exactly once")
        return self


class AreaCluster(StrictModel):
    area_id: UUID
    label: str = Field(min_length=1, max_length=300)
    representative_coordinate: GeoCoordinate
    place_ids: tuple[UUID, ...] = Field(min_length=1)
    nearest_transport_nodes: tuple[str, ...] = ()
    estimated_visit_minutes: int = Field(ge=0)
    internal_walking_meters: float = Field(ge=0)
    algorithm: Literal["haversine_dbscan"] = "haversine_dbscan"
    algorithm_version: str = Field(min_length=1, max_length=40)
    parameters: dict[str, float | int | str]
    confidence: float = Field(ge=0, le=1)
    travel_time_status: Literal["road", "haversine_fallback", "unverified"]
    warnings: tuple[str, ...] = ()


class CandidateDecision(StrictModel):
    entity_type: Literal["place", "area"]
    entity_id: UUID
    status: Literal["included", "recommended", "excluded"]
    reason_code: str = Field(min_length=1, max_length=80)
    detail: str = Field(min_length=1, max_length=500)


class CandidateEdge(StrictModel):
    source_type: str = Field(min_length=1, max_length=40)
    source_id: str = Field(min_length=1, max_length=120)
    relation: Literal[
        "appearance",
        "contains",
        "near",
        "reachable",
        "supported_by",
        "conflicts_with",
        "requires_confirmation",
    ]
    target_type: str = Field(min_length=1, max_length=40)
    target_id: str = Field(min_length=1, max_length=120)


class TripCandidateGraph(StrictModel):
    graph_id: UUID = Field(default_factory=uuid4)
    trip_id: UUID
    version: int = Field(ge=1)
    subject_intent_ids: tuple[UUID, ...] = Field(min_length=1, max_length=12)
    place_ids: tuple[UUID, ...]
    area_ids: tuple[UUID, ...]
    decisions: tuple[CandidateDecision, ...]
    edges: tuple[CandidateEdge, ...]
    evidence_status: Literal["complete", "partial", "stale", "unverified"]
    created_at: datetime


class PlanningStrategy(StrEnum):
    BALANCED = "balanced"
    PRIMARY_SUBJECT_FIRST = "primary_subject_first"
    LOW_WALKING = "low_walking"
    GEOGRAPHIC_EFFICIENCY = "geographic_efficiency"


class ScheduledPlace(StrictModel):
    place_id: UUID
    area_id: UUID
    sequence: int = Field(ge=0)
    start_at: datetime
    end_at: datetime
    incoming_distance_meters: float = Field(ge=0)
    incoming_duration_seconds: float = Field(ge=0)

    @model_validator(mode="after")
    def visit_time_is_ordered(self) -> ScheduledPlace:
        if self.end_at <= self.start_at:
            raise ValueError("scheduled place end must follow start")
        return self


class ItineraryDay(StrictModel):
    date: date
    area_ids: tuple[UUID, ...]
    visits: tuple[ScheduledPlace, ...]
    walking_distance_meters: float = Field(ge=0)
    duration_minutes: int = Field(ge=0)


class SubjectCoverage(StrictModel):
    subject_id: str
    priority: int = Field(ge=1, le=5)
    scheduled_place_ids: tuple[UUID, ...]
    minimum_place_count: int | None = Field(default=None, ge=0)
    minimum_satisfied: bool


class StructuredOmission(StrictModel):
    place_id: UUID
    reason_code: Literal[
        "excluded",
        "time_limit",
        "walking_limit",
        "visit_window",
        "area_not_selected",
        "lower_strategy_score",
        "unverified",
        "unreachable",
    ]
    detail: str = Field(min_length=1, max_length=500)


class ScoreComponent(StrictModel):
    entity_id: UUID
    component: str = Field(min_length=1, max_length=80)
    value: float
    policy_version: str


class ItineraryVersion(StrictModel):
    itinerary_id: UUID = Field(default_factory=uuid4)
    trip_id: UUID
    candidate_graph_id: UUID
    version: int = Field(ge=1)
    parent_version: int | None = Field(default=None, ge=1)
    strategy: PlanningStrategy
    timezone: str = Field(min_length=1, max_length=80)
    access: AccessSelection | None = None
    base: BaseCandidate | None = None
    days: tuple[ItineraryDay, ...]
    subject_coverage: tuple[SubjectCoverage, ...]
    total_cost: float | None = Field(default=None, ge=0)
    currency: str | None = Field(default=None, pattern=r"^[A-Z]{3}$")
    total_walking_meters: float = Field(ge=0)
    total_duration_minutes: int = Field(ge=0)
    omissions: tuple[StructuredOmission, ...]
    score_components: tuple[ScoreComponent, ...]
    evidence_refs: tuple[str, ...]
    warnings: tuple[str, ...] = ()
    validation_issues: tuple[ValidationIssue, ...] = ()
    applied_patch_id: UUID | None = None
    created_at: datetime

    @model_validator(mode="after")
    def scheduled_places_are_unique(self) -> ItineraryVersion:
        place_ids = [visit.place_id for day in self.days for visit in day.visits]
        if len(place_ids) != len(set(place_ids)):
            raise ValueError("a real place can be scheduled only once per itinerary")
        return self


class UpdateRequirementOperation(StrictModel):
    op: Literal["update_requirement"] = "update_requirement"
    field: Literal[
        "origin",
        "destination",
        "start_date",
        "end_date",
        "budget_level",
        "walking_preference",
        "max_walking_meters_per_day",
    ]
    value: date | float | str | None

    @model_validator(mode="before")
    @classmethod
    def restore_persisted_date(cls, value: object) -> object:
        if not isinstance(value, dict):
            return value
        if value.get("field") not in {"start_date", "end_date"}:
            return value
        raw_value = value.get("value")
        if not isinstance(raw_value, str):
            return value
        restored = dict(value)
        try:
            restored["value"] = date.fromisoformat(raw_value)
        except ValueError:
            return value
        return restored

    @model_validator(mode="after")
    def value_matches_field(self) -> UpdateRequirementOperation:
        if self.field in {"origin", "destination"} and not (
            self.value is None or isinstance(self.value, str)
        ):
            raise ValueError("text requirements accept only text or null")
        if self.field in {"start_date", "end_date"} and not (
            self.value is None or isinstance(self.value, date)
        ):
            raise ValueError("date requirements accept only ISO dates or null")
        if self.field == "budget_level" and self.value not in {
            None,
            "low",
            "medium",
            "high",
        }:
            raise ValueError("budget level must be low, medium, high or null")
        if self.field == "walking_preference" and self.value not in {
            None,
            "low",
            "medium",
            "high",
        }:
            raise ValueError("walking preference must be low, medium, high or null")
        if self.field == "max_walking_meters_per_day" and not (
            self.value is None
            or (
                isinstance(self.value, (int, float))
                and 0 < float(self.value) <= 50_000
            )
        ):
            raise ValueError("walking distance must be in (0, 50000] or null")
        return self


class SubjectIntentOperation(StrictModel):
    op: Literal["subject_intent"] = "subject_intent"
    action: Literal["add", "remove", "reprioritize", "confirm", "reject"]
    intent: SubjectIntent | None = None
    intent_id: UUID | None = None
    priority: int | None = Field(default=None, ge=1, le=5)
    confirmed_subject_id: str | None = Field(default=None, max_length=50)

    @model_validator(mode="after")
    def fields_match_action(self) -> SubjectIntentOperation:
        if self.action == "add":
            if self.intent is None or any(
                item is not None
                for item in (self.intent_id, self.priority, self.confirmed_subject_id)
            ):
                raise ValueError("adding a subject requires only a new intent")
        elif self.intent_id is None or self.intent is not None:
            raise ValueError("subject changes require an existing intent ID")
        if self.action == "reprioritize" and self.priority is None:
            raise ValueError("reprioritizing requires a priority")
        if self.action == "confirm" and self.confirmed_subject_id is None:
            raise ValueError("confirming requires a catalog subject ID")
        return self


class PlaceOperation(StrictModel):
    op: Literal["place"] = "place"
    action: Literal["include", "exclude", "move_day", "reorder"]
    place_id: UUID
    target_day: int | None = Field(default=None, ge=1, le=30)
    target_position: int | None = Field(default=None, ge=0, le=100)

    @model_validator(mode="after")
    def target_matches_action(self) -> PlaceOperation:
        if self.action == "move_day" and self.target_day is None:
            raise ValueError("moving a place requires a target day")
        if self.action == "reorder" and (
            self.target_day is None or self.target_position is None
        ):
            raise ValueError("reordering requires a target day and position")
        if self.action in {"include", "exclude"} and (
            self.target_day is not None or self.target_position is not None
        ):
            raise ValueError("include/exclude operations do not accept a position")
        return self


class SelectionOperation(StrictModel):
    op: Literal["selection"] = "selection"
    action: Literal["change_access", "change_base", "change_strategy", "create_branch"]
    selection_id: str | None = Field(default=None, max_length=200)
    strategy: PlanningStrategy | None = None

    @model_validator(mode="after")
    def selection_matches_action(self) -> SelectionOperation:
        if self.action == "change_strategy":
            if self.strategy is None or self.selection_id is not None:
                raise ValueError("strategy changes require only a strategy")
        elif self.action in {"change_access", "change_base"}:
            if self.selection_id is None or self.strategy is not None:
                raise ValueError("access/base changes require only a selection ID")
        elif self.strategy is not None:
            raise ValueError("branch creation does not accept a strategy field")
        return self


class KnowledgeOperation(StrictModel):
    op: Literal["knowledge"] = "knowledge"
    action: Literal["attach", "remove"]
    document_id: UUID


class MergeDecisionOperation(StrictModel):
    op: Literal["merge_decision"] = "merge_decision"
    action: Literal["accept_merge", "reject_merge"]
    evidence_ids: tuple[UUID, ...] = Field(min_length=2)


PatchOperation = Annotated[
    UpdateRequirementOperation
    | SubjectIntentOperation
    | PlaceOperation
    | SelectionOperation
    | KnowledgeOperation
    | MergeDecisionOperation,
    Field(discriminator="op"),
]


class PlanPatch(StrictModel):
    patch_id: UUID = Field(default_factory=uuid4)
    trip_id: UUID
    expected_base_version: int = Field(ge=0)
    operations: tuple[PatchOperation, ...] = Field(min_length=1, max_length=25)
    rationale: str = Field(min_length=1, max_length=1000)
    requires_confirmation: bool
    idempotency_key: str = Field(min_length=8, max_length=120, pattern=r"^[A-Za-z0-9._:-]+$")
    status: Literal["proposed", "confirmed", "applied", "rejected"] = "proposed"
    created_at: datetime


class ImpactAnalysis(StrictModel):
    patch_id: UUID
    invalidated_nodes: tuple[str, ...]
    invalidated_refs: tuple[str, ...]
    stable_refs: tuple[str, ...]
    validation_required: Literal[True] = True
    reviewer_required: bool
    confirmation_required: bool


class PlanVersionDiff(StrictModel):
    from_version: int = Field(ge=0)
    to_version: int = Field(ge=1)
    changed_requirements: tuple[str, ...] = ()
    changed_subject_intents: tuple[UUID, ...] = ()
    changed_place_ids: tuple[UUID, ...] = ()
    changed_day_numbers: tuple[int, ...] = ()
    changed_access: bool = False
    changed_base: bool = False
    changed_strategy: bool = False
    validation_before: tuple[str, ...] = ()
    validation_after: tuple[str, ...] = ()


class AgentRole(StrEnum):
    REQUIREMENT = "requirement"
    SUBJECT = "subject"
    EVIDENCE_COLLECTOR = "evidence_collector"
    PLACE_CURATOR = "place_curator"
    ACCESS = "access"
    BASE = "base"
    ITINERARY_PLANNER = "itinerary_planner"
    VALIDATOR = "validator"
    REVIEWER = "reviewer"
    REPLANNER = "replanner"


class EntityRef(StrictModel):
    entity_type: str = Field(min_length=1, max_length=60)
    entity_id: str = Field(min_length=1, max_length=120)
    version: int | None = Field(default=None, ge=0)


class AgentHandoff(StrictModel):
    handoff_id: UUID = Field(default_factory=uuid4)
    run_id: UUID
    sender: AgentRole
    receiver: AgentRole
    task_type: str = Field(min_length=1, max_length=80)
    goal: str = Field(min_length=1, max_length=500)
    input_refs: tuple[EntityRef, ...]
    constraint_refs: tuple[EntityRef, ...] = ()
    evidence_refs: tuple[EntityRef, ...] = ()
    expected_output_schema: str = Field(min_length=1, max_length=200)
    status: Literal["pending", "running", "completed", "partial", "failed"]
    result_refs: tuple[EntityRef, ...] = ()
    warnings: tuple[str, ...] = ()
    safe_error: str | None = Field(default=None, max_length=500)
    retry_count: int = Field(default=0, ge=0, le=3)
    created_at: datetime
    completed_at: datetime | None = None

    @model_validator(mode="after")
    def completion_timestamp_is_consistent(self) -> AgentHandoff:
        terminal = self.status in {"completed", "partial", "failed"}
        if terminal != (self.completed_at is not None):
            raise ValueError("terminal handoff status and completion timestamp must agree")
        return self


class ContextFact(StrictModel):
    key: str = Field(min_length=1, max_length=80)
    value: str | int | float | bool | None
    source_ref: EntityRef | None = None


class RoleContext(StrictModel):
    context_id: UUID = Field(default_factory=uuid4)
    schema_version: Literal["2"] = "2"
    role: AgentRole
    run_id: UUID
    facts: tuple[ContextFact, ...]
    refs: tuple[EntityRef, ...]
    estimated_tokens: int = Field(ge=0, le=4000)
    byte_size: int = Field(ge=0, le=64_000)
    excluded_categories: tuple[str, ...] = (
        "raw_chat_history",
        "credentials",
        "authorization_headers",
        "raw_prompts",
        "raw_tool_payloads",
    )


class DerivedKnowledgeRule(StrictModel):
    rule_id: UUID = Field(default_factory=uuid4)
    trip_id: UUID
    rule_type: Literal[
        "opening_window",
        "closure_date_range",
        "photography_restriction",
        "accessibility",
        "safety",
        "etiquette",
        "transport_disruption",
    ]
    target_refs: tuple[EntityRef, ...]
    value: dict[str, str | int | float | bool | None]
    evidence_ids: tuple[str, ...] = Field(min_length=1)
    authority_level: int = Field(ge=0, le=5)
    status: Literal["proposed", "advisory", "active_constraint", "conflicted", "expired"]
    valid_from: date | None = None
    valid_until: date | None = None
    conflict_ids: tuple[str, ...] = ()
    created_at: datetime

    @model_validator(mode="after")
    def hard_constraint_requires_authority(self) -> DerivedKnowledgeRule:
        if self.status == "active_constraint" and (
            self.authority_level < 4 or self.conflict_ids
        ):
            raise ValueError("active constraints require current high-authority evidence")
        return self
