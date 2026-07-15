"""Scenario G: violation semantics select different bounded repair patches."""

from uuid import uuid4

import pytest

from pilgrimage_agent.planning.replanner import (
    ReplanViolation,
    ViolationCode,
    propose_violation_patch,
    run_bounded_replanning,
)


@pytest.mark.parametrize(
    ("violation", "expected_operations"),
    [
        (
            ReplanViolation(
                code=ViolationCode.MISSING_MUST_VISIT,
                detail="required place missing",
                place_id=uuid4(),
            ),
            (("place", "include"),),
        ),
        (
            ReplanViolation(
                code=ViolationCode.WALKING_LIMIT,
                detail="walking exceeds limit",
            ),
            (("selection", "change_strategy"),),
        ),
        (
            ReplanViolation(
                code=ViolationCode.VISIT_WINDOW,
                detail="closed on day one",
                place_id=uuid4(),
                target_day=2,
            ),
            (("place", "move_day"),),
        ),
        (
            ReplanViolation(
                code=ViolationCode.SUBJECT_MINIMUM_COVERAGE,
                detail="secondary subject coverage missing",
                replacement_place_id=uuid4(),
                lower_priority_place_id=uuid4(),
            ),
            (("place", "include"), ("place", "exclude")),
        ),
        (
            ReplanViolation(
                code=ViolationCode.STALE_ACCESS,
                detail="access quote expired",
                replacement_access_id="access-refreshed",
            ),
            (("selection", "change_access"),),
        ),
        (
            ReplanViolation(
                code=ViolationCode.INEFFICIENT_BASE,
                detail="base adds excessive transfers",
                replacement_base_id="base-ueno",
            ),
            (("selection", "create_branch"), ("selection", "change_base")),
        ),
    ],
)
def test_violation_types_produce_semantically_distinct_patches(
    violation: ReplanViolation, expected_operations: tuple[tuple[str, str], ...]
) -> None:
    proposal = propose_violation_patch(
        trip_id=uuid4(), expected_base_version=4, violation=violation
    )

    assert proposal.status == "proposed"
    assert proposal.patch is not None
    assert tuple(
        (operation.op, str(operation.model_dump(mode="python")["action"]))
        for operation in proposal.patch.operations
    ) == expected_operations
    assert proposal.patch.expected_base_version == 4
    assert proposal.patch.requires_confirmation == (
        violation.code in {ViolationCode.STALE_ACCESS, ViolationCode.INEFFICIENT_BASE}
    )


def test_missing_repair_reference_remains_visible_as_partial() -> None:
    violation = ReplanViolation(
        code=ViolationCode.VISIT_WINDOW,
        detail="no compatible alternate day is known",
        place_id=uuid4(),
        stable_refs=("day:1", "place:stable"),
    )

    proposal = propose_violation_patch(
        trip_id=uuid4(), expected_base_version=2, violation=violation
    )

    assert proposal.status == "partial"
    assert proposal.patch is None
    assert proposal.unresolved == (violation,)
    assert proposal.stable_refs == ("day:1", "place:stable")


def test_replanning_loop_is_bounded_and_validator_remains_authoritative() -> None:
    violation = ReplanViolation(
        code=ViolationCode.WALKING_LIMIT,
        detail="validator still measures excessive walking",
        stable_refs=("day:1", "day:3"),
    )
    validator_calls: list[int] = []

    def still_invalid(_patch: object, attempt: int) -> tuple[ReplanViolation, ...]:
        validator_calls.append(attempt)
        return (violation,)

    result = run_bounded_replanning(
        trip_id=uuid4(),
        expected_base_version=7,
        violations=(violation,),
        validate_after_patch=still_invalid,
        max_attempts=3,
    )

    assert result.status == "partial"
    assert result.attempts == 3
    assert validator_calls == [1, 2, 3]
    assert [patch.expected_base_version for patch in result.patches] == [7, 8, 9]
    assert result.remaining_violations == (violation,)


def test_replanning_only_reports_resolved_after_validator_clears_issues() -> None:
    violation = ReplanViolation(
        code=ViolationCode.MISSING_MUST_VISIT,
        detail="required place missing",
        place_id=uuid4(),
    )

    result = run_bounded_replanning(
        trip_id=uuid4(),
        expected_base_version=1,
        violations=(violation,),
        validate_after_patch=lambda _patch, _attempt: (),
    )

    assert result.status == "resolved"
    assert result.attempts == 1
    assert result.remaining_violations == ()
