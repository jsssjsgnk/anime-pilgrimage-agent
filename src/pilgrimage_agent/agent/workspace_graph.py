"""Authoritative LangGraph runtime for the multi-work pilgrimage workspace."""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime
from typing import Any, Literal, TypedDict, cast
from uuid import UUID, uuid4

from langgraph.checkpoint.base import BaseCheckpointSaver
from langgraph.graph import END, START, StateGraph
from langgraph.graph.state import CompiledStateGraph
from langgraph.types import interrupt

from pilgrimage_agent.agent.llm import ReviewerBoundary, WorkspaceReplannerBoundary
from pilgrimage_agent.agent.schemas import ReviewerInput, WorkspaceReplannerInput
from pilgrimage_agent.agent.workspace import (
    ConfirmWorkspaceSubjectsRequest,
    PlanWorkspaceRequest,
    WorkspaceAgent,
    WorkspaceReviewerAssessment,
    WorkspaceStartRequest,
    WorkspaceState,
)
from pilgrimage_agent.domain.workspace import (
    AgentHandoff,
    AgentRole,
    ContextFact,
    EntityRef,
)


class WorkspaceGraphState(TypedDict, total=False):
    start_request: dict[str, object]
    requirements: dict[str, object]
    workspace: dict[str, object]
    subject_confirmation: dict[str, object]
    plan_request: dict[str, object]
    phase: str
    run_id: str
    active_handoff_id: str
    access_handoff_id: str
    place_facts_handoff_id: str
    weather_handoff_id: str
    knowledge_handoff_id: str
    next_action: str
    revision_count: int


WorkspaceGraph = CompiledStateGraph[
    WorkspaceGraphState, None, WorkspaceGraphState, WorkspaceGraphState
]


def _dump(model: Any) -> dict[str, object]:
    return cast(dict[str, object], model.model_dump(mode="json"))


def _workspace(state: WorkspaceGraphState) -> WorkspaceState:
    return WorkspaceState.model_validate(state["workspace"])


def _replace_handoff(
    workspace: WorkspaceState, handoff: AgentHandoff
) -> WorkspaceState:
    return workspace.model_copy(
        update={
            "handoffs": tuple(
                handoff if item.handoff_id == handoff.handoff_id else item
                for item in workspace.handoffs
            )
        }
    )


def _handoff_time(handoff: AgentHandoff, *, terminal: bool = False) -> datetime:
    """Return a wall-clock timestamp that preserves the handoff lifecycle order."""

    bounds = [handoff.created_at, datetime.now(UTC)]
    if terminal and handoff.started_at is not None:
        bounds.append(handoff.started_at)
    return max(bounds)


def _new_review_handoff(workspace: WorkspaceState, run_id: UUID) -> AgentHandoff:
    contexts = tuple(
        item for item in workspace.contexts if item.run_id == run_id
    ) or workspace.contexts[-max(1, len(workspace.planning_strategies)) :]
    return AgentHandoff(
        run_id=run_id,
        sender=AgentRole.VALIDATOR,
        receiver=AgentRole.REVIEWER,
        task_type="review_normalized_plan_quality",
        goal="Review priorities and omissions without overriding deterministic validation.",
        input_refs=tuple(
            EntityRef(entity_type="role_context", entity_id=str(item.context_id))
            for item in contexts
        ),
        expected_output_schema="WorkspaceReviewerAssessment[]",
        status="pending",
        created_at=datetime.now(UTC),
    )


