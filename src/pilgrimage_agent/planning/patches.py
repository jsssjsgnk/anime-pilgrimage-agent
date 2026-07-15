"""Common PlanPatch normalization, parsing, and dependency impact analysis."""

from __future__ import annotations

import re
from datetime import UTC, date, datetime
from uuid import UUID

from pydantic import Field

from pilgrimage_agent.domain.models import StrictModel, SubjectIntent
from pilgrimage_agent.domain.workspace import (
    ImpactAnalysis,
    KnowledgeOperation,
    MergeDecisionOperation,
    PatchOperation,
    PlaceOperation,
    PlanningStrategy,
    PlanPatch,
    SelectionOperation,
    SubjectIntentOperation,
    UpdateRequirementOperation,
)

_UUID = r"[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}"
_DATE = re.compile(r"\b(20\d{2}-\d{2}-\d{2})\b")
_TITLE = re.compile(r"《([^》]{1,100})》")


class NaturalLanguagePatchRequest(StrictModel):
    owner_user_id: str = Field(min_length=1, max_length=120)
    thread_id: str = Field(min_length=1, max_length=120)
    expected_base_version: int = Field(ge=1)
    instruction: str = Field(min_length=1, max_length=1000)
    idempotency_key: str = Field(
        min_length=8, max_length=120, pattern=r"^[A-Za-z0-9._:-]+$"
    )


class ApplyPlanPatchRequest(StrictModel):
    owner_user_id: str = Field(min_length=1, max_length=120)
    thread_id: str = Field(min_length=1, max_length=120)
    confirm: bool = False


class DirectPlanPatchRequest(StrictModel):
    owner_user_id: str = Field(min_length=1, max_length=120)
    thread_id: str = Field(min_length=1, max_length=120)
    patch: PlanPatch


class PlanPatchPreview(StrictModel):
    patch: PlanPatch
    impact: ImpactAnalysis


def confirmation_required(operations: tuple[PatchOperation, ...]) -> bool:
    """Material upstream and identity changes always require an explicit preview."""

    for operation in operations:
        if isinstance(operation, SubjectIntentOperation | MergeDecisionOperation):
            return True
        if isinstance(operation, UpdateRequirementOperation) and operation.field in {
            "origin",
            "destination",
            "base_preference",
            "start_date",
            "end_date",
        }:
            return True
        if isinstance(operation, SelectionOperation) and operation.action in {
            "change_access",
            "change_base",
            "create_branch",
        }:
            return True
        if isinstance(operation, KnowledgeOperation):
            return True
    return False


def normalize_patch(patch: PlanPatch) -> PlanPatch:
    """Ignore a caller's materiality claim and derive it from typed operations."""

    return patch.model_copy(
        update={
            "requires_confirmation": confirmation_required(patch.operations),
            "status": "proposed",
        }
    )


def analyze_impact(patch: PlanPatch) -> ImpactAnalysis:
    """Central dependency policy used by conversational and direct UI edits."""

    nodes: set[str] = {"validator"}
    invalidated: set[str] = set()
    stable: set[str] = set()
    reviewer = False
    for operation in patch.operations:
        if isinstance(operation, UpdateRequirementOperation):
            invalidated.add(f"requirement:{operation.field}")
            if operation.field in {"start_date", "end_date", "destination"}:
                nodes.update(
                    {
                        "access",
                        "weather",
                        "evidence_freshness",
                        "candidate_graph",
                        "itinerary_planner",
                    }
                )
            elif operation.field == "origin":
                nodes.update({"access", "itinerary_planner"})
                stable.update({"scene_evidence:*", "visit_place:*", "area:*"})
            elif operation.field == "base_preference":
                nodes.update({"base", "access_linkage", "itinerary_planner"})
                stable.update({"scene_evidence:*", "visit_place:*", "area:*"})
            else:
                nodes.update({"itinerary_planner"})
                stable.update(
                    {"subject:*", "scene_evidence:*", "visit_place:*", "area:*"}
                )
            reviewer = True
        elif isinstance(operation, SubjectIntentOperation):
            invalidated.add(f"subject_intent:{operation.intent_id or 'new'}")
            nodes.update(
                {
                    "subject_confirmation",
                    "evidence_collector",
                    "place_curator",
                    "area_clustering",
                    "candidate_graph",
                    "itinerary_planner",
                }
            )
            reviewer = True
        elif isinstance(operation, PlaceOperation):
            invalidated.add(f"visit_place:{operation.place_id}")
            if operation.action in {"move_day", "reorder"}:
                nodes.update({"local_matrix", "day_assignment"})
                invalidated.add(f"day:{operation.target_day}")
                stable.add("unaffected_days:*")
            else:
                nodes.update({"candidate_graph", "itinerary_planner"})
                stable.update({"scene_evidence:*", "area_membership:*"})
            reviewer = True
        elif isinstance(operation, SelectionOperation):
            invalidated.add(f"selection:{operation.action}")
            if operation.action == "change_base":
                nodes.update({"access_linkage", "route_matrix", "day_assignment"})
            else:
                nodes.update({"itinerary_planner"})
            stable.update({"scene_evidence:*", "visit_place:*", "area:*"})
            reviewer = True
        elif isinstance(operation, KnowledgeOperation):
            invalidated.add(f"knowledge:{operation.document_id}")
            nodes.update({"retrieval", "derived_rules", "itinerary_planner"})
            reviewer = True
        else:
            invalidated.update(f"scene_evidence:{item}" for item in operation.evidence_ids)
            nodes.update(
                {"place_curator", "area_clustering", "candidate_graph", "itinerary_planner"}
            )
            reviewer = True
    if reviewer:
        nodes.add("reviewer")
    return ImpactAnalysis(
        patch_id=patch.patch_id,
        invalidated_nodes=tuple(sorted(nodes)),
        invalidated_refs=tuple(sorted(invalidated)),
        stable_refs=tuple(sorted(stable)),
        reviewer_required=reviewer,
        confirmation_required=patch.requires_confirmation,
    )


