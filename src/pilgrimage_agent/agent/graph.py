"""Durable mixed-initiative LangGraph with three explicit confirmation points."""

from __future__ import annotations

from hashlib import sha256
from typing import Any, Literal, TypedDict, cast

from langgraph.checkpoint.base import BaseCheckpointSaver
from langgraph.graph import END, START, StateGraph
from langgraph.graph.state import CompiledStateGraph
from langgraph.types import interrupt

from pilgrimage_agent.agent.context import ContextBuilder
from pilgrimage_agent.agent.review import FixtureReviewer
from pilgrimage_agent.agent.schemas import (
    ConfirmationDecision,
    ConfirmationRequest,
    ReviewerInput,
    WorkflowStatus,
)


class WorkflowState(TypedDict, total=False):
    owner_user_id: str
    thread_id: str
    trip_id: str
    request_summary: str
    status: str
    phase: str
    candidate_subject_id: str
    route_a_point_ids: tuple[str, ...]
    plan_day_hashes: tuple[str, ...]
    deterministic_violations: tuple[str, ...]
    revision_count: int
    next_action: str
    warnings: tuple[str, ...]
    context_snapshot_id: str


RouteName = Literal["continue", "stop", "replan", "present"]
WorkflowGraph = CompiledStateGraph[WorkflowState, None, WorkflowState, WorkflowState]


def _hash_day(trip_id: str, day: int, revision: int = 0) -> str:
    return sha256(f"{trip_id}:day:{day}:revision:{revision}".encode()).hexdigest()[:16]


