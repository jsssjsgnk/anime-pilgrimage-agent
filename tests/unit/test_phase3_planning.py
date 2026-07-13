"""Deterministic Phase 3 planning algorithms and invariants."""

from __future__ import annotations

from datetime import UTC, date, datetime, time, timedelta
from urllib.parse import parse_qs, urlparse
from uuid import UUID, uuid5
from zoneinfo import ZoneInfo

import pytest
from hypothesis import given, settings
from hypothesis import strategies as st

from pilgrimage_agent.domain.models import (
    DataProvenance,
    DataStatus,
    GeoCoordinate,
    MatrixQuery,
    PilgrimagePoint,
    RouteA,
    RouteMatrix,
)
from pilgrimage_agent.domain.planning import (
    AccessMode,
    AccessOption,
    BaseCandidate,
    OmissionCode,
    PlanningConstraints,
)
from pilgrimage_agent.planning.access import select_access_options
from pilgrimage_agent.planning.geo import (
    GOOGLE_MAPS_MAX_URL_LENGTH,
    google_maps_direction_urls,
    haversine_matrix,
    matrix_with_fallback,
)
from pilgrimage_agent.planning.planner import (
    build_route_b,
    choose_base,
    cluster_points,
    validate_route_b,
)
from pilgrimage_agent.providers.base import ProviderError, ProviderErrorKind
from pilgrimage_agent.providers.ors import FixtureOpenRouteServiceProvider


def prov(provider: str = "fixture") -> DataProvenance:
    return DataProvenance(
        provider=provider,
        source_url="https://example.org/source",
        fetched_at=datetime(2030, 1, 1, tzinfo=UTC),
        status=DataStatus.CACHED,
    )


def point(index: int, latitude: float, longitude: float) -> PilgrimagePoint:
    return PilgrimagePoint(
        id=uuid5(UUID(int=0), f"point-{index}"),
        subject_id="subject",
        name=f"Point {index}",
        latitude=latitude,
        longitude=longitude,
        confidence="verified",
        provenance=prov(),
    )


def base(latitude: float = 35.66, longitude: float = 139.66) -> BaseCandidate:
    return BaseCandidate(
        base_id="base",
        name="Base",
        coordinate=GeoCoordinate(latitude=latitude, longitude=longitude),
        provenance=prov(),
    )


def constraints(
    start: date,
    *,
    days: int = 3,
    max_walk: float = 8_000,
    must: frozenset[UUID] = frozenset(),
    excluded: frozenset[UUID] = frozenset(),
) -> PlanningConstraints:
    timezone = ZoneInfo("Asia/Tokyo")
    end = start + timedelta(days=days - 1)
    return PlanningConstraints(
        start_date=start,
        end_date=end,
        arrival_at=datetime.combine(start, time(8), timezone),
        departure_at=datetime.combine(end, time(20), timezone),
        max_walking_meters_per_day=max_walk,
        must_visit_point_ids=must,
        excluded_point_ids=excluded,
    )


@settings(max_examples=30, deadline=None)
@given(
    latitudes=st.lists(
        st.floats(min_value=35.60, max_value=35.72, allow_nan=False),
        min_size=1,
        max_size=12,
    )
)
def test_route_b_is_always_a_route_a_subset(latitudes: list[float]) -> None:
    points = tuple(
        point(index, latitude, 139.60 + index * 0.002)
        for index, latitude in enumerate(latitudes)
    )
    route_a = RouteA(subject_id="subject", points=points, is_complete=True)
    chosen_base = base()
    coordinates = (
        chosen_base.coordinate,
        *(GeoCoordinate(latitude=item.latitude, longitude=item.longitude) for item in points),
    )
    plan = build_route_b(
        route_a=route_a,
        base=chosen_base,
        matrix=haversine_matrix(coordinates),
        constraints=constraints(date(2030, 1, 1), max_walk=5_000),
    )
    scheduled = {visit.point_id for day in plan.days for visit in day.visits}
    assert scheduled <= {item.id for item in points}
    assert scheduled | set(plan.omitted_reasons) == {item.id for item in points}


