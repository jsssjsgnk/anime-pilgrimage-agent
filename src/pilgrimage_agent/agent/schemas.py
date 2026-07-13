"""Strict schemas at workflow, confirmation, and LLM boundaries."""

from enum import StrEnum
from typing import Literal
from uuid import UUID, uuid4

from pydantic import Field

from pilgrimage_agent.domain.models import StrictModel


class WorkflowStatus(StrEnum):
    WAITING = "waiting_confirmation"
    RUNNING = "running"
    COMPLETE = "complete"
    PARTIAL = "partial"
    REJECTED = "rejected"


class ConfirmationDecision(StrictModel):
    decision: Literal["accept", "reject"]
    note: str | None = Field(default=None, max_length=300)


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


class ResumeWorkflowRequest(StrictModel):
    owner_user_id: str = Field(min_length=1, max_length=120)
    thread_id: str = Field(min_length=1, max_length=120)
    decision: ConfirmationDecision


class WorkflowResponse(StrictModel):
    trip_id: UUID
    thread_id: str
    status: WorkflowStatus
    phase: str
    pending_confirmation: ConfirmationRequest | None = None
    revision_count: int = Field(default=0, ge=0, le=3)
    warnings: tuple[str, ...] = ()
    plan_day_hashes: tuple[str, ...] = ()


class ReviewerInput(StrictModel):
    context_snapshot_id: str = Field(min_length=1, max_length=120)
    deterministic_violations: tuple[str, ...]
    revision_count: int = Field(ge=0, le=3)


class ReviewerOutput(StrictModel):
    action: Literal["accept", "revise"]
    target_day: int | None = Field(default=None, ge=1, le=30)
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
