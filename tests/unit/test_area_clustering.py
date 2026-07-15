"""Area clustering operates on canonical places and never loses outliers."""

from uuid import NAMESPACE_URL, UUID, uuid5

from pilgrimage_agent.domain.models import GeoCoordinate
from pilgrimage_agent.domain.workspace import SubjectAppearance, VisitPlace
from pilgrimage_agent.planning.areas import AreaClusteringPolicy, cluster_places


def _place(key: str, latitude: float, longitude: float) -> VisitPlace:
    evidence_id = uuid5(NAMESPACE_URL, f"area-evidence:{key}")
    return VisitPlace(
        place_id=uuid5(NAMESPACE_URL, f"area-place:{key}"),
        canonical_name=key,
        coordinate=GeoCoordinate(latitude=latitude, longitude=longitude),
        verification_status="community",
        scene_evidence_ids=(evidence_id,),
        subject_appearances=(
            SubjectAppearance(subject_id="328609", evidence_ids=(evidence_id,)),
        ),
        merge_confidence=1.0,
        resolution_version="test-v1",
        provenance_label="fixture",
    )


def _membership(areas: object) -> set[frozenset[UUID]]:
    return {frozenset(area.place_ids) for area in areas}  # type: ignore[attr-defined]


def test_dbscan_is_stable_and_keeps_isolated_singletons() -> None:
    close_a = _place("close-a", 35.6600, 139.6680)
    close_b = _place("close-b", 35.6610, 139.6690)
    isolated = _place("isolated", 36.1000, 137.2000)
    places = (close_a, close_b, isolated)

    forward = cluster_places(places)
    reverse = cluster_places(tuple(reversed(places)))

    assert len(forward) == 2
    assert _membership(forward) == _membership(reverse)
    assert {area.area_id for area in forward} == {area.area_id for area in reverse}
    assert any(area.place_ids == (isolated.place_id,) for area in forward)
    assert all(area.algorithm == "haversine_dbscan" for area in forward)
    assert all(area.algorithm_version == "area-dbscan-v2" for area in forward)
    assert all(area.travel_time_status == "haversine_fallback" for area in forward)
    assert all(area.warnings for area in forward)


def test_road_time_correction_splits_barrier_outlier_without_loss() -> None:
    west = _place("west", 35.6600, 139.6680)
    center = _place("center", 35.6610, 139.6690)
    east = _place("east", 35.6620, 139.6700)
    durations = {
        (center.place_id, west.place_id): 90.0,
        (center.place_id, east.place_id): 2_400.0,
    }

    areas = cluster_places(
        (east, west, center),
        policy=AreaClusteringPolicy(
            eps_meters=1_000,
            min_samples=2,
            max_internal_walking_minutes=25,
        ),
        walking_durations_seconds=durations,
    )

    assert len(areas) == 2
    assert any(area.place_ids == (east.place_id,) for area in areas)
    assert {place_id for area in areas for place_id in area.place_ids} == {
        west.place_id,
        center.place_id,
        east.place_id,
    }
    assert all(area.travel_time_status == "road" for area in areas)


def test_partial_walking_matrix_keeps_a_tuple_warning() -> None:
    first = _place("partial-first", 35.6600, 139.6680)
    second = _place("partial-second", 35.6610, 139.6690)

    areas = cluster_places(
        (first, second),
        walking_durations_seconds={},
    )

    assert len(areas) == 1
    assert areas[0].travel_time_status == "unverified"
    assert areas[0].warnings == (
        "Walking matrix coverage is partial; unverified pairs retain Haversine membership.",
    )


def test_empty_and_invalid_inputs_are_explicit() -> None:
    assert cluster_places(()) == ()
    duplicate = _place("duplicate", 35.0, 139.0)
    try:
        cluster_places((duplicate, duplicate))
    except ValueError as error:
        assert "unique" in str(error)
    else:  # pragma: no cover - invariant regression guard
        raise AssertionError("duplicate place IDs must fail")


def test_earlier_noise_becomes_a_border_member_of_a_later_core_cluster() -> None:
    border_left = _place("border-left", 35.6600, 139.6680).model_copy(
        update={"place_id": UUID(int=1)}
    )
    core = _place("core", 35.6607, 139.6680).model_copy(
        update={"place_id": UUID(int=2)}
    )
    border_right = _place("border-right", 35.6614, 139.6680).model_copy(
        update={"place_id": UUID(int=3)}
    )
    policy = AreaClusteringPolicy(eps_meters=100, min_samples=3)

    forward = cluster_places((border_left, core, border_right), policy=policy)
    reverse = cluster_places((border_right, core, border_left), policy=policy)

    assert len(forward) == 1
    assert forward[0].place_ids == (UUID(int=1), UUID(int=2), UUID(int=3))
    assert _membership(forward) == _membership(reverse)
