"""Strict schemas at workflow, confirmation, and LLM boundaries."""

from datetime import datetime
from enum import StrEnum
from typing import Literal
from uuid import UUID, uuid4

from pydantic import Field

from pilgrimage_agent.domain.models import (
    ConfirmedSubject,
    RouteA,
    StrictModel,
    SubjectCandidate,
    TripRequest,
    WeatherForecastResult,
)
from pilgrimage_agent.domain.planning import PlanningOptions, RouteBPlan, ValidationIssue
from pilgrimage_agent.rag.schemas import KnowledgeSearchResult


class WorkflowStatus(StrEnum):
    WAITING = "waiting_confirmation"
    RUNNING = "running"
    COMPLETE = "complete"
    PARTIAL = "partial"
    REJECTED = "rejected"


class ConfirmationDecision(StrictModel):
    decision: Literal["accept", "reject"]
    note: str | None = Field(default=None, max_length=300)
    requirements: TripRequest | None = None
    selected_subject_id: str | None = Field(default=None, max_length=50)
    inbound_option_id: str | None = Field(default=None, max_length=100)
    outbound_option_id: str | None = Field(default=None, max_length=100)
    base_id: str | None = Field(default=None, max_length=100)


class ConfirmationRequest(StrictModel):
    kind: Literal["requirements", "subject", "access_and_base"]
    title: str = Field(min_length=1, max_length=120)
    summary: str = Field(min_length=1, max_length=500)
    requires_explicit_choice: Literal[True] = True


class StartWorkflowRequest(StrictModel):
    owner_user_id: str = Field(min_length=1, max_length=120)
    thread_id: str = Field(min_length=1, max_length=120)
    trip_id: UUID = Field(default_factory=uuid4)
    request_summary: str = Field(min_length=1, max_length=1000)
    requirements: TripRequest | None = None
    apply_saved_preferences: bool = False


class RequirementExtraction(StrictModel):
    requirements: TripRequest
    source: Literal["llm", "deterministic_fallback"]
    assumptions: tuple[str, ...] = ()
    missing_fields: tuple[
        Literal["origin", "destination", "start_date", "end_date", "anime_query"], ...
    ] = ()


class ResumeWorkflowRequest(StrictModel):
    owner_user_id: str = Field(min_length=1, max_length=120)
    thread_id: str = Field(min_length=1, max_length=120)
    decision: ConfirmationDecision


class ModifyWorkflowRequest(StrictModel):
    owner_user_id: str = Field(min_length=1, max_length=120)
    thread_id: str = Field(min_length=1, max_length=120)
    instruction: str = Field(min_length=2, max_length=500)


class PlanModification(StrictModel):
    target_day: int = Field(ge=1, le=30)
    walking_reduction_percent: int = Field(ge=1, le=90)
    reason: str = Field(min_length=1, max_length=300)


class ConversationIntent(StrEnum):
    TRIP_STARTED = "trip_started"
    STATUS = "status"
    EXPLAIN_PLAN = "explain_plan"
    MODIFY_PLAN = "modify_plan"
    CONFIRMATION_HELP = "confirmation_help"
    POINT_COVERAGE = "point_coverage"
    WEATHER = "weather"
    EVIDENCE = "evidence"
    ACCESS = "access"
    UNSUPPORTED_CHANGE = "unsupported_change"
    GENERAL = "general"


class ConversationAction(StrictModel):
    kind: Literal[
        "none",
        "workflow_modified",
        "confirmation_required",
        "unsupported_change",
    ] = "none"
    target_day: int | None = Field(default=None, ge=1, le=30)
    revision_count: int | None = Field(default=None, ge=0, le=3)


class ConversationEventPayload(StrictModel):
    role: Literal["user", "assistant"]
    content: str = Field(min_length=1, max_length=2000)
    intent: ConversationIntent
    action: ConversationAction = Field(default_factory=ConversationAction)
    memory_kind: Literal[
        "ordinary", "hard_constraint", "confirmation", "rejection"
    ] = "ordinary"


class ConversationMessage(ConversationEventPayload):
    message_id: UUID
    created_at: datetime


class ConversationSummaryPayload(StrictModel):
    """Traceable prompt summary; the source messages remain immutable events."""

    source_first_message_id: UUID
    through_message_id: UUID
    summarized_message_count: int = Field(ge=1)
    summary: str = Field(min_length=1, max_length=8000)
    critical_decisions: tuple[str, ...] = Field(default=(), max_length=120)


