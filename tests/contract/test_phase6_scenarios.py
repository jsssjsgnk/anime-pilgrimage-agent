"""Complete relative-clock S2 and degraded S3 acceptance scenarios."""

from __future__ import annotations

from datetime import UTC, date, datetime, time, timedelta
from uuid import UUID, uuid5
from zoneinfo import ZoneInfo

import httpx
import pytest

from pilgrimage_agent.agent.review import StructuredOutputError, parse_reviewer_output
from pilgrimage_agent.agent.schemas import ReviewerInput
from pilgrimage_agent.domain.models import (
    DataProvenance,
    DataStatus,
    FlightSearchQuery,
    GeoCoordinate,
    MatrixQuery,
    PilgrimagePoint,
    PilgrimagePointQuery,
    RouteA,
    RouteMatrix,
    WeatherForecastQuery,
)
from pilgrimage_agent.domain.planning import BaseCandidate, PlanningConstraints
from pilgrimage_agent.planning.geo import haversine_matrix, matrix_with_fallback
from pilgrimage_agent.planning.planner import build_route_b, validate_route_b
from pilgrimage_agent.providers.anitabi import AnitabiProvider
from pilgrimage_agent.providers.base import ProviderError, ProviderErrorKind
from pilgrimage_agent.providers.cache import request_fingerprint
from pilgrimage_agent.providers.http import SafeHttpClient
from pilgrimage_agent.providers.points import build_route_a
from pilgrimage_agent.providers.searchapi import SearchApiFlightProvider
from pilgrimage_agent.providers.weather import FixtureOpenMeteoProvider


def _provenance(provider: str = "fixture") -> DataProvenance:
    return DataProvenance(
        provider=provider,
        source_url="https://example.test/source",
        fetched_at=datetime(2030, 1, 1, tzinfo=UTC),
        status=DataStatus.CACHED,
    )


def _point() -> PilgrimagePoint:
    return PilgrimagePoint(
        id=uuid5(UUID(int=0), "scenario-point"),
        subject_id="328609",
        name="Scenario point",
        latitude=35.661,
        longitude=139.661,
        confidence="verified",
        provenance=_provenance(),
    )


def _base() -> BaseCandidate:
    return BaseCandidate(
        base_id="scenario-base",
        name="Scenario base",
        coordinate=GeoCoordinate(latitude=35.66, longitude=139.66),
        provenance=_provenance(),
    )


async def test_s2_international_timezones_buffers_and_stale_price_removal() -> None:
    clock = date(2030, 1, 1)
    outbound = clock + timedelta(days=60)
    fail_upstream = False
    calls = 0

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        if fail_upstream:
            return httpx.Response(429, request=request, json={"error": "fixture limit"})
        first_day = outbound.isoformat()
        connection_day = (outbound + timedelta(days=1)).isoformat()
        arrival_day = (outbound + timedelta(days=2)).isoformat()
        return httpx.Response(
            200,
            request=request,
            json={
                "best_flights": [{
                    "price": 1_200,
                    "total_duration": 1,
                    "flights": [
                        {
                            "departure_airport": {
                                "id": "LAX", "date": first_day, "time": "23:30-08:00",
                            },
                            "arrival_airport": {
                                "id": "YVR", "date": connection_day, "time": "02:00-08:00",
                            },
                            "airline": "Fixture Pacific",
                            "flight_number": "FP100",
                        },
                        {
                            "departure_airport": {
                                "id": "YVR", "date": connection_day, "time": "04:00-08:00",
                            },
                            "arrival_airport": {
                                "id": "HND", "date": arrival_day, "time": "08:00+09:00",
                            },
                            "airline": "Fixture Pacific",
                            "flight_number": "FP200",
                        },
                    ],
                }],
            },
        )

    http = SafeHttpClient(provider="searchapi", timeout_seconds=1, max_attempts=1)
    await http.client.aclose()
    client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    http.client = client
    provider = SearchApiFlightProvider(api_key="fixture-credential", http=http)
    query = FlightSearchQuery(
        departure_id="LAX",
        arrival_id="HND",
        outbound_date=outbound,
        currency="USD",
    )
    try:
        result = await provider.fetch(query)
        option = result.options[0]
        assert option.segments[0].departure_at.utcoffset() == timedelta(hours=-8)
        assert option.segments[-1].arrival_at.utcoffset() == timedelta(hours=9)
        assert option.segments[-1].arrival_at.date() > option.segments[0].departure_at.date()
        assert (option.stops, option.duration_minutes, option.price, option.currency) == (
            1,
            930,
            1_200,
            "USD",
        )

        fingerprint = request_fingerprint("searchapi-flights", query)
        provider.flight_cache.put(
            provider="searchapi",
            fingerprint=fingerprint,
            value=result,
            ttl=timedelta(minutes=15),
            now=datetime.now(UTC) - timedelta(minutes=16),
        )
        fail_upstream = True
        with pytest.raises(ProviderError) as error:
            await provider.fetch(query)
        assert error.value.kind is ProviderErrorKind.RATE_LIMIT
        assert calls == 2
    finally:
        await client.aclose()

    point = _point()
    chosen_base = _base()
    route_a = RouteA(subject_id="328609", points=(point,), is_complete=True)
    coordinates = (
        chosen_base.coordinate,
        GeoCoordinate(latitude=point.latitude, longitude=point.longitude),
    )
    timezone = ZoneInfo("Asia/Tokyo")
    trip_start = outbound + timedelta(days=2)
    late_constraints = PlanningConstraints(
        start_date=trip_start,
        end_date=trip_start + timedelta(days=2),
        arrival_at=datetime.combine(trip_start, time(19), timezone),
        departure_at=datetime.combine(trip_start + timedelta(days=2), time(20), timezone),
        max_walking_meters_per_day=5_000,
    )
    late_plan = build_route_b(
        route_a=route_a,
        base=chosen_base,
        matrix=haversine_matrix(coordinates),
        constraints=late_constraints,
    )
    assert late_plan.days[0].visits == ()
    assert any(day.visits for day in late_plan.days[1:])

    tight_departure = PlanningConstraints(
        start_date=trip_start,
        end_date=trip_start,
        arrival_at=datetime.combine(trip_start, time(6), timezone),
        departure_at=datetime.combine(trip_start, time(10), timezone),
        departure_buffer_minutes=120,
        max_walking_meters_per_day=5_000,
        must_visit_point_ids=frozenset({point.id}),
    )
    tight_plan = build_route_b(
        route_a=route_a,
        base=chosen_base,
        matrix=haversine_matrix(coordinates),
        constraints=tight_departure,
    )
    report = validate_route_b(tight_plan, tight_departure)
    assert not report.valid
    assert "missing_must_visit" in {issue.code for issue in report.issues}


