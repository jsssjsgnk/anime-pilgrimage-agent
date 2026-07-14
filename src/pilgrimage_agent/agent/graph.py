"""Durable mixed-initiative LangGraph backed by the internal read-only MCP service."""

from __future__ import annotations

from hashlib import sha256
from typing import Any, Literal, TypedDict, cast
from uuid import UUID

from langgraph.checkpoint.base import BaseCheckpointSaver
from langgraph.graph import END, START, StateGraph
from langgraph.graph.state import CompiledStateGraph
from langgraph.types import interrupt
from pydantic import BaseModel

from pilgrimage_agent.agent.context import ContextBuilder
from pilgrimage_agent.agent.knowledge import EmptyKnowledgeRetriever, KnowledgeRetriever
from pilgrimage_agent.agent.llm import (
    DeterministicRequirementExtractor,
    RequirementExtractor,
    ReviewerBoundary,
)
from pilgrimage_agent.agent.mcp_client import AgentToolClient, FixtureAgentToolClient
from pilgrimage_agent.agent.review import FixtureReviewer
from pilgrimage_agent.agent.schemas import (
    ConfirmationDecision,
    ConfirmationRequest,
    PlanModification,
    ReviewerInput,
    WorkflowStatus,
)
from pilgrimage_agent.domain.models import (
    ConfirmedSubject,
    FlightSearchQuery,
    FlightSearchResult,
    GeoCoordinate,
    PilgrimagePointQuery,
    PilgrimagePointResult,
    PlaceSearchResult,
    RouteA,
    RouteMatrix,
    SubjectSearchResult,
    TripRequest,
    WeatherForecastResult,
)
from pilgrimage_agent.domain.planning import (
    PlanningConstraints,
    PlanningOptions,
    RouteBPlan,
    ValidationIssue,
)
from pilgrimage_agent.planning.geo import haversine_matrix
from pilgrimage_agent.planning.integrated import (
    build_planning_options,
    confirmed_access,
    matrix_candidate_route,
    restore_full_route_a_membership,
    walking_limit,
    with_flight_options,
)
from pilgrimage_agent.planning.modification import replan_local_walking
from pilgrimage_agent.planning.planner import build_route_b, validate_route_b
from pilgrimage_agent.providers.points import build_route_a
from pilgrimage_agent.rag.schemas import KnowledgeSearchResult


class WorkflowState(TypedDict, total=False):
    owner_user_id: str
    thread_id: str
    trip_id: str
    request_summary: str
    status: str
    phase: str
    requirements: dict[str, object]
    requirement_source: str
    requirement_assumptions: tuple[str, ...]
    preference_defaults: dict[str, object]
    applied_preference_keys: tuple[str, ...]
    subject_candidates: tuple[dict[str, object], ...]
    confirmed_subject: dict[str, object]
    point_result: dict[str, object]
    route_a: dict[str, object]
    planning_options: dict[str, object]
    inbound_option_id: str
    outbound_option_id: str
    base_id: str
    weather: dict[str, object]
    knowledge: dict[str, object]
    route_b: dict[str, object]
    plan_day_hashes: tuple[str, ...]
    validation_issues: tuple[dict[str, object], ...]
    deterministic_violations: tuple[str, ...]
    revision_count: int
    next_action: str
    warnings: tuple[str, ...]
    reviewer_explanation: str
    reviewer_target_day: int
    context_snapshot_id: str
    effective_walking_limit: float


RouteName = Literal["continue", "stop", "replan", "present"]
WorkflowGraph = CompiledStateGraph[WorkflowState, None, WorkflowState, WorkflowState]


def _dump(model: BaseModel) -> dict[str, object]:
    return cast(dict[str, object], model.model_dump(mode="json"))


def _day_hashes(plan: RouteBPlan, revision: int = 0) -> tuple[str, ...]:
    return tuple(
        sha256(
            f"{day.model_dump_json()}|revision={revision}".encode()
        ).hexdigest()[:16]
        for day in plan.days
    )


