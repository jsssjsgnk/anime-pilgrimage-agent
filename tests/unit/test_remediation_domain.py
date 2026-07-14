"""Remediation domain invariants and explicit legacy adapters."""

from datetime import UTC, date, datetime, timedelta
from uuid import uuid4

import pytest
from pydantic import ValidationError

from pilgrimage_agent.domain.models import (
    DataProvenance,
    DataStatus,
    GeoCoordinate,
    SubjectIntent,
    TripRequest,
)
from pilgrimage_agent.domain.workspace import (
    AgentHandoff,
    AgentRole,
    DerivedKnowledgeRule,
    EntityRef,
    EvidenceQuarantine,
    ItineraryDay,
    ItineraryVersion,
    PlaceResolutionResult,
    PlanningStrategy,
    PlanPatch,
    SceneEvidence,
    ScheduledPlace,
    SubjectAppearance,
    VisitPlace,
)


def _provenance() -> DataProvenance:
    return DataProvenance(
        provider="fixture",
        fetched_at=datetime.now(UTC),
        status=DataStatus.COMMUNITY,
    )


def _evidence(*, subject_id: str = "328609") -> SceneEvidence:
    return SceneEvidence(
        evidence_id=uuid4(),
        subject_id=subject_id,
        provider="fixture",
        provider_record_id=str(uuid4()),
        coordinate=GeoCoordinate(latitude=35.0, longitude=139.0),
        names=("Test place",),
        provenance=_provenance(),
        raw_fingerprint="a" * 64,
    )


def test_legacy_query_maps_to_one_stable_primary_subject_intent() -> None:
    first = TripRequest(anime_query="孤独摇滚")
    second = TripRequest(anime_query="孤独摇滚")

    assert len(first.subject_intents) == 1
    assert first.subject_intents[0].is_primary
    assert first.subject_intents[0].priority == 5
    assert first.subject_intents[0].intent_id == second.subject_intents[0].intent_id
    assert first.primary_subject_query == "孤独摇滚"


def test_trip_request_requires_one_primary_and_at_most_three_intents() -> None:
    with pytest.raises(ValidationError, match="one and only one"):
        TripRequest(
            subject_intents=(
                SubjectIntent(query="A"),
                SubjectIntent(query="B"),
            )
        )
    with pytest.raises(ValidationError):
        TripRequest(
            subject_intents=tuple(
                SubjectIntent(query=str(index), is_primary=index == 0)
                for index in range(4)
            )
        )


def test_confirmed_subject_intent_requires_catalog_id() -> None:
    with pytest.raises(ValidationError, match="catalog subject ID"):
        SubjectIntent(query="A", is_primary=True, status="confirmed")


def test_place_resolution_accounts_for_every_evidence_once() -> None:
    linked = _evidence()
    invalid = _evidence(subject_id="lycoris")
    place = VisitPlace(
        place_id=uuid4(),
        canonical_name="Shared location",
        coordinate=GeoCoordinate(latitude=35.0, longitude=139.0),
        verification_status="community",
        scene_evidence_ids=(linked.evidence_id,),
        subject_appearances=(
            SubjectAppearance(
                subject_id=linked.subject_id, evidence_ids=(linked.evidence_id,)
            ),
        ),
        merge_confidence=1.0,
        resolution_version="test-v1",
        provenance_label="fixture",
    )

    result = PlaceResolutionResult(
        policy_version="test-v1",
        evidence=(linked, invalid),
        places=(place,),
        quarantined=(
            EvidenceQuarantine(
                evidence_id=invalid.evidence_id,
                reason_code="invalid_coordinate",
                detail="Fixture invalid coordinate.",
            ),
        ),
    )

    assert result.places[0].scene_evidence_ids == (linked.evidence_id,)
    with pytest.raises(ValidationError, match="exactly once"):
        PlaceResolutionResult(
            policy_version="test-v1",
            evidence=(linked, invalid),
            places=(place,),
            quarantined=(),
        )


def test_quarantined_scene_evidence_requires_reason() -> None:
    with pytest.raises(ValidationError, match="requires a reason"):
        SceneEvidence.model_validate(
            {
                **_evidence().model_dump(mode="python"),
                "resolution_status": "quarantined",
                "quarantine_reason": None,
            }
        )


def test_itinerary_rejects_duplicate_shared_place_scheduling() -> None:
    now = datetime.now(UTC)
    place_id = uuid4()
    area_id = uuid4()
    first = ScheduledPlace(
        place_id=place_id,
        area_id=area_id,
        sequence=0,
        start_at=now,
        end_at=now + timedelta(minutes=30),
        incoming_distance_meters=10,
        incoming_duration_seconds=10,
    )
    second = first.model_copy(
        update={
            "sequence": 1,
            "start_at": now + timedelta(hours=1),
            "end_at": now + timedelta(hours=2),
        }
    )

    with pytest.raises(ValidationError, match="scheduled only once"):
        ItineraryVersion(
            trip_id=uuid4(),
            candidate_graph_id=uuid4(),
            version=1,
            strategy=PlanningStrategy.BALANCED,
            timezone="Asia/Tokyo",
            days=(
                ItineraryDay(
                    date=date.today(),
                    area_ids=(area_id,),
                    visits=(first, second),
                    walking_distance_meters=100,
                    duration_minutes=120,
                ),
            ),
            subject_coverage=(),
            total_walking_meters=100,
            total_duration_minutes=120,
            omissions=(),
            score_components=(),
            evidence_refs=(),
            created_at=now,
        )


def test_plan_patch_parses_discriminated_operations() -> None:
    patch = PlanPatch.model_validate(
        {
            "trip_id": str(uuid4()),
            "expected_base_version": 2,
            "operations": [
                {
                    "op": "update_requirement",
                    "field": "walking_preference",
                    "value": "low",
                },
                {
                    "op": "place",
                    "action": "move_day",
                    "place_id": str(uuid4()),
                    "target_day": 2,
                },
            ],
            "rationale": "Reduce walking and preserve the selected visit.",
            "requires_confirmation": False,
            "idempotency_key": "client:patch:0001",
            "created_at": datetime.now(UTC).isoformat(),
        }
    )

    assert [operation.op for operation in patch.operations] == [
        "update_requirement",
        "place",
    ]


def test_handoff_and_knowledge_rule_boundaries_are_strict() -> None:
    now = datetime.now(UTC)
    reference = EntityRef(entity_type="candidate_graph", entity_id=str(uuid4()), version=1)
    handoff = AgentHandoff(
        run_id=uuid4(),
        sender=AgentRole.PLACE_CURATOR,
        receiver=AgentRole.ITINERARY_PLANNER,
        task_type="build_alternatives",
        goal="Build two deterministic itinerary strategies.",
        input_refs=(reference,),
        expected_output_schema="ItineraryVersion[]",
        status="completed",
        result_refs=(EntityRef(entity_type="itinerary", entity_id=str(uuid4())),),
        created_at=now,
        completed_at=now,
    )
    assert handoff.completed_at == now

    with pytest.raises(ValidationError, match="high-authority"):
        DerivedKnowledgeRule(
            trip_id=uuid4(),
            rule_type="opening_window",
            target_refs=(reference,),
            value={"opens_at": "10:00"},
            evidence_ids=("K-123456789abc",),
            authority_level=2,
            status="active_constraint",
            created_at=now,
        )