async def test_s3_partial_provider_matrix_weather_and_llm_degradation() -> None:
    def anitabi_handler(request: httpx.Request) -> httpx.Response:
        if request.url.path.endswith("/lite"):
            return httpx.Response(
                200,
                request=request,
                json={"id": 328609, "pointsLength": 2, "imagesLength": 1},
            )
        return httpx.Response(
            200,
            request=request,
            json=[{
                "id": "available-point",
                "name": "Available point",
                "geo": [35.66, 139.66],
                "originURL": "https://example.test/point",
            }],
        )

    anitabi_http = SafeHttpClient(provider="anitabi", timeout_seconds=1, max_attempts=1)
    await anitabi_http.client.aclose()
    anitabi_client = httpx.AsyncClient(transport=httpx.MockTransport(anitabi_handler))
    anitabi_http.client = anitabi_client
    try:
        result = await AnitabiProvider(http=anitabi_http).fetch(
            PilgrimagePointQuery(subject_id="328609")
        )
    finally:
        await anitabi_client.aclose()
    route_a = build_route_a(result, subject_id="328609")
    assert len(route_a.points) == 1
    assert not route_a.is_complete
    assert route_a.warnings

    class RateLimitedMatrix:
        async def matrix(self, _query: MatrixQuery) -> RouteMatrix:
            raise ProviderError(
                ProviderErrorKind.RATE_LIMIT,
                "fixture-ors",
                "fixture rate limit",
                retryable=True,
            )

    query = MatrixQuery(
        coordinates=(
            GeoCoordinate(latitude=35.66, longitude=139.66),
            GeoCoordinate(latitude=35.67, longitude=139.67),
        )
    )
    matrix = await matrix_with_fallback(RateLimitedMatrix(), query)
    assert matrix.provenance.provider == "haversine"
    assert matrix.provenance.status is DataStatus.ESTIMATED

    clock = date(2030, 1, 1)
    weather = await FixtureOpenMeteoProvider(today=lambda: clock).fetch(
        query=WeatherForecastQuery(
            coordinate=GeoCoordinate(latitude=35.66, longitude=139.66),
            start_date=clock + timedelta(days=60),
            end_date=clock + timedelta(days=62),
        )
    )
    assert not weather.available
    assert weather.windows == ()
    assert weather.provenance.status is DataStatus.UNKNOWN

    with pytest.raises(StructuredOutputError):
        parse_reviewer_output(
            lambda _request: "not-json",
            ReviewerInput(
                context_snapshot_id="scenario-s3",
                deterministic_violations=(),
                revision_count=0,
            ),
            max_attempts=2,
        )
