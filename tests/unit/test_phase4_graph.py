"""Phase 4 graph confirmation, failure, and bounded replan behavior."""

from hashlib import sha256
from typing import cast

from langchain_core.runnables import RunnableConfig
from langgraph.checkpoint.memory import InMemorySaver
from langgraph.types import Command, Interrupt

from pilgrimage_agent.agent.graph import WorkflowGraph, WorkflowState, build_workflow
from pilgrimage_agent.agent.review import FixtureReviewer

INITIAL: WorkflowState = {
    "owner_user_id": "user-a",
    "thread_id": "thread-a",
    "trip_id": "018f5cee-7f16-7ef3-ba85-b0d3447ca5fe",
    "request_summary": "Three low-walking days from Kyoto to Tokyo.",
}


def _config(thread_id: str = "graph-test") -> RunnableConfig:
    return {"configurable": {"thread_id": thread_id}}


def _resume(
    graph: WorkflowGraph, config: RunnableConfig, decision: str = "accept"
) -> WorkflowState:
    return cast(WorkflowState, graph.invoke(Command(resume={"decision": decision}), config))


def _interrupt_kind(state: WorkflowState) -> object:
    raw = cast(dict[str, object], state)
    interrupts = cast(tuple[Interrupt, ...], raw["__interrupt__"])
    return cast(dict[str, object], interrupts[0].value)["kind"]


def _advance_three_confirmations(
    graph: WorkflowGraph, config: RunnableConfig
) -> tuple[WorkflowState, WorkflowState, WorkflowState, WorkflowState]:
    first = cast(WorkflowState, graph.invoke(INITIAL, config))
    second = _resume(graph, config)
    third = _resume(graph, config)
    fourth = _resume(graph, config)
    return first, second, third, fourth


def test_graph_interrupts_three_times_then_completes() -> None:
    states = _advance_three_confirmations(build_workflow(InMemorySaver()), _config())
    assert [_interrupt_kind(state) for state in states[:3]] == [
        "requirements",
        "subject",
        "access_and_base",
    ]
    assert states[3]["status"] == "complete"
    assert states[3]["phase"] == "present"
    assert states[3]["revision_count"] == 0


def test_rejected_confirmation_stops_without_fetching() -> None:
    graph = build_workflow(InMemorySaver())
    config = _config("reject-test")
    graph.invoke(INITIAL, config)
    result = _resume(graph, config, "reject")
    assert result["status"] == "rejected"
    assert "route_a_point_ids" not in result


def test_tool_failure_returns_partial_without_inventing_points() -> None:
    graph = build_workflow(InMemorySaver(), fail_fetch=True)
    config = _config("tool-failure")
    graph.invoke(INITIAL, config)
    _resume(graph, config)
    result = _resume(graph, config)
    assert result["status"] == "partial"
    assert "route_a_point_ids" not in result
    assert "no points were invented" in result["warnings"][0]


def test_day_two_local_replan_preserves_other_day_hashes() -> None:
    graph = build_workflow(InMemorySaver(), inject_first_violation=True)
    result = _advance_three_confirmations(graph, _config("local-replan"))[3]
    trip_id = INITIAL["trip_id"]
    original = tuple(
        sha256(f"{trip_id}:day:{day}:revision:0".encode()).hexdigest()[:16] for day in range(1, 4)
    )
    assert result["status"] == "complete"
    assert result["revision_count"] == 1
    assert result["plan_day_hashes"][0] == original[0]
    assert result["plan_day_hashes"][1] != original[1]
    assert result["plan_day_hashes"][2] == original[2]


def test_nonconverging_reviewer_stops_at_three_revisions() -> None:
    graph = build_workflow(InMemorySaver(), reviewer=FixtureReviewer(always_revise=True))
    result = _advance_three_confirmations(graph, _config("bounded-revision"))[3]
    assert result["status"] == "partial"
    assert result["revision_count"] == 3
    assert result["phase"] == "revision_limit_reached"