class ConversationPromptWindow(StrictModel):
    """Budgeted context passed to a conversational reasoning boundary."""

    summary: str | None = Field(default=None, max_length=8000)
    critical_decisions: tuple[str, ...] = Field(default=(), max_length=120)
    recent_messages: tuple[ConversationMessage, ...] = Field(max_length=12)


class ConversationRequest(StrictModel):
    owner_user_id: str = Field(min_length=1, max_length=120)
    thread_id: str = Field(min_length=1, max_length=120)
    message: str = Field(min_length=1, max_length=2000)


class ConversationDecision(StrictModel):
    intent: ConversationIntent
    answer: str = Field(min_length=1, max_length=2000)
    modification: PlanModification | None = None
    supporting_fields: tuple[
        Literal[
            "phase",
            "pending_confirmation",
            "subject",
            "route_a",
            "route_b",
            "weather",
            "knowledge",
            "warnings",
            "validation",
        ],
        ...,
    ] = ()


class WorkflowResponse(StrictModel):
    trip_id: UUID
    thread_id: str
    status: WorkflowStatus
    phase: str
    pending_confirmation: ConfirmationRequest | None = None
    revision_count: int = Field(default=0, ge=0, le=3)
    warnings: tuple[str, ...] = ()
    plan_day_hashes: tuple[str, ...] = ()
    requirements: TripRequest | None = None
    requirement_source: Literal["provided", "llm", "deterministic_fallback"] | None = None
    requirement_assumptions: tuple[str, ...] = ()
    effective_walking_limit: float | None = Field(default=None, gt=0, le=50_000)
    applied_preference_keys: tuple[str, ...] = ()
    subject_candidates: tuple[SubjectCandidate, ...] = ()
    confirmed_subject: ConfirmedSubject | None = None
    route_a: RouteA | None = None
    planning_options: PlanningOptions | None = None
    route_b: RouteBPlan | None = None
    weather: WeatherForecastResult | None = None
    knowledge: KnowledgeSearchResult | None = None
    validation_issues: tuple[ValidationIssue, ...] = ()
    reviewer_explanation: str | None = Field(default=None, max_length=500)


class ConversationResponse(StrictModel):
    trip_id: UUID
    messages: tuple[ConversationMessage, ...] = Field(max_length=50)
    assistant_message: ConversationMessage
    workflow: WorkflowResponse


class ReviewerInput(StrictModel):
    context_snapshot_id: str = Field(min_length=1, max_length=120)
    deterministic_violations: tuple[str, ...]
    revision_count: int = Field(ge=0, le=3)


class ReviewerOutput(StrictModel):
    action: Literal["accept", "revise"]
    target_day: int | None = Field(default=None, ge=1, le=30)
    explanation: str = Field(min_length=1, max_length=500)


class WorkspaceReplannerInput(StrictModel):
    context_snapshot_id: str = Field(min_length=1, max_length=120)
    target_day: int = Field(ge=1, le=30)
    reviewer_explanation: str = Field(min_length=1, max_length=500)
    deterministic_violations: tuple[str, ...]
    stable_day_numbers: tuple[int, ...]
    revision_count: int = Field(ge=0, le=3)


class WorkspaceReplannerOutput(StrictModel):
    action: Literal["apply_targeted_revision", "stop_partial"]
    target_day: int = Field(ge=1, le=30)
    explanation: str = Field(min_length=1, max_length=500)


class ReplanPatch(StrictModel):
    target_day: int = Field(ge=1, le=30)
    reason: str = Field(min_length=1, max_length=300)


class ContextSnapshot(StrictModel):
    snapshot_id: str = Field(min_length=1, max_length=120)
    schema_version: Literal["1"] = "1"
    node: str = Field(min_length=1, max_length=80)
    state_ids: tuple[str, ...]
    fact_summary: tuple[str, ...]
    route_a_point_ids: tuple[str, ...] = ()
    relevant_knowledge_ids: tuple[str, ...] = ()
    estimated_tokens: int = Field(ge=0, le=4000)
    excluded_categories: tuple[str, ...] = (
        "raw_chat_history",
        "credentials",
        "authorization_headers",
        "raw_tool_payloads",
    )


class RunMetric(StrictModel):
    run_id: UUID = Field(default_factory=uuid4)
    node: str
    duration_ms: int = Field(ge=0)
    retry_count: int = Field(ge=0, le=3)
    outcome: Literal["ok", "partial", "error"]