def build_workspace_graph(
    agent: WorkspaceAgent,
    checkpointer: BaseCheckpointSaver[Any] | None = None,
    *,
    reviewer: ReviewerBoundary | None = None,
    replanner: WorkspaceReplannerBoundary | None = None,
    reviewer_source: Literal["llm", "fixture"] = "llm",
    max_revisions: int = 2,
) -> WorkspaceGraph:
    """Compile the sole product graph with durable subject and plan interrupts."""

    if not 0 <= max_revisions <= 3:
        raise ValueError("max_revisions must be between zero and three")

    async def load_context(state: WorkspaceGraphState) -> WorkspaceGraphState:
        request = WorkspaceStartRequest.model_validate(state["start_request"])
        return {
            "phase": "load_workspace_context",
            "run_id": str(uuid4()),
            "revision_count": 0,
            "start_request": _dump(request),
        }

    async def requirement_agent(state: WorkspaceGraphState) -> WorkspaceGraphState:
        request = WorkspaceStartRequest.model_validate(state["start_request"])
        requirements = await agent.extract_requirements(request)
        return {"phase": "requirement_agent", "requirements": _dump(requirements)}

    async def subject_agent(state: WorkspaceGraphState) -> WorkspaceGraphState:
        raw = dict(state["start_request"])
        raw["requirements"] = state["requirements"]
        workspace = await agent.resolve_subjects(WorkspaceStartRequest.model_validate(raw))
        return {"phase": "subject_agent", "workspace": _dump(workspace)}

    def confirm_subjects(state: WorkspaceGraphState) -> WorkspaceGraphState:
        workspace = _workspace(state)
        payload = interrupt(
            {
                "kind": "subjects",
                "trip_id": str(workspace.trip_id),
                "state_version": workspace.state_version,
                "candidate_group_count": len(workspace.subject_groups),
            }
        )
        request = ConfirmWorkspaceSubjectsRequest.model_validate(payload)
        return {"phase": "confirm_subjects", "subject_confirmation": _dump(request)}

    async def point_agent(state: WorkspaceGraphState) -> WorkspaceGraphState:
        workspace = await agent.collect_subject_evidence(
            _workspace(state),
            ConfirmWorkspaceSubjectsRequest.model_validate(state["subject_confirmation"]),
        )
        return {"phase": "anitabi_point_agent", "workspace": _dump(workspace)}

    def place_curator(state: WorkspaceGraphState) -> WorkspaceGraphState:
        workspace = agent.curate_places(_workspace(state))
        return {"phase": "place_curator", "workspace": _dump(workspace)}

    async def travel_area_builder(state: WorkspaceGraphState) -> WorkspaceGraphState:
        workspace = agent.build_travel_areas(_workspace(state))
        workspace = await agent.calibrate_travel_areas(workspace)
        return {"phase": "travel_area_builder", "workspace": _dump(workspace)}

    def prepare_access_agent(state: WorkspaceGraphState) -> WorkspaceGraphState:
        workspace = _workspace(state)
        handoff = AgentHandoff(
            run_id=UUID(state["run_id"]),
            sender=AgentRole.TRAVEL_AREA_BUILDER,
            receiver=AgentRole.ACCESS,
            task_type="collect_access_candidates",
            goal="Collect read-only access candidates for explicit user confirmation.",
            input_refs=tuple(
                EntityRef(entity_type="area", entity_id=str(item.area_id))
                for item in workspace.areas
            ),
            expected_output_schema="AccessOption[] + ProviderSnapshot[]",
            status="pending",
            created_at=datetime.now(UTC),
        )
        workspace = workspace.model_copy(
            update={"handoffs": (*workspace.handoffs, handoff)}
        )
        return {
            "phase": "access_handoff_pending",
            "access_handoff_id": str(handoff.handoff_id),
            "workspace": _dump(workspace),
        }

    def start_access_agent(state: WorkspaceGraphState) -> WorkspaceGraphState:
        workspace = _workspace(state)
        handoff_id = UUID(state["access_handoff_id"])
        handoff = next(item for item in workspace.handoffs if item.handoff_id == handoff_id)
        workspace = _replace_handoff(
            workspace,
            handoff.model_copy(
                update={"status": "running", "started_at": _handoff_time(handoff)}
            ),
        )
        return {"phase": "access_handoff_running", "workspace": _dump(workspace)}

    async def access_agent(state: WorkspaceGraphState) -> WorkspaceGraphState:
        workspace = await agent.collect_access_candidates(_workspace(state))
        handoff_id = UUID(state["access_handoff_id"])
        handoff = next(item for item in workspace.handoffs if item.handoff_id == handoff_id)
        result_refs = (
            *(
                EntityRef(entity_type="access_candidate", entity_id=item.option_id)
                for item in workspace.access_candidates
            ),
            *(
                EntityRef(entity_type="provider_snapshot", entity_id=str(item.snapshot_id))
                for item in workspace.provider_snapshots
                if item.kind in {"flight", "transit"}
            ),
        )
        status: Literal["completed", "partial"] = (
            "completed" if workspace.access_candidates else "partial"
        )
        warning = (
            None
            if workspace.access_candidates
            else "No access candidate was available; no schedule or fare was invented."
        )
        workspace = _replace_handoff(
            workspace,
            handoff.model_copy(
                update={
                    "status": status,
                    "result_refs": result_refs,
                    "warnings": (warning,) if warning else (),
                    "completed_at": _handoff_time(handoff, terminal=True),
                }
            ),
        )
        return {"phase": "access_agent", "workspace": _dump(workspace)}

    def confirm_access_and_base(state: WorkspaceGraphState) -> WorkspaceGraphState:
        workspace = _workspace(state)
        payload = interrupt(
            {
                "kind": "access_and_base",
                "trip_id": str(workspace.trip_id),
                "state_version": workspace.state_version,
                "base_ids": tuple(item.base_id for item in workspace.base_candidates),
            }
        )
        request = PlanWorkspaceRequest.model_validate(payload)
        return {
            "phase": "confirm_access_and_base",
            "plan_request": _dump(request),
        }

    def prepare_live_constraints(state: WorkspaceGraphState) -> WorkspaceGraphState:
        workspace = _workspace(state)
        now = datetime.now(UTC)
        place_handoff = AgentHandoff(
            run_id=UUID(state["run_id"]),
            sender=AgentRole.BASE,
            receiver=AgentRole.PLACE_FACTS,
            task_type="collect_current_place_facts",
            goal="Match bounded place facts without treating uncertain names as constraints.",
            input_refs=tuple(
                EntityRef(entity_type="visit_place", entity_id=str(item.place_id))
                for item in workspace.places
            ),
            expected_output_schema="PlaceFact[] + ProviderSnapshot[]",
            status="pending",
            created_at=now,
        )
        weather_handoff = AgentHandoff(
            run_id=UUID(state["run_id"]),
            sender=AgentRole.BASE,
            receiver=AgentRole.WEATHER,
            task_type="collect_weather_constraints",
            goal="Collect a bounded forecast or an explicit unknown result.",
            input_refs=(
                EntityRef(
                    entity_type="base",
                    entity_id=PlanWorkspaceRequest.model_validate(
                        state["plan_request"]
                    ).base_id,
                ),
            ),
            expected_output_schema="WeatherForecastResult + ProviderSnapshot",
            status="pending",
            created_at=now,
        )
        knowledge_handoff = AgentHandoff(
            run_id=UUID(state["run_id"]),
            sender=AgentRole.BASE,
            receiver=AgentRole.KNOWLEDGE,
            task_type="retrieve_scoped_knowledge",
            goal=(
                "Retrieve scoped evidence and propose cited rules without activating "
                "unconfirmed constraints."
            ),
            input_refs=tuple(
                EntityRef(
                    entity_type="subject", entity_id=item.subject.subject_id
                )
                for item in workspace.confirmed_subjects
            ),
            expected_output_schema="RetrievedEvidence[] + DerivedKnowledgeRule[]",
            status="pending",
            created_at=now,
        )
        workspace = workspace.model_copy(
            update={
                "handoffs": (
                    *workspace.handoffs,
                    place_handoff,
                    weather_handoff,
                    knowledge_handoff,
                )
            }
        )
        return {
            "phase": "live_constraint_handoffs_pending",
            "place_facts_handoff_id": str(place_handoff.handoff_id),
            "weather_handoff_id": str(weather_handoff.handoff_id),
            "knowledge_handoff_id": str(knowledge_handoff.handoff_id),
            "workspace": _dump(workspace),
        }

    def start_live_constraints(state: WorkspaceGraphState) -> WorkspaceGraphState:
        workspace = _workspace(state)
        for key in (
            "place_facts_handoff_id",
            "weather_handoff_id",
            "knowledge_handoff_id",
        ):
            handoff_id = UUID(state[key])
            handoff = next(
                item for item in workspace.handoffs if item.handoff_id == handoff_id
            )
            workspace = _replace_handoff(
                workspace,
                handoff.model_copy(
                    update={"status": "running", "started_at": _handoff_time(handoff)}
                ),
            )
        return {"phase": "live_constraint_handoffs_running", "workspace": _dump(workspace)}

    async def place_facts_agent(state: WorkspaceGraphState) -> WorkspaceGraphState:
        workspace = await agent.collect_live_constraints(
            _workspace(state), PlanWorkspaceRequest.model_validate(state["plan_request"])
        )
        handoff_id = UUID(state["place_facts_handoff_id"])
        handoff = next(item for item in workspace.handoffs if item.handoff_id == handoff_id)
        result_refs = tuple(
            EntityRef(entity_type="place_fact", entity_id=str(place_id))
            for place_id in workspace.place_facts
        )
        status: Literal["completed", "partial"] = (
            "completed" if len(workspace.place_facts) == len(workspace.places) else "partial"
        )
        warning = (
            None
            if status == "completed"
            else "Some current place facts remain unmatched and were not used as hard facts."
        )
        workspace = _replace_handoff(
            workspace,
            handoff.model_copy(
                update={
                    "status": status,
                    "result_refs": result_refs,
                    "warnings": (warning,) if warning else (),
                    "completed_at": _handoff_time(handoff, terminal=True),
                }
            ),
        )
        return {"phase": "place_facts_agent", "workspace": _dump(workspace)}

    async def weather_agent(state: WorkspaceGraphState) -> WorkspaceGraphState:
        workspace = _workspace(state)
        handoff_id = UUID(state["weather_handoff_id"])
        handoff = next(item for item in workspace.handoffs if item.handoff_id == handoff_id)
        forecast = workspace.weather_forecast
        status: Literal["completed", "partial"] = (
            "completed" if forecast is not None and forecast.available else "partial"
        )
        warning = (
            None
            if status == "completed"
            else "Weather is outside the reliable window or unavailable; refresh before travel."
        )
        refs = (
            tuple(
                EntityRef(entity_type="weather_window", entity_id=item.date.isoformat())
                for item in forecast.windows
            )
            if forecast is not None
            else ()
        )
        workspace = _replace_handoff(
            workspace,
            handoff.model_copy(
                update={
                    "status": status,
                    "result_refs": refs,
                    "warnings": (warning,) if warning else (),
                    "completed_at": _handoff_time(handoff, terminal=True),
                }
            ),
        )
        return {"phase": "weather_agent", "workspace": _dump(workspace)}

    async def knowledge_agent(state: WorkspaceGraphState) -> WorkspaceGraphState:
        workspace = _workspace(state)
        handoff_id = UUID(state["knowledge_handoff_id"])
        handoff = next(item for item in workspace.handoffs if item.handoff_id == handoff_id)
        result_refs = (
            *(
                EntityRef(entity_type="knowledge_evidence", entity_id=item.evidence_id)
                for item in workspace.knowledge_evidence
            ),
            *(
                EntityRef(entity_type="knowledge_rule", entity_id=str(item.rule_id))
                for item in workspace.knowledge_rules
            ),
        )
        status: Literal["completed", "partial"] = (
            "completed" if workspace.knowledge_evidence else "partial"
        )
        warning = (
            None
            if status == "completed"
            else "No scoped knowledge evidence was available; no rule was invented."
        )
        workspace = _replace_handoff(
            workspace,
            handoff.model_copy(
                update={
                    "status": status,
                    "result_refs": result_refs,
                    "warnings": (warning,) if warning else (),
                    "completed_at": _handoff_time(handoff, terminal=True),
                }
            ),
        )
        return {"phase": "knowledge_agent", "workspace": _dump(workspace)}

    def itinerary_planner(state: WorkspaceGraphState) -> WorkspaceGraphState:
        workspace = agent.plan(
            _workspace(state), PlanWorkspaceRequest.model_validate(state["plan_request"])
        )
        return {"phase": "itinerary_planner", "workspace": _dump(workspace)}

    def deterministic_validator(state: WorkspaceGraphState) -> WorkspaceGraphState:
        workspace = _workspace(state)
        has_issues = any(
            item.validation_issues
            for item in workspace.itineraries[: len(workspace.planning_strategies)]
        )
        return {
            "phase": "deterministic_validator",
            "next_action": "review",
            "workspace": _dump(workspace),
            **({"next_action": "review_with_violations"} if has_issues else {}),
        }

    def prepare_reviewer(state: WorkspaceGraphState) -> WorkspaceGraphState:
        workspace = _workspace(state)
        run_id = UUID(state["run_id"])
        handoff = _new_review_handoff(workspace, run_id)
        workspace = workspace.model_copy(
            update={"handoffs": (*workspace.handoffs, handoff)}
        )
        return {
            "phase": "reviewer_handoff_pending",
            "active_handoff_id": str(handoff.handoff_id),
            "workspace": _dump(workspace),
        }

    def start_reviewer(state: WorkspaceGraphState) -> WorkspaceGraphState:
        workspace = _workspace(state)
        handoff_id = UUID(state["active_handoff_id"])
        handoff = next(item for item in workspace.handoffs if item.handoff_id == handoff_id)
        workspace = _replace_handoff(
            workspace,
            handoff.model_copy(
                update={"status": "running", "started_at": _handoff_time(handoff)}
            ),
        )
        return {"phase": "reviewer_handoff_running", "workspace": _dump(workspace)}

    async def reviewer_agent(state: WorkspaceGraphState) -> WorkspaceGraphState:
        workspace = _workspace(state)
        handoff_id = UUID(state["active_handoff_id"])
        handoff = next(item for item in workspace.handoffs if item.handoff_id == handoff_id)
        active = workspace.itineraries[: len(workspace.planning_strategies)]
        assessments: list[WorkspaceReviewerAssessment] = []
        next_action = "present"
        warning: str | None = None
        if reviewer is None:
            warning = (
                "LLM Reviewer is not configured; deterministic validation "
                "remains authoritative."
            )
            for itinerary in active:
                assessments.append(
                    WorkspaceReviewerAssessment(
                        itinerary_id=itinerary.itinerary_id,
                        itinerary_version=itinerary.version,
                        action="unavailable",
                        explanation=warning,
                        source="unavailable",
                        created_at=datetime.now(UTC),
                    )
                )
            status: Literal["completed", "partial", "failed"] = "partial"
        else:
            try:
                review_inputs = tuple(
                    ReviewerInput(
                        context_snapshot_id=str(
                            next(
                                item.context_id
                                for item in reversed(workspace.contexts)
                                if item.refs
                                and item.refs[0].entity_id == str(itinerary.itinerary_id)
                            )
                        ),
                        deterministic_violations=tuple(
                            issue.code for issue in itinerary.validation_issues
                        ),
                        revision_count=state.get("revision_count", 0),
                    )
                    for itinerary in active
                )
                outputs = await asyncio.gather(
                    *(reviewer.review(review_input) for review_input in review_inputs)
                )
                for itinerary, output in zip(active, outputs, strict=True):
                    assessments.append(
                        WorkspaceReviewerAssessment(
                            itinerary_id=itinerary.itinerary_id,
                            itinerary_version=itinerary.version,
                            action=output.action,
                            target_day=output.target_day,
                            explanation=output.explanation,
                            source=reviewer_source,
                            created_at=datetime.now(UTC),
                        )
                    )
                status = "completed"
                if any(item.action == "revise" for item in assessments):
                    next_action = (
                        "replan"
                        if state.get("revision_count", 0) < max_revisions
                        else "present"
                    )
                    if next_action == "present":
                        warning = "Reviewer revision limit reached; returning a partial plan."
                        status = "partial"
            except Exception:
                warning = "LLM Reviewer failed safely; no review result was fabricated."
                status = "failed"
        finished = handoff.model_copy(
            update={
                "status": status,
                "result_refs": tuple(
                    EntityRef(
                        entity_type="reviewer_assessment",
                        entity_id=f"{item.itinerary_id}:{item.itinerary_version}",
                    )
                    for item in assessments
                ),
                "warnings": (warning,) if warning and status != "failed" else (),
                "safe_error": warning if status == "failed" else None,
                "completed_at": _handoff_time(handoff, terminal=True),
            }
        )
        workspace = _replace_handoff(workspace, finished)
        workspace = workspace.model_copy(
            update={
                "reviewer_assessments": (*workspace.reviewer_assessments, *assessments),
                "warnings": (*workspace.warnings, *((warning,) if warning else ())),
            }
        )
        return {
            "phase": "reviewer_agent",
            "next_action": next_action,
            "workspace": _dump(workspace),
        }

    def review_route(state: WorkspaceGraphState) -> str:
        return state.get("next_action", "present")

    async def bounded_replanner(state: WorkspaceGraphState) -> WorkspaceGraphState:
        workspace = _workspace(state)
        assessment = next(
            (
                item
                for item in reversed(workspace.reviewer_assessments)
                if item.action == "revise" and item.target_day is not None
            ),
            None,
        )
        now = datetime.now(UTC)
        handoff = AgentHandoff(
            run_id=UUID(state["run_id"]),
            sender=AgentRole.REVIEWER,
            receiver=AgentRole.REPLANNER,
            task_type="replan_affected_day",
            goal="Revise only the reviewer-targeted day and preserve stable days.",
            input_refs=tuple(
                EntityRef(
                    entity_type="itinerary",
                    entity_id=str(item.itinerary_id),
                    version=item.version,
                )
                for item in workspace.itineraries[: len(workspace.planning_strategies)]
            ),
            expected_output_schema="PlanVersionDiff",
            status="running",
            created_at=now,
            started_at=now,
        )
        warning: str | None = None
        status: Literal["completed", "partial", "failed"] = "partial"
        next_action = "present"
        result_workspace = workspace
        if assessment is None:
            warning = "Reviewer requested revision without a target day; no broad rewrite was made."
        elif replanner is None:
            warning = "LLM Replanner is not configured; no revision result was fabricated."
        else:
            target = cast(int, assessment.target_day)
            active = workspace.itineraries[: len(workspace.planning_strategies)]
            violations = tuple(
                issue.code for item in active for issue in item.validation_issues
            )
            stable_days = tuple(
                number
                for number in range(1, len(active[0].days) + 1)
                if number != target
            )
            replan_context = agent.context_builder.build(
                role=AgentRole.REPLANNER,
                run_id=UUID(state["run_id"]),
                facts=(
                    ContextFact(key="target_day", value=target),
                    ContextFact(
                        key="reviewer_explanation",
                        value=assessment.explanation[:1000],
                    ),
                    ContextFact(
                        key="deterministic_violations",
                        value=",".join(violations) or "none",
                    ),
                    ContextFact(
                        key="stable_day_numbers",
                        value=",".join(str(item) for item in stable_days) or "none",
                    ),
                ),
                refs=tuple(
                    EntityRef(
                        entity_type="itinerary",
                        entity_id=str(item.itinerary_id),
                        version=item.version,
                    )
                    for item in active
                ),
            )
            workspace = workspace.model_copy(
                update={"contexts": (*workspace.contexts, replan_context)}
            )
            result_workspace = workspace
            context_id = str(replan_context.context_id)
            try:
                output = await replanner.replan(
                    WorkspaceReplannerInput(
                        context_snapshot_id=context_id,
                        target_day=target,
                        reviewer_explanation=assessment.explanation,
                        deterministic_violations=violations,
                        stable_day_numbers=stable_days,
                        revision_count=state.get("revision_count", 0),
                    )
                )
                if output.target_day != target:
                    warning = "Replanner changed the bounded target day; the output was rejected."
                elif output.action == "stop_partial":
                    warning = output.explanation
                else:
                    result_workspace = agent.replan_target_day(workspace, target)
                    status = "completed"
                    next_action = "review"
            except Exception:
                status = "failed"
                warning = "LLM Replanner failed safely; the existing plan was preserved."
        result_refs = (
            (
                EntityRef(
                    entity_type="plan_diff",
                    entity_id=str(result_workspace.diffs[-1].to_version),
                ),
            )
            if status == "completed" and result_workspace.diffs
            else ()
        )
        handoff = handoff.model_copy(
            update={
                "status": status,
                "result_refs": result_refs,
                "warnings": (warning,) if warning and status != "failed" else (),
                "safe_error": warning if status == "failed" else None,
                "completed_at": _handoff_time(handoff, terminal=True),
            }
        )
        result_workspace = result_workspace.model_copy(
            update={
                "handoffs": (*result_workspace.handoffs, handoff),
                "warnings": (
                    *result_workspace.warnings,
                    *((warning,) if warning else ()),
                ),
            }
        )
        return {
            "phase": "bounded_replanner",
            "revision_count": state.get("revision_count", 0) + 1,
            "next_action": next_action,
            "workspace": _dump(result_workspace),
        }

    def present_workspace(state: WorkspaceGraphState) -> WorkspaceGraphState:
        return {"phase": "present_workspace", "workspace": state["workspace"]}

    graph = StateGraph(WorkspaceGraphState)
    graph.add_node("load_workspace_context", load_context)
    graph.add_node("requirement_agent", requirement_agent)
    graph.add_node("subject_agent", subject_agent)
    graph.add_node("confirm_subjects", confirm_subjects)
    graph.add_node("anitabi_point_agent", point_agent)
    graph.add_node("place_curator", place_curator)
    graph.add_node("travel_area_builder", travel_area_builder)
    graph.add_node("prepare_access_agent", prepare_access_agent)
    graph.add_node("start_access_agent", start_access_agent)
    graph.add_node("access_agent", access_agent)
    graph.add_node("confirm_access_and_base", confirm_access_and_base)
    graph.add_node("prepare_live_constraints", prepare_live_constraints)
    graph.add_node("start_live_constraints", start_live_constraints)
    graph.add_node("place_facts_agent", place_facts_agent)
    graph.add_node("weather_agent", weather_agent)
    graph.add_node("knowledge_agent", knowledge_agent)
    graph.add_node("itinerary_planner", itinerary_planner)
    graph.add_node("deterministic_validator", deterministic_validator)
    graph.add_node("prepare_reviewer", prepare_reviewer)
    graph.add_node("start_reviewer", start_reviewer)
    graph.add_node("reviewer_agent", reviewer_agent)
    graph.add_node("bounded_replanner", bounded_replanner)
    graph.add_node("present_workspace", present_workspace)
    graph.add_edge(START, "load_workspace_context")
    graph.add_edge("load_workspace_context", "requirement_agent")
    graph.add_edge("requirement_agent", "subject_agent")
    graph.add_edge("subject_agent", "confirm_subjects")
    graph.add_edge("confirm_subjects", "anitabi_point_agent")
    graph.add_edge("anitabi_point_agent", "place_curator")
    graph.add_edge("place_curator", "travel_area_builder")
    graph.add_edge("travel_area_builder", "prepare_access_agent")
    graph.add_edge("prepare_access_agent", "start_access_agent")
    graph.add_edge("start_access_agent", "access_agent")
    graph.add_edge("access_agent", "confirm_access_and_base")
    graph.add_edge("confirm_access_and_base", "prepare_live_constraints")
    graph.add_edge("prepare_live_constraints", "start_live_constraints")
    graph.add_edge("start_live_constraints", "place_facts_agent")
    graph.add_edge("place_facts_agent", "weather_agent")
    graph.add_edge("weather_agent", "knowledge_agent")
    graph.add_edge("knowledge_agent", "itinerary_planner")
    graph.add_edge("itinerary_planner", "deterministic_validator")
    graph.add_edge("deterministic_validator", "prepare_reviewer")
    graph.add_edge("prepare_reviewer", "start_reviewer")
    graph.add_edge("start_reviewer", "reviewer_agent")
    graph.add_conditional_edges(
        "reviewer_agent",
        review_route,
        {"replan": "bounded_replanner", "present": "present_workspace"},
    )
    graph.add_conditional_edges(
        "bounded_replanner",
        review_route,
        {"review": "deterministic_validator", "present": "present_workspace"},
    )
    graph.add_edge("present_workspace", END)
    return graph.compile(checkpointer=checkpointer)
