"""Violation-specific, bounded replanning proposals.

The Validator remains authoritative: this module can only propose typed patches and
reports PARTIAL whenever validation still returns a violation.
"""

from __future__ import annotations

from collections.abc import Callable
from datetime import UTC, datetime
from enum import StrEnum
from uuid import UUID, uuid4

from pydantic import Field

from pilgrimage_agent.domain.models import StrictModel
from pilgrimage_agent.domain.workspace import (
    PlaceOperation,
    PlanningStrategy,
    PlanPatch,
    SelectionOperation,
)
from pilgrimage_agent.planning.patches import normalize_patch


class ViolationCode(StrEnum):
    MISSING_MUST_VISIT = "missing_must_visit"
    WALKING_LIMIT = "walking_limit"
    VISIT_WINDOW = "visit_window"
    SUBJECT_MINIMUM_COVERAGE = "subject_minimum_coverage"
    STALE_ACCESS = "stale_access"
    INEFFICIENT_BASE = "inefficient_base"


class ReplanViolation(StrictModel):
    violation_id: UUID = Field(default_factory=uuid4)
    code: ViolationCode
    detail: str = Field(min_length=1, max_length=300)
    place_id: UUID | None = None
    replacement_place_id: UUID | None = None
    lower_priority_place_id: UUID | None = None
    target_day: int | None = Field(default=None, ge=1, le=30)
    replacement_access_id: str | None = Field(default=None, max_length=200)
    replacement_base_id: str | None = Field(default=None, max_length=200)
    stable_refs: tuple[str, ...] = ()


class ReplanProposal(StrictModel):
    status: str = Field(pattern=r"^(proposed|partial)$")
    patch: PlanPatch | None = None
    unresolved: tuple[ReplanViolation, ...] = ()
    stable_refs: tuple[str, ...] = ()


class BoundedReplanResult(StrictModel):
    status: str = Field(pattern=r"^(resolved|partial)$")
    attempts: int = Field(ge=0, le=10)
    patches: tuple[PlanPatch, ...]
    remaining_violations: tuple[ReplanViolation, ...]


def propose_violation_patch(
    *,
    trip_id: UUID,
    expected_base_version: int,
    violation: ReplanViolation,
) -> ReplanProposal:
    """Map one deterministic violation to a semantically relevant patch family."""

    operations: tuple[PlaceOperation | SelectionOperation, ...]
    code = violation.code
    if code is ViolationCode.MISSING_MUST_VISIT and violation.place_id is not None:
        operations = (PlaceOperation(action="include", place_id=violation.place_id),)
        rationale = "Schedule the missing required place without dropping another day blindly."
    elif code is ViolationCode.WALKING_LIMIT:
        if violation.place_id is not None and violation.target_day is not None:
            operations = (
                PlaceOperation(
                    action="move_day",
                    place_id=violation.place_id,
                    target_day=violation.target_day,
                ),
            )
        else:
            operations = (
                SelectionOperation(
                    action="change_strategy", strategy=PlanningStrategy.LOW_WALKING
                ),
            )
        rationale = "Reduce walking through a targeted move or the low-walking strategy."
    elif (
        code is ViolationCode.VISIT_WINDOW
        and violation.place_id is not None
        and violation.target_day is not None
    ):
        operations = (
            PlaceOperation(
                action="move_day",
                place_id=violation.place_id,
                target_day=violation.target_day,
            ),
        )
        rationale = "Move the place to a day compatible with its visit window."
    elif (
        code is ViolationCode.SUBJECT_MINIMUM_COVERAGE
        and violation.replacement_place_id is not None
    ):
        coverage_operations: list[PlaceOperation] = [
            PlaceOperation(action="include", place_id=violation.replacement_place_id)
        ]
        if violation.lower_priority_place_id is not None:
            coverage_operations.append(
                PlaceOperation(
                    action="exclude", place_id=violation.lower_priority_place_id
                )
            )
        operations = tuple(coverage_operations)
        rationale = (
            "Add missing-subject coverage and only replace an explicit "
            "lower-priority place."
        )
    elif (
        code is ViolationCode.STALE_ACCESS
        and violation.replacement_access_id is not None
    ):
        operations = (
            SelectionOperation(
                action="change_access", selection_id=violation.replacement_access_id
            ),
        )
        rationale = "Invalidate stale access and require confirmation of a refreshed option."
    elif (
        code is ViolationCode.INEFFICIENT_BASE
        and violation.replacement_base_id is not None
    ):
        operations = (
            SelectionOperation(action="create_branch"),
            SelectionOperation(
                action="change_base", selection_id=violation.replacement_base_id
            ),
        )
        rationale = "Create an alternative plan branch around the more efficient base."
    else:
        return ReplanProposal(
            status="partial",
            unresolved=(violation,),
            stable_refs=violation.stable_refs,
        )

    patch = normalize_patch(
        PlanPatch(
            trip_id=trip_id,
            expected_base_version=expected_base_version,
            operations=operations,
            rationale=rationale,
            requires_confirmation=False,
            idempotency_key=f"replanner:{violation.violation_id}",
            created_at=datetime.now(UTC),
        )
    )
    return ReplanProposal(
        status="proposed", patch=patch, stable_refs=violation.stable_refs
    )


ValidationCallback = Callable[
    [PlanPatch, int], tuple[ReplanViolation, ...]
]


def run_bounded_replanning(
    *,
    trip_id: UUID,
    expected_base_version: int,
    violations: tuple[ReplanViolation, ...],
    validate_after_patch: ValidationCallback,
    max_attempts: int = 3,
) -> BoundedReplanResult:
    """Propose at most ``max_attempts`` patches and trust validator output only."""

    if not 1 <= max_attempts <= 10:
        raise ValueError("max_attempts must be between 1 and 10")
    remaining = violations
    patches: list[PlanPatch] = []
    for attempt in range(1, max_attempts + 1):
        if not remaining:
            break
        proposal = propose_violation_patch(
            trip_id=trip_id,
            expected_base_version=expected_base_version + len(patches),
            violation=remaining[0],
        )
        if proposal.patch is None:
            return BoundedReplanResult(
                status="partial",
                attempts=len(patches),
                patches=tuple(patches),
                remaining_violations=remaining,
            )
        patches.append(proposal.patch)
        remaining = validate_after_patch(proposal.patch, attempt)
    return BoundedReplanResult(
        status="resolved" if not remaining else "partial",
        attempts=len(patches),
        patches=tuple(patches),
        remaining_violations=remaining,
    )