def build_workflow(
    checkpointer: BaseCheckpointSaver[Any] | None = None,
    *,
    reviewer: FixtureReviewer | None = None,
    fail_fetch: bool = False,
    inject_first_violation: bool = False,
) -> WorkflowGraph:
    """Compile one workflow implementation for memory and PostgreSQL checkpointers."""

    context_builder = ContextBuilder()
    reviewer_boundary = reviewer or FixtureReviewer()

    def requirement(state: WorkflowState) -> WorkflowState:
        return {
            "status": WorkflowStatus.RUNNING.value,
            "phase": "requirement",
            "revision_count": 0,
            "warnings": (),
        }

    def confirm_requirements(state: WorkflowState) -> WorkflowState:
        request = ConfirmationRequest(
            kind="requirements",
            title="Confirm trip requirements",
            summary=state["request_summary"],
            requires_explicit_choice=True,
        )
        decision = ConfirmationDecision.model_validate(interrupt(request.model_dump(mode="json")))
        if decision.decision == "reject":
            return {"status": WorkflowStatus.REJECTED.value, "phase": "requirements_rejected"}
        return {"status": WorkflowStatus.RUNNING.value, "phase": "requirements_confirmed"}

    def resolve_subject(state: WorkflowState) -> WorkflowState:
        del state
        return {"phase": "resolve_subject", "candidate_subject_id": "fixture-kyoto-animation"}

    def confirm_subject(state: WorkflowState) -> WorkflowState:
        request = ConfirmationRequest(
            kind="subject",
            title="Confirm the matched work",
            summary=f"Candidate subject: {state['candidate_subject_id']}",
            requires_explicit_choice=True,
        )
        decision = ConfirmationDecision.model_validate(interrupt(request.model_dump(mode="json")))
        if decision.decision == "reject":
            return {"status": WorkflowStatus.REJECTED.value, "phase": "subject_rejected"}
        return {"phase": "subject_confirmed"}

    def fetch_points(state: WorkflowState) -> WorkflowState:
        if fail_fetch:
            return {
                "status": WorkflowStatus.PARTIAL.value,
                "phase": "fetch_points_partial",
                "warnings": (
                    "Pilgrimage point provider was unavailable; no points were invented.",
                ),
            }
        point_ids = tuple(
            f"{state['candidate_subject_id']}-point-{number}" for number in range(1, 5)
        )
        return {"phase": "fetch_points", "route_a_point_ids": point_ids}

    def build_route_a(state: WorkflowState) -> WorkflowState:
        del state
        return {"phase": "build_route_a"}

    def access_planner(state: WorkflowState) -> WorkflowState:
        del state
        return {"phase": "access_planner"}

    def confirm_access(state: WorkflowState) -> WorkflowState:
        del state
        request = ConfirmationRequest(
            kind="access_and_base",
            title="Confirm access and base",
            summary="Rail access and Tokyo Station base; no booking or payment action.",
            requires_explicit_choice=True,
        )
        decision = ConfirmationDecision.model_validate(interrupt(request.model_dump(mode="json")))
        if decision.decision == "reject":
            return {"status": WorkflowStatus.REJECTED.value, "phase": "access_rejected"}
        return {"phase": "access_confirmed"}

    def retrieve_knowledge(state: WorkflowState) -> WorkflowState:
        del state
        return {"phase": "retrieve_knowledge"}

    def planner(state: WorkflowState) -> WorkflowState:
        hashes = tuple(_hash_day(state["trip_id"], day) for day in range(1, 4))
        return {"phase": "pilgrimage_planner", "plan_day_hashes": hashes}

    def validator(state: WorkflowState) -> WorkflowState:
        revision = state.get("revision_count", 0)
        violations = ("day_2_walking_limit",) if inject_first_violation and revision == 0 else ()
        return {"phase": "deterministic_validator", "deterministic_violations": violations}

    def review(state: WorkflowState) -> WorkflowState:
        snapshot = context_builder.build(
            node="reviewer",
            owner_user_id=state["owner_user_id"],
            thread_id=state["thread_id"],
            trip_id=state["trip_id"],
            facts=(
                f"revision_count={state.get('revision_count', 0)}",
                f"violation_count={len(state.get('deterministic_violations', ()))}",
            ),
            route_a_point_ids=state.get("route_a_point_ids", ()),
        )
        output = reviewer_boundary.review(
            ReviewerInput(
                context_snapshot_id=snapshot.snapshot_id,
                deterministic_violations=state.get("deterministic_violations", ()),
                revision_count=state.get("revision_count", 0),
            )
        )
        next_action = "present" if output.action == "accept" else "replan"
        if next_action == "replan" and state.get("revision_count", 0) >= 3:
            return {
                "status": WorkflowStatus.PARTIAL.value,
                "phase": "revision_limit_reached",
                "next_action": "stop",
                "warnings": ("The deterministic three-revision limit was reached.",),
                "context_snapshot_id": snapshot.snapshot_id,
            }
        return {
            "phase": "reviewer",
            "next_action": next_action,
            "context_snapshot_id": snapshot.snapshot_id,
        }

    def replan(state: WorkflowState) -> WorkflowState:
        revision = state.get("revision_count", 0) + 1
        hashes = list(state["plan_day_hashes"])
        hashes[1] = _hash_day(state["trip_id"], 2, revision)
        return {
            "phase": "replan_day_2",
            "revision_count": revision,
            "plan_day_hashes": tuple(hashes),
        }

    def present(state: WorkflowState) -> WorkflowState:
        del state
        return {"status": WorkflowStatus.COMPLETE.value, "phase": "present"}

    def accepted_route(state: WorkflowState) -> RouteName:
        return "stop" if state.get("status") == WorkflowStatus.REJECTED.value else "continue"

    def fetch_route(state: WorkflowState) -> RouteName:
        return "stop" if state.get("status") == WorkflowStatus.PARTIAL.value else "continue"

    def review_route(state: WorkflowState) -> RouteName:
        return cast(RouteName, state["next_action"])

    graph: StateGraph[WorkflowState, None, WorkflowState, WorkflowState] = StateGraph(WorkflowState)
    graph.add_node("requirement", requirement)
    graph.add_node("confirm_requirements", confirm_requirements)
    graph.add_node("resolve_subject", resolve_subject)
    graph.add_node("confirm_subject", confirm_subject)
    graph.add_node("fetch_points", fetch_points)
    graph.add_node("build_route_a", build_route_a)
    graph.add_node("access_planner", access_planner)
    graph.add_node("confirm_access_and_base", confirm_access)
    graph.add_node("retrieve_knowledge", retrieve_knowledge)
    graph.add_node("pilgrimage_planner", planner)
    graph.add_node("deterministic_validator", validator)
    graph.add_node("reviewer", review)
    graph.add_node("replan", replan)
    graph.add_node("present", present)
    graph.add_edge(START, "requirement")
    graph.add_edge("requirement", "confirm_requirements")
    graph.add_conditional_edges(
        "confirm_requirements",
        accepted_route,
        {"continue": "resolve_subject", "stop": END},
    )
    graph.add_edge("resolve_subject", "confirm_subject")
    graph.add_conditional_edges(
        "confirm_subject", accepted_route, {"continue": "fetch_points", "stop": END}
    )
    graph.add_conditional_edges(
        "fetch_points", fetch_route, {"continue": "build_route_a", "stop": END}
    )
    graph.add_edge("build_route_a", "access_planner")
    graph.add_edge("access_planner", "confirm_access_and_base")
    graph.add_conditional_edges(
        "confirm_access_and_base",
        accepted_route,
        {"continue": "retrieve_knowledge", "stop": END},
    )
    graph.add_edge("retrieve_knowledge", "pilgrimage_planner")
    graph.add_edge("pilgrimage_planner", "deterministic_validator")
    graph.add_edge("deterministic_validator", "reviewer")
    graph.add_conditional_edges(
        "reviewer", review_route, {"present": "present", "replan": "replan", "stop": END}
    )
    graph.add_edge("replan", "deterministic_validator")
    graph.add_edge("present", END)
    return graph.compile(checkpointer=checkpointer)