def test_required_excluded_buffers_and_walking_constraints_are_validated() -> None:
    points = (point(1, 35.661, 139.661), point(2, 35.70, 139.71))
    route_a = RouteA(subject_id="subject", points=points, is_complete=True)
    chosen_base = base()
    matrix = haversine_matrix(
        (
            chosen_base.coordinate,
            *(GeoCoordinate(latitude=item.latitude, longitude=item.longitude) for item in points),
        )
    )
    plan = build_route_b(
        route_a=route_a,
        base=chosen_base,
        matrix=matrix,
        constraints=constraints(
            date(2030, 1, 1),
            max_walk=1_000,
            must=frozenset({points[1].id}),
            excluded=frozenset({points[0].id}),
        ),
    )
    assert plan.omitted_reasons[points[0].id].code is OmissionCode.EXCLUDED
    assert plan.omitted_reasons[points[1].id].code is OmissionCode.WALKING_LIMIT
    report = validate_route_b(
        plan,
        constraints(
            date(2030, 1, 1),
            max_walk=1_000,
            must=frozenset({points[1].id}),
            excluded=frozenset({points[0].id}),
        ),
    )
    assert not report.valid
    assert {issue.code for issue in report.issues} == {"missing_must_visit"}


async def test_ors_matrix_and_haversine_fallback_are_labelled() -> None:
    query = MatrixQuery(
        coordinates=(
            GeoCoordinate(latitude=35.66, longitude=139.66),
            GeoCoordinate(latitude=35.67, longitude=139.67),
        )
    )
    road = await matrix_with_fallback(FixtureOpenRouteServiceProvider(), query)

    class FailingProvider:
        async def matrix(self, _query: MatrixQuery) -> RouteMatrix:
            raise ProviderError(
                ProviderErrorKind.RATE_LIMIT,
                "fixture",
                "fixture limit",
                retryable=True,
            )

    fallback = await matrix_with_fallback(FailingProvider(), query)
    assert road.provenance.provider == "openrouteservice-fixture"
    assert fallback.provenance.provider == "haversine"
    assert fallback.provenance.status is DataStatus.ESTIMATED


def test_google_maps_urls_are_encoded_bounded_split_and_continuous() -> None:
    coordinates = tuple(
        GeoCoordinate(latitude=35.60 + index * 0.01, longitude=139.60 + index * 0.01)
        for index in range(12)
    )
    urls = google_maps_direction_urls(coordinates)
    assert len(urls) > 1
    previous_destination: str | None = None
    for url in urls:
        assert len(url) <= GOOGLE_MAPS_MAX_URL_LENGTH
        parsed = parse_qs(urlparse(url).query)
        assert parsed["api"] == ["1"]
        assert parsed["travelmode"] == ["walking"]
        if previous_destination is not None:
            assert parsed["origin"] == [previous_destination]
        previous_destination = parsed["destination"][0]
        assert len(parsed.get("waypoints", [""])[0].split("|")) <= 3


def test_base_clustering_and_access_selection_are_deterministic() -> None:
    points = (point(1, 35.661, 139.661), point(2, 35.662, 139.662))
    near, far = base(), BaseCandidate(
        base_id="far",
        name="Far",
        coordinate=GeoCoordinate(latitude=35.8, longitude=139.8),
        provenance=prov(),
    )
    assert choose_base((far, near), points).base_id == "base"
    clusters = cluster_points(points, 3)
    assert sum(len(cluster) for cluster in clusters) == len(points)

    inbound = AccessOption(
        option_id="inbound",
        mode=AccessMode.TRAIN,
        origin="Kyoto",
        destination="Tokyo",
        departure_at=datetime(2030, 1, 1, 6, tzinfo=UTC),
        arrival_at=datetime(2030, 1, 1, 8, tzinfo=UTC),
        price=10_000,
        currency="JPY",
        provenance=prov(),
    )
    outbound = inbound.model_copy(
        update={
            "option_id": "outbound",
            "origin": "Tokyo",
            "destination": "Kyoto",
            "departure_at": datetime(2030, 1, 3, 10, tzinfo=UTC),
            "arrival_at": datetime(2030, 1, 3, 12, tzinfo=UTC),
        }
    )
    selection = select_access_options(
        inbound_options=(inbound,),
        outbound_options=(outbound,),
        max_total_price=25_000,
    )
    assert selection.inbound.option_id == "inbound"
    with pytest.raises(ValueError, match="price constraint"):
        select_access_options(
            inbound_options=(inbound,),
            outbound_options=(outbound,),
            max_total_price=15_000,
        )
