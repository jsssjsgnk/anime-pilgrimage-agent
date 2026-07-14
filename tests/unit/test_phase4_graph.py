"""Integrated Agent graph confirmation, MCP data, failure, and bounded replan behavior."""

from datetime import date, timedelta
from hashlib import sha256
from typing import cast

from langchain_core.runnables import RunnableConfig
from langgraph.checkpoint.memory import InMemorySaver
from langgraph.types import Command, Interrupt

from pilgrimage_agent.agent.graph import WorkflowGraph, WorkflowState, build_workflow
from pilgrimage_agent.agent.review import FixtureReviewer
from pilgrimage_agent.api.main import _workflow_response
from pilgrimage_agent.domain.models import RouteA
from pilgrimage_agent.domain.planning import PlanningOptions, RouteBPlan
from pilgrimage_agent.planning.modification import (
    parse_local_modification,
    replan_local_walking,
)

START = date.today() + timedelta(days=60)
INITIAL: WorkflowState = {
    "owner_user_id": "user-a",
    "thread_id": "thread-a",
    "trip_id": "018f5cee-7f16-7ef3-ba85-b0d3447ca5fe",
    "request_summary": "Three low-walking days from Kyoto to Tokyo for Bocchi the Rock.",
    "requirements": {
        "origin": "Kyoto",
        "destination": "Tokyo",
        "start_date": START.isoformat(),
        "end_date": (START + timedelta(days=2)).isoformat(),
        "anime_query": "孤独摇滚",
        "budget_level": "medium",
        "walking_preference": "low",
        "max_walking_meters_per_day": 5_000,
        "origin_iata": None,
        "destination_iata": None,
        "adults": 1,
        "cabin_class": "economy",
        "currency": "JPY",
        "must_visit_point_ids": [],
        "excluded_point_ids": [],
    },
}


def _config(thread_id: str = "graph-test") -> RunnableConfig:
    return {"configurable": {"thread_id": thread_id}}


async def _resume(
    graph: WorkflowGraph,
    config: RunnableConfig,
    **decision: object,
) -> WorkflowState:
    payload: dict[str, object] = {"decision": "accept", **decision}
    return cast(WorkflowState, await graph.ainvoke(Command(resume=payload), config))


def _interrupt_kind(state: WorkflowState) -> object:
    raw = cast(dict[str, object], state)
    interrupts = cast(tuple[Interrupt, ...], raw["__interrupt__"])
    return cast(dict[str, object], interrupts[0].value)["kind"]


async def _advance_three_confirmations(
    graph: WorkflowGraph, config: RunnableConfig
) -> tuple[WorkflowState, WorkflowState, WorkflowState, WorkflowState]:
    first = cast(WorkflowState, await graph.ainvoke(INITIAL, config))
    second = await _resume(graph, config)
    third = await _resume(graph, config, selected_subject_id="328609")
    fourth = await _resume(
        graph,
        config,
        inbound_option_id="manual-inbound",
        outbound_option_id="manual-outbound",
        base_id="route-centroid",
    )
    return first, second, third, fourth


async def test_graph_interrupts_three_times_then_completes_with_real_models() -> None:
    states = await _advance_three_confirmations(build_workflow(InMemorySaver()), _config())
    assert [_interrupt_kind(state) for state in states[:3]] == [
        "requirements",
        "subject",
        "access_and_base",
    ]
    result = states[3]
    assert result["status"] == "complete"
    assert result["phase"] == "present"
    assert len(RouteA.model_validate(result["route_a"]).points) == 3
    plan = RouteBPlan.model_validate(result["route_b"])
    assert plan.route_a_point_ids
    assert not result["deterministic_violations"]
    response = _workflow_response(result)
    assert response.route_a is not None
    assert response.route_b is not None
    assert response.weather is not None
    assert response.knowledge is not None


async def test_rejected_confirmation_stops_without_fetching() -> None:
    graph = build_workflow(InMemorySaver())
    config = _config("reject-test")
    await graph.ainvoke(INITIAL, config)
    result = cast(
        WorkflowState,
        await graph.ainvoke(Command(resume={"decision": "reject"}), config),
    )
    assert result["status"] == "rejected"
    assert "route_a" not in result


async def test_tool_failure_returns_partial_without_inventing_points() -> None:
    graph = build_workflow(InMemorySaver(), fail_fetch=True)
    config = _config("tool-failure")
    await graph.ainvoke(INITIAL, config)
    await _resume(graph, config)
    result = await _resume(graph, config, selected_subject_id="328609")
    assert result["status"] == "partial"
    assert "route_a" not in result
    assert "no points were invented" in result["warnings"][0]


async def test_day_two_local_replan_preserves_other_day_hashes() -> None:
    graph = build_workflow(InMemorySaver(), inject_first_violation=True)
    result = (await _advance_three_confirmations(graph, _config("local-replan")))[3]
    plan = RouteBPlan.model_validate(result["route_b"])
    baseline = tuple(
        sha256(f"{day.model_dump_json()}|revision=0".encode()).hexdigest()[:16]
        for day in plan.days
    )
    assert result["status"] == "complete"
    assert result["revision_count"] == 1
    assert result["plan_day_hashes"][0] == baseline[0]
    assert result["plan_day_hashes"][1] != baseline[1]
    assert result["plan_day_hashes"][2] == baseline[2]


async def test_nonconverging_reviewer_stops_at_three_revisions() -> None:
    graph = build_workflow(InMemorySaver(), reviewer=FixtureReviewer(always_revise=True))
    result = (await _advance_three_confirmations(graph, _config("bounded-revision")))[3]
    assert result["status"] == "partial"
    assert result["revision_count"] == 3
    assert result["phase"] == "revision_limit_reached"


async def test_natural_language_local_replan_reduces_day_two_by_thirty_percent() -> None:
    result = (await _advance_three_confirmations(
        build_workflow(InMemorySaver()), _config("local-modification")
    ))[3]
    original = RouteBPlan.model_validate(result["route_b"])
    route_a = RouteA.model_validate(result["route_a"])
    modification = parse_local_modification("第二天少走 30%, 保留其他天")
    changed, warnings = replan_local_walking(original, route_a, modification)

    assert changed.days[0] == original.days[0]
    assert changed.days[2] == original.days[2]
    assert changed.days[1].walking_distance_meters <= (
        original.days[1].walking_distance_meters * 0.7
    )
    assert warnings


async def test_agent_presents_flights_beside_manual_options_when_iata_is_confirmed() -> None:
    with_iata: WorkflowState = {
        **INITIAL,
        "requirements": {
            **INITIAL["requirements"],
            "origin_iata": "ITM",
            "destination_iata": "HND",
        },
    }
    graph = build_workflow(InMemorySaver())
    config = _config("flight-options")
    await graph.ainvoke(with_iata, config)
    await _resume(graph, config)
    result = await _resume(graph, config, selected_subject_id="328609")

    options = PlanningOptions.model_validate(result["planning_options"])
    modes = {item.mode for item in options.access_options}
    assert modes == {"manual", "flight"}
    flight = next(item for item in options.access_options if item.mode == "flight")
    assert set(flight.comparison_labels) == {
        "recommended",
        "fastest",
        "cheapest",
        "fewest_transfers",
    }