def _uuid_after(text: str, marker: str) -> UUID | None:
    match = re.search(rf"{marker}\s*({_UUID})", text, re.IGNORECASE)
    return UUID(match.group(1)) if match else None


def parse_patch_instruction(
    *,
    trip_id: UUID,
    expected_base_version: int,
    instruction: str,
    idempotency_key: str,
) -> PlanPatch:
    """Parse one bounded edit; ambiguous free text is rejected instead of guessed."""

    normalized = instruction.strip()
    lowered = normalized.casefold()
    operation: PatchOperation
    if ("开始日期" in normalized or "start date" in lowered) and (
        match := _DATE.search(normalized)
    ):
        operation = UpdateRequirementOperation(
            field="start_date", value=date.fromisoformat(match.group(1))
        )
    elif any(
        token in lowered
        for token in ("步行", "walking", "少走", "多走", "走路", "不要走太多")
    ):
        preference = next(
            (
                value
                for token, value in (
                    ("不要走太多", "low"),
                    ("少走", "low"),
                    ("减少", "low"),
                    ("低", "low"),
                    ("low", "low"),
                    ("适中", "medium"),
                    ("中", "medium"),
                    ("medium", "medium"),
                    ("多走", "high"),
                    ("高", "high"),
                    ("high", "high"),
                )
                if token in lowered
            ),
            None,
        )
        if preference is None:
            raise ValueError("请说明希望少走、适中, 还是愿意多走一些")
        operation = UpdateRequirementOperation(
            field="walking_preference", value=preference
        )
    elif "添加作品" in normalized or "add subject" in lowered:
        titles = _TITLE.findall(normalized)
        if len(titles) != 1:
            raise ValueError("adding a subject requires exactly one title in 《》")
        operation = SubjectIntentOperation(
            action="add", intent=SubjectIntent(query=titles[0], priority=3)
        )
    elif "remove subject" in lowered or "移除作品" in normalized:
        intent_id = _uuid_after(normalized, r"(?:remove subject|移除作品)")
        if intent_id is None:
            raise ValueError("removing a subject requires its intent UUID")
        operation = SubjectIntentOperation(action="remove", intent_id=intent_id)
    elif "move place" in lowered or "移动地点" in normalized:
        place_id = _uuid_after(normalized, r"(?:move place|移动地点)")
        day_match = re.search(r"(?:day|第)\s*(\d{1,2})", normalized, re.IGNORECASE)
        if place_id is None or day_match is None:
            raise ValueError("moving a place requires a place UUID and target day")
        operation = PlaceOperation(
            action="move_day",
            place_id=place_id,
            target_day=int(day_match.group(1)),
        )
    elif "exclude place" in lowered or "排除地点" in normalized:
        place_id = _uuid_after(normalized, r"(?:exclude place|排除地点)")
        if place_id is None:
            raise ValueError("excluding a place requires its UUID")
        operation = PlaceOperation(action="exclude", place_id=place_id)
    elif "change base" in lowered or "更换住宿基地" in normalized:
        match = re.search(
            r"(?:change base|更换住宿基地)\s+([A-Za-z0-9._:-]{1,100})",
            normalized,
            re.IGNORECASE,
        )
        if match is None:
            raise ValueError("base changes require a candidate base ID")
        operation = SelectionOperation(
            action="change_base", selection_id=match.group(1)
        )
    elif "低步行策略" in normalized or "low walking strategy" in lowered:
        operation = SelectionOperation(
            action="change_strategy", strategy=PlanningStrategy.LOW_WALKING
        )
    else:
        raise ValueError("instruction does not match one bounded PlanPatch operation")
    return normalize_patch(
        PlanPatch(
            trip_id=trip_id,
            expected_base_version=expected_base_version,
            operations=(operation,),
            rationale=normalized,
            requires_confirmation=False,
            idempotency_key=idempotency_key,
            created_at=datetime.now(UTC),
        )
    )
