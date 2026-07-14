"""General PlanPatch operations share one impact and revalidation path."""

from datetime import UTC, date, datetime
from uuid import uuid4

import pytest
from pydantic import ValidationError

from pilgrimage_agent.agent.context import RoleContextBuilder
from pilgrimage_agent.domain.workspace import (
    AgentRole,
    ContextFact,
    EntityRef,
    PlaceOperation,
    PlanPatch,
    SelectionOperation,
    UpdateRequirementOperation,
)
from pilgrimage_agent.planning.patches import (
    analyze_impact,
    normalize_patch,
    parse_patch_instruction,
)


def _patch(operation: object, *, requires_confirmation: bool = False) -> PlanPatch:
    return PlanPatch.model_validate(
        {
            "trip_id": str(uuid4()),
            "expected_base_version": 3,
            "operations": [operation],
            "rationale": "bounded fixture change",
            "requires_confirmation": requires_confirmation,
            "idempotency_key": f"fixture:{uuid4()}",
            "created_at": datetime.now(UTC),
        }
    )


def test_natural_language_and_direct_date_edit_have_the_same_operation() -> None:
    trip_id = uuid4()
    direct = normalize_patch(
        PlanPatch(
            trip_id=trip_id,
            expected_base_version=3,
            operations=(
                UpdateRequirementOperation(
                    field="start_date", value=date(2027, 4, 5)
                ),
            ),
            rationale="direct UI edit",
            requires_confirmation=False,
            idempotency_key="fixture:direct-date",
            created_at=datetime.now(UTC),
        )
    )
    parsed = parse_patch_instruction(
        trip_id=trip_id,
        expected_base_version=3,
        instruction="把开始日期改为 2027-04-05",
        idempotency_key="fixture:natural-date",
    )

    assert parsed.operations == direct.operations
    assert parsed.requires_confirmation is direct.requires_confirmation is True
    assert analyze_impact(parsed).invalidated_nodes == analyze_impact(
        direct
    ).invalidated_nodes


def test_materiality_and_central_impact_rules_cannot_be_weakened_by_client() -> None:
    place_id = uuid4()
    local = normalize_patch(
        _patch(PlaceOperation(action="move_day", place_id=place_id, target_day=2))
    )
    base = normalize_patch(
        _patch(
            SelectionOperation(action="change_base", selection_id="station-area"),
            requires_confirmation=False,
        )
    )

    local_impact = analyze_impact(local)
    base_impact = analyze_impact(base)
    assert local.requires_confirmation is False
    assert "day_assignment" in local_impact.invalidated_nodes
    assert "unaffected_days:*" in local_impact.stable_refs
    assert base.requires_confirmation is True
    assert {"access_linkage", "route_matrix", "validator"}.issubset(
        base_impact.invalidated_nodes
    )


def test_date_patch_survives_json_persistence_round_trip() -> None:
    patch = parse_patch_instruction(
        trip_id=uuid4(),
        expected_base_version=3,
        instruction="把开始日期改为 2030-09-02",
        idempotency_key="fixture:date-roundtrip",
    )

    restored = PlanPatch.model_validate(patch.model_dump(mode="json"))

    operation = restored.operations[0]
    assert isinstance(operation, UpdateRequirementOperation)
    assert operation.value == date(2030, 9, 2)


def test_natural_walking_request_does_not_require_internal_enum_words() -> None:
    patch = parse_patch_instruction(
        trip_id=uuid4(),
        expected_base_version=3,
        instruction="我想每天少走一点",
        idempotency_key="fixture:natural-walking",
    )

    operation = patch.operations[0]
    assert isinstance(operation, UpdateRequirementOperation)
    assert operation.field == "walking_preference"
    assert operation.value == "low"


def test_operation_models_reject_incomplete_targets() -> None:
    with pytest.raises(ValidationError, match="target day"):
        PlaceOperation(action="move_day", place_id=uuid4())
    with pytest.raises(ValidationError, match="strategy changes"):
        SelectionOperation(action="change_strategy")


def test_role_context_is_bounded_and_excludes_raw_categories() -> None:
    builder = RoleContextBuilder()
    context = builder.build(
        role=AgentRole.REVIEWER,
        run_id=uuid4(),
        facts=tuple(ContextFact(key=f"fact-{index}", value=index) for index in range(100)),
        refs=tuple(
            EntityRef(entity_type="place", entity_id=str(uuid4()))
            for _index in range(100)
        ),
    )

    assert len(context.facts) == 60
    assert len(context.refs) == 80
    assert context.estimated_tokens <= 4000
    assert context.byte_size <= 64_000
    assert "raw_prompts" in context.excluded_categories