def _required_trip_fields(request: TripRequest) -> tuple[str, ...]:
    missing: list[str] = []
    for name in ("origin", "destination", "start_date", "end_date", "anime_query"):
        if getattr(request, name) is None:
            missing.append(name)
    return tuple(missing)


def build_workflow(
    checkpointer: BaseCheckpointSaver[Any] | None = None,
    *,
    tool_client: AgentToolClient | None = None,
    reviewer: ReviewerBoundary | None = None,
    requirement_extractor: RequirementExtractor | None = None,
    knowledge_retriever: KnowledgeRetriever | None = None,
    fail_fetch: bool = False,
    inject_first_violation: bool = False,
) -> WorkflowGraph:
    """Compile the Agent graph; production injects the LangChain MCP client."""

    context_builder = ContextBuilder()
    tools = tool_client or FixtureAgentToolClient()
    reviewer_boundary = reviewer or FixtureReviewer()
    extractor = requirement_extractor or DeterministicRequirementExtractor()
    knowledge_boundary = knowledge_retriever or EmptyKnowledgeRetriever()

    async def requirement(state: WorkflowState) -> WorkflowState:
        raw = state.get("requirements")
        if raw is None:
            extracted = await extractor.extract(state["request_summary"])
            request = extracted.requirements
            source: Literal["provided", "llm", "deterministic_fallback"] = extracted.source
            assumptions = extracted.assumptions
        else:
            request = TripRequest.model_validate(raw)
            source = "provided"
            assumptions = ()
        defaults = state.get("preference_defaults", {})
        request_data = request.model_dump(mode="python")
        applied: list[str] = []
        for key, value in defaults.items():
            if key in request_data and request_data[key] is None:
                request_data[key] = value
                applied.append(key)
        request = TripRequest.model_validate(request_data)
        return {
            "status": WorkflowStatus.RUNNING.value,
            "phase": "requirement",
            "requirements": _dump(request),
            "requirement_source": source,
            "requirement_assumptions": assumptions,
            "applied_preference_keys": tuple(applied),
            "revision_count": 0,
            "warnings": (),
        }

    def confirm_requirements(state: WorkflowState) -> WorkflowState:
        current = TripRequest.model_validate(state["requirements"])
        request = ConfirmationRequest(
            kind="requirements",
            title="Confirm trip requirements",
            summary=current.model_dump_json(),
            requires_explicit_choice=True,
        )
        decision = ConfirmationDecision.model_validate(interrupt(request.model_dump(mode="json")))
        if decision.decision == "reject":
            return {"status": WorkflowStatus.REJECTED.value, "phase": "requirements_rejected"}
        confirmed = decision.requirements or current
        missing = _required_trip_fields(confirmed)
        if missing:
            return {
                "status": WorkflowStatus.PARTIAL.value,
                "phase": "requirements_incomplete",
                "requirements": _dump(confirmed),
                "warnings": (f"Missing explicitly confirmed fields: {', '.join(missing)}",),
            }
        return {
            "status": WorkflowStatus.RUNNING.value,
            "phase": "requirements_confirmed",
            "requirements": _dump(confirmed),
        }

    async def resolve_subject(state: WorkflowState) -> WorkflowState:
        request = TripRequest.model_validate(state["requirements"])
        assert request.anime_query is not None
        raw = await tools.call(
            "search_anime_subjects", {"query": request.anime_query, "limit": 5}
        )
        result = SubjectSearchResult.model_validate(raw)
        if not result.candidates:
            return {
                "status": WorkflowStatus.PARTIAL.value,
                "phase": "subject_not_found",
                "warnings": ("No Bangumi subject candidate was found; nothing was guessed.",),
            }
        return {
            "phase": "resolve_subject",
            "subject_candidates": tuple(_dump(item) for item in result.candidates),
        }

    async def confirm_subject(state: WorkflowState) -> WorkflowState:
        candidates = tuple(state["subject_candidates"])
        request = ConfirmationRequest(
            kind="subject",
            title="Confirm the matched work",
            summary="; ".join(
                f"{item['subject_id']}: {item.get('name_cn') or item['name']}"
                for item in candidates
            ),
            requires_explicit_choice=True,
        )
        decision = ConfirmationDecision.model_validate(interrupt(request.model_dump(mode="json")))
        if decision.decision == "reject":
            return {"status": WorkflowStatus.REJECTED.value, "phase": "subject_rejected"}
        candidate_ids = {cast(str, item["subject_id"]) for item in candidates}
        selected = decision.selected_subject_id
        if selected not in candidate_ids:
            return {
                "status": WorkflowStatus.PARTIAL.value,
                "phase": "subject_confirmation_invalid",
                "warnings": ("A returned Bangumi candidate must be explicitly selected.",),
            }
        raw = await tools.call("get_anime_subject", {"subject_id": selected})
        confirmed = ConfirmedSubject.model_validate(raw)
        return {"phase": "subject_confirmed", "confirmed_subject": _dump(confirmed)}

    async def fetch_points(state: WorkflowState) -> WorkflowState:
        if fail_fetch:
            return {
                "status": WorkflowStatus.PARTIAL.value,
                "phase": "fetch_points_partial",
                "warnings": (
                    "Pilgrimage point Provider was unavailable; no points were invented.",
                ),
            }
        subject = ConfirmedSubject.model_validate(state["confirmed_subject"])
        try:
            raw = await tools.call(
                "fetch_pilgrimage_points",
                _dump(PilgrimagePointQuery(subject_id=subject.subject_id, provider="anitabi")),
            )
        except Exception:
            return {
                "status": WorkflowStatus.PARTIAL.value,
                "phase": "fetch_points_partial",
                "warnings": (
                    "Pilgrimage point Provider was unavailable; confirmed subject data was "
                    "preserved and no points were invented.",
                ),
            }
        result = PilgrimagePointResult.model_validate(raw)
        return {"phase": "fetch_points", "point_result": _dump(result)}

    def build_route_a_node(state: WorkflowState) -> WorkflowState:
        subject = ConfirmedSubject.model_validate(state["confirmed_subject"])
        route = build_route_a(
            PilgrimagePointResult.model_validate(state["point_result"]),
            subject_id=subject.subject_id,
        )
        if not route.points:
            return {
                "status": WorkflowStatus.PARTIAL.value,
                "phase": "route_a_empty",
                "warnings": (*state.get("warnings", ()), *route.warnings, "Route A is empty."),
            }
        return {
            "phase": "build_route_a",
            "route_a": _dump(route),
            "warnings": (*state.get("warnings", ()), *route.warnings),
        }

    async def access_planner(state: WorkflowState) -> WorkflowState:
        request = TripRequest.model_validate(state["requirements"])
        route_a = RouteA.model_validate(state["route_a"])
        geocoded: GeoCoordinate | None = None
        assert request.origin is not None
        assert request.destination is not None
        try:
            raw = await tools.call(
                "geocode_place", {"text": request.destination, "language": "ja", "limit": 3}
            )
            places = PlaceSearchResult.model_validate(raw)
            if places.candidates:
                geocoded = places.candidates[0].coordinate
        except (NotImplementedError, ValueError):
            geocoded = None
        options = build_planning_options(request, route_a, geocoded_base=geocoded)
        flight_warning: tuple[str, ...] = ()
        if request.origin_iata and request.destination_iata:
            try:
                assert request.start_date is not None
                assert request.end_date is not None
                inbound_raw = await tools.call(
                    "search_flight_options",
                    _dump(
                        FlightSearchQuery(
                            departure_id=request.origin_iata,
                            arrival_id=request.destination_iata,
                            outbound_date=request.start_date,
                            adults=request.adults,
                            cabin_class=request.cabin_class,
                            currency=request.currency,
                        )
                    ),
                )
                outbound_raw = await tools.call(
                    "search_flight_options",
                    _dump(
                        FlightSearchQuery(
                            departure_id=request.destination_iata,
                            arrival_id=request.origin_iata,
                            outbound_date=request.end_date,
                            adults=request.adults,
                            cabin_class=request.cabin_class,
                            currency=request.currency,
                        )
                    ),
                )
                options = with_flight_options(
                    options,
                    FlightSearchResult.model_validate(inbound_raw),
                    FlightSearchResult.model_validate(outbound_raw),
                    origin=request.origin,
                    destination=request.destination,
                )
            except Exception:  # MCP errors degrade to explicit manual choices.
                flight_warning = (
                    "Flight search was unavailable; manual access remains selectable "
                    "and prices are unknown.",
                )
        return {
            "phase": "access_planner",
            "planning_options": _dump(options),
            "warnings": (*state.get("warnings", ()), *flight_warning),
        }

    def confirm_access(state: WorkflowState) -> WorkflowState:
        options = PlanningOptions.model_validate(state["planning_options"])
        request = ConfirmationRequest(
            kind="access_and_base",
            title="Confirm access and base",
            summary=(
                f"{len(options.access_options)} access candidates; "
                f"{len(options.base_candidates)} base candidates; no booking or payment action."
            ),
            requires_explicit_choice=True,
        )
        decision = ConfirmationDecision.model_validate(interrupt(request.model_dump(mode="json")))
        if decision.decision == "reject":
            return {"status": WorkflowStatus.REJECTED.value, "phase": "access_rejected"}
        inbound_option_id = decision.inbound_option_id
        outbound_option_id = decision.outbound_option_id
        base_id = decision.base_id
        if inbound_option_id is None or outbound_option_id is None or base_id is None:
            return {
                "status": WorkflowStatus.PARTIAL.value,
                "phase": "access_confirmation_invalid",
                "warnings": ("Inbound, outbound and base choices require explicit confirmation.",),
            }
        by_base = {base.base_id for base in options.base_candidates}
        if base_id not in by_base:
            return {
                "status": WorkflowStatus.PARTIAL.value,
                "phase": "base_confirmation_invalid",
                "warnings": ("The confirmed base is not one of the presented candidates.",),
            }
        confirmed_access(
            options,
            inbound_option_id=inbound_option_id,
            outbound_option_id=outbound_option_id,
        )
        confirmed_requirements = decision.requirements or TripRequest.model_validate(
            state["requirements"]
        )
        return {
            "phase": "access_confirmed",
            "inbound_option_id": inbound_option_id,
            "outbound_option_id": outbound_option_id,
            "base_id": base_id,
            "requirements": _dump(confirmed_requirements),
        }

    async def retrieve_knowledge(state: WorkflowState) -> WorkflowState:
        try:
            result = await knowledge_boundary.retrieve(
                owner_user_id=state["owner_user_id"],
                trip_id=UUID(state["trip_id"]),
                request=TripRequest.model_validate(state["requirements"]),
                subject=ConfirmedSubject.model_validate(state["confirmed_subject"]),
            )
            warnings: tuple[str, ...] = ()
        except Exception:  # Retrieval failure must degrade to unknown, never invented evidence.
            result = KnowledgeSearchResult(status="insufficient_evidence", evidence=())
            warnings = (
                "Project knowledge retrieval was unavailable; visit rules remain unknown.",
            )
        return {
            "phase": "retrieve_knowledge",
            "knowledge": _dump(result),
            "warnings": (*state.get("warnings", ()), *warnings),
        }

    async def planner(state: WorkflowState) -> WorkflowState:
        request = TripRequest.model_validate(state["requirements"])
        route_a = RouteA.model_validate(state["route_a"])
        options = PlanningOptions.model_validate(state["planning_options"])
        base_by_id = {base.base_id: base for base in options.base_candidates}
        base = base_by_id[state["base_id"]]
        access = confirmed_access(
            options,
            inbound_option_id=state["inbound_option_id"],
            outbound_option_id=state["outbound_option_id"],
        )
        assert request.start_date is not None
        assert request.end_date is not None
        weather: WeatherForecastResult | None = None
        weather_warning: tuple[str, ...] = ()
        try:
            raw_weather = await tools.call(
                "get_weather_forecast",
                {
                    "coordinate": base.coordinate.model_dump(mode="json"),
                    "start_date": request.start_date.isoformat(),
                    "end_date": request.end_date.isoformat(),
                },
            )
            weather = WeatherForecastResult.model_validate(raw_weather)
        except (NotImplementedError, RuntimeError, ValueError):
            weather_warning = (
                "Weather is unavailable; no weather condition was invented and the plan "
                "must be reconfirmed before departure.",
            )
        effective_walking = walking_limit(request)
        if weather and weather.available and any(
            (window.precipitation_probability_max or 0) >= 70
            for window in weather.windows
        ):
            effective_walking *= 0.7
            weather_warning = (
                "Rain probability reaches 70%; the deterministic walking cap was reduced "
                "by 30% for a conservative itinerary.",
            )
        constraints = PlanningConstraints(
            start_date=request.start_date,
            end_date=request.end_date,
            arrival_at=access.inbound.arrival_at,
            departure_at=access.outbound.departure_at,
            max_walking_meters_per_day=effective_walking,
            must_visit_point_ids=frozenset(request.must_visit_point_ids),
            excluded_point_ids=frozenset(request.excluded_point_ids),
        )
        candidate_route, matrix_omitted = matrix_candidate_route(
            route_a,
            base,
            must_visit_point_ids=constraints.must_visit_point_ids,
            excluded_point_ids=constraints.excluded_point_ids,
        )
        coordinates = [base.coordinate]
        coordinates.extend(
            GeoCoordinate(latitude=point.latitude, longitude=point.longitude)
            for point in candidate_route.points
        )
        try:
            raw_matrix = await tools.call(
                "get_route_matrix",
                {
                    "coordinates": [item.model_dump(mode="json") for item in coordinates],
                    "profile": "foot-walking",
                },
            )
            matrix = RouteMatrix.model_validate(raw_matrix)
        except (NotImplementedError, RuntimeError, ValueError):
            matrix = haversine_matrix(tuple(coordinates))
            weather_warning = (
                *weather_warning,
                "ORS matrix was unavailable; Route B uses a labelled straight-line estimate.",
            )
        candidate_plan = build_route_b(
            route_a=candidate_route,
            base=base,
            matrix=matrix,
            constraints=constraints,
            access=access,
        )
        plan = restore_full_route_a_membership(
            candidate_plan,
            route_a,
            matrix_omitted_ids=matrix_omitted,
            excluded_point_ids=constraints.excluded_point_ids,
        )
        update: WorkflowState = {
            "phase": "pilgrimage_planner",
            "route_b": _dump(plan),
            "plan_day_hashes": _day_hashes(plan),
            "effective_walking_limit": effective_walking,
            "warnings": (*state.get("warnings", ()), *weather_warning),
        }
        if weather is not None:
            update["weather"] = _dump(weather)
        return update

    def validator(state: WorkflowState) -> WorkflowState:
        request = TripRequest.model_validate(state["requirements"])
        plan = RouteBPlan.model_validate(state["route_b"])
        assert request.start_date is not None
        assert request.end_date is not None
        assert plan.access is not None
        constraints = PlanningConstraints(
            start_date=request.start_date,
            end_date=request.end_date,
            arrival_at=plan.access.inbound.arrival_at,
            departure_at=plan.access.outbound.departure_at,
            max_walking_meters_per_day=state.get(
                "effective_walking_limit", walking_limit(request)
            ),
            must_visit_point_ids=frozenset(request.must_visit_point_ids),
            excluded_point_ids=frozenset(request.excluded_point_ids),
        )
        report = validate_route_b(plan, constraints)
        issues = list(report.issues)
        if inject_first_violation and state.get("revision_count", 0) == 0:
            issues.append(
                ValidationIssue(
                    code="injected_test_violation",
                    detail="A deterministic test violation requires one bounded replan.",
                )
            )
        return {
            "phase": "deterministic_validator",
            "validation_issues": tuple(_dump(issue) for issue in issues),
            "deterministic_violations": tuple(issue.code for issue in issues),
        }

    async def review(state: WorkflowState) -> WorkflowState:
        snapshot = context_builder.build(
            node="reviewer",
            owner_user_id=state["owner_user_id"],
            thread_id=state["thread_id"],
            trip_id=state["trip_id"],
            facts=(
                f"revision_count={state.get('revision_count', 0)}",
                f"violation_count={len(state.get('deterministic_violations', ()))}",
            ),
            route_a_point_ids=tuple(
                str(point.id) for point in RouteA.model_validate(state["route_a"]).points
            ),
            relevant_knowledge_ids=tuple(
                item.evidence_id
                for item in KnowledgeSearchResult.model_validate(
                    state.get(
                        "knowledge",
                        {"status": "insufficient_evidence", "evidence": []},
                    )
                ).evidence
            ),
        )
        output = await reviewer_boundary.review(
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
                "warnings": (*state.get("warnings", ()), "The three-revision limit was reached."),
                "reviewer_explanation": output.explanation,
                "context_snapshot_id": snapshot.snapshot_id,
            }
        return {
            "phase": "reviewer",
            "next_action": next_action,
            "reviewer_explanation": output.explanation,
            "reviewer_target_day": output.target_day or 2,
            "context_snapshot_id": snapshot.snapshot_id,
        }

    def replan(state: WorkflowState) -> WorkflowState:
        revision = state.get("revision_count", 0) + 1
        plan = RouteBPlan.model_validate(state["route_b"])
        target_day = state.get("reviewer_target_day", 2)
        plan, replan_warnings = replan_local_walking(
            plan,
            RouteA.model_validate(state["route_a"]),
            PlanModification(
                target_day=target_day,
                walking_reduction_percent=30,
                reason=state.get(
                    "reviewer_explanation", "Reviewer requested a local replan."
                ),
            ),
        )
        hashes = list(state["plan_day_hashes"])
        target_index = target_day - 1
        if len(hashes) > target_index:
            hashes[target_index] = sha256(
                f"{plan.days[target_index].model_dump_json()}|revision={revision}".encode()
            ).hexdigest()[:16]
        return {
            "phase": "replan",
            "revision_count": revision,
            "route_b": _dump(plan),
            "plan_day_hashes": tuple(hashes),
            "warnings": (*state.get("warnings", ()), *replan_warnings),
        }

    def present(state: WorkflowState) -> WorkflowState:
        return {"status": WorkflowStatus.COMPLETE.value, "phase": "present"}

    def continue_route(state: WorkflowState) -> RouteName:
        return (
            "stop"
            if state.get("status") in {WorkflowStatus.REJECTED.value, WorkflowStatus.PARTIAL.value}
            else "continue"
        )

    def review_route(state: WorkflowState) -> RouteName:
        return cast(RouteName, state["next_action"])

    graph: StateGraph[WorkflowState, None, WorkflowState, WorkflowState] = StateGraph(WorkflowState)
    graph.add_node("requirement", requirement)
    graph.add_node("confirm_requirements", confirm_requirements)
    graph.add_node("resolve_subject", resolve_subject)
    graph.add_node("confirm_subject", confirm_subject)
    graph.add_node("fetch_points", fetch_points)
    graph.add_node("build_route_a", build_route_a_node)
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
        "confirm_requirements", continue_route, {"continue": "resolve_subject", "stop": END}
    )
    graph.add_conditional_edges(
        "resolve_subject", continue_route, {"continue": "confirm_subject", "stop": END}
    )
    graph.add_conditional_edges(
        "confirm_subject", continue_route, {"continue": "fetch_points", "stop": END}
    )
    graph.add_conditional_edges(
        "fetch_points", continue_route, {"continue": "build_route_a", "stop": END}
    )
    graph.add_conditional_edges(
        "build_route_a", continue_route, {"continue": "access_planner", "stop": END}
    )
    graph.add_edge("access_planner", "confirm_access_and_base")
    graph.add_conditional_edges(
        "confirm_access_and_base",
        continue_route,
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
