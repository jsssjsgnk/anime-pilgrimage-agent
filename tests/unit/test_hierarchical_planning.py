"""Hierarchical planning produces explainable independent strategy versions."""

from datetime import UTC, date, datetime, timedelta
from uuid import NAMESPACE_URL, uuid4, uuid5

from pilgrimage_agent.domain.models import (
    DataProvenance,
    DataStatus,
    GeoCoordinate,
    SubjectIntent,
    TripRequest,
)
from pilgrimage_agent.domain.planning import BaseCandidate
from pilgrimage_agent.domain.workspace import (
    PlanningStrategy,
    SubjectAppearance,
    VisitPlace,
)
from pilgrimage_agent.planning.areas import AreaClusteringPolicy, cluster_places
from pilgrimage_agent.planning.hierarchical import (
    HierarchicalPlanningRequest,
    plan_hierarchical_itineraries,
)


def _provenance() -> DataProvenance:
    return DataProvenance(
        provider="fixture",
        fetched_at=datetime.now(UTC),
        status=DataStatus.ESTIMATED,
    )


def _place(
    key: str,
    latitude: float,
    longitude: float,
    subjects: tuple[str, ...],
) -> VisitPlace:
    evidence_ids = tuple(
        uuid5(NAMESPACE_URL, f"planner-evidence:{key}:{subject}")
        for subject in subjects
    )
    return VisitPlace(
        place_id=uuid5(NAMESPACE_URL, f"planner-place:{key}"),
        canonical_name=key,
        coordinate=GeoCoordinate(latitude=latitude, longitude=longitude),
        verification_status="community",
        scene_evidence_ids=evidence_ids,
        subject_appearances=tuple(
            SubjectAppearance(subject_id=subject, evidence_ids=(evidence_id,))
            for subject, evidence_id in zip(subjects, evidence_ids, strict=True)
        ),
        merge_confidence=1.0,
        resolution_version="test-v1",
        provenance_label="fixture",
    )


def _fixture() -> tuple[TripRequest, tuple[VisitPlace, ...], BaseCandidate]:
    primary = SubjectIntent(
        query="Bocchi",
        confirmed_subject_id="328609",
        priority=5,
        minimum_place_count=2,
        is_primary=True,
        status="confirmed",
    )
    secondary = SubjectIntent(
        query="Lycoris",
        confirmed_subject_id="lycoris",
        priority=3,
        minimum_place_count=1,
        status="confirmed",
    )
    start = date.today() + timedelta(days=60)
    requirements = TripRequest(
        origin="Kyoto",
        destination="Tokyo",
        start_date=start,
        end_date=start + timedelta(days=1),
        subject_intents=(primary, secondary),
        walking_preference="high",
        max_walking_meters_per_day=10_000,
    )
    places = (
        _place("primary-a", 35.6800, 139.6800, ("328609",)),
        _place("primary-b", 35.6805, 139.6803, ("328609",)),
        _place("primary-c", 35.6810, 139.6806, ("328609",)),
        _place("shared", 35.6602, 139.6602, ("328609", "lycoris")),
    )
    base = BaseCandidate(
        base_id="station-area",
        name="Confirmed station area",
        coordinate=GeoCoordinate(latitude=35.6600, longitude=139.6600),
        provenance=_provenance(),
    )
    return requirements, places, base


def _request(
    *,
    places: tuple[VisitPlace, ...] | None = None,
    must_visit: frozenset[object] = frozenset(),
    walking_limit: float = 10_000,
) -> HierarchicalPlanningRequest:
    requirements, fixture_places, base = _fixture()
    selected = places or fixture_places
    requirements = requirements.model_copy(
        update={"max_walking_meters_per_day": walking_limit}
    )
    areas = cluster_places(
        selected,
        policy=AreaClusteringPolicy(eps_meters=500, min_samples=2),
    )
    return HierarchicalPlanningRequest(
        trip_id=uuid4(),
        requirements=requirements,
        places=selected,
        areas=areas,
        base=base,
        timezone="Europe/Paris",
        strategies=(
            PlanningStrategy.PRIMARY_SUBJECT_FIRST,
            PlanningStrategy.LOW_WALKING,
        ),
        must_visit_place_ids=frozenset(must_visit),
    )


def test_two_strategies_coexist_and_share_one_visit_across_coverage() -> None:
    result = plan_hierarchical_itineraries(_request())

    assert len(result.itineraries) == 2
    primary, low_walking = result.itineraries
    assert primary.strategy is PlanningStrategy.PRIMARY_SUBJECT_FIRST
    assert low_walking.strategy is PlanningStrategy.LOW_WALKING
    assert primary.itinerary_id != low_walking.itinerary_id
    assert primary.timezone == low_walking.timezone == "Europe/Paris"
    assert primary.base is not None
    primary_first = primary.days[0].visits[0].place_id
    low_walking_first = low_walking.days[0].visits[0].place_id
    assert primary_first != low_walking_first

    shared = next(place for place in _fixture()[1] if place.canonical_name == "shared")
    for itinerary in result.itineraries:
        scheduled = [visit.place_id for day in itinerary.days for visit in day.visits]
        assert scheduled.count(shared.place_id) == 1
        coverage = {item.subject_id: item for item in itinerary.subject_coverage}
        assert shared.place_id in coverage["328609"].scheduled_place_ids
        assert shared.place_id in coverage["lycoris"].scheduled_place_ids
        assert not itinerary.validation_issues
        assert itinerary.score_components


def test_tight_walking_limit_keeps_omissions_and_missing_must_visit_visible() -> None:
    far_required = _fixture()[1][0]
    result = plan_hierarchical_itineraries(
        _request(must_visit=frozenset({far_required.place_id}), walking_limit=500)
    )

    for itinerary in result.itineraries:
        omitted = {item.place_id: item.reason_code for item in itinerary.omissions}
        assert omitted[far_required.place_id] == "walking_limit"
        assert "missing_must_visit" in {
            item.code for item in itinerary.validation_issues
        }
        graph_ids = set(result.candidate_graph.place_ids)
        scheduled = {
            visit.place_id for day in itinerary.days for visit in day.visits
        }
        assert scheduled | set(omitted) == graph_ids


def test_candidate_graph_and_plan_ids_are_stable_under_input_order() -> None:
    places = _fixture()[1]
    forward_request = _request(places=places)
    reverse_request = forward_request.model_copy(
        update={
            "places": tuple(reversed(forward_request.places)),
            "areas": tuple(reversed(forward_request.areas)),
        }
    )
    forward = plan_hierarchical_itineraries(forward_request)
    reverse = plan_hierarchical_itineraries(reverse_request)

    assert forward.candidate_graph.graph_id == reverse.candidate_graph.graph_id
    assert {item.itinerary_id for item in forward.itineraries} == {
        item.itinerary_id for item in reverse.itineraries
    }
    assert [
        {visit.place_id for day in item.days for visit in day.visits}
        for item in forward.itineraries
    ] == [
        {visit.place_id for day in item.days for visit in day.visits}
        for item in reverse.itineraries
    ]
