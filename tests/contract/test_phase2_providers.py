"""Phase 2 provider contract tests: typed success, empty, and normalized failures."""

from __future__ import annotations

from datetime import date, timedelta
from typing import Any

import httpx
import pytest

from pilgrimage_agent.domain.models import (
    DirectionsQuery,
    FlexibleFlightQuery,
    FlightSearchQuery,
    GeoCoordinate,
    MatrixQuery,
    PilgrimagePointQuery,
    PlaceSearchQuery,
    SubjectSearchQuery,
    WeatherForecastQuery,
)
from pilgrimage_agent.providers.anitabi import AnitabiProvider
from pilgrimage_agent.providers.bangumi import BangumiSubjectProvider
from pilgrimage_agent.providers.base import ProviderError, ProviderErrorKind
from pilgrimage_agent.providers.http import SafeHttpClient
from pilgrimage_agent.providers.ors import OpenRouteServiceProvider
from pilgrimage_agent.providers.points import ImportedPilgrimagePointProvider, build_route_a
from pilgrimage_agent.providers.searchapi import SearchApiFlightProvider
from pilgrimage_agent.providers.weather import OpenMeteoProvider


def json_response(request: httpx.Request, payload: Any, status: int = 200) -> httpx.Response:
    return httpx.Response(status, request=request, json=payload)


def transport_client(
    provider: str,
    handler: Any,
    *,
    attempts: int = 1,
) -> tuple[SafeHttpClient, httpx.AsyncClient]:
    client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    return (
        SafeHttpClient(
            provider=provider,
            timeout_seconds=0.2,
            max_attempts=attempts,
            client=client,
        ),
        client,
    )


@pytest.mark.parametrize(
    ("mode", "kind", "attempts"),
    [
        ("429", ProviderErrorKind.RATE_LIMIT, 2),
        ("timeout", ProviderErrorKind.TIMEOUT, 2),
        ("invalid_json", ProviderErrorKind.UPSTREAM, 1),
    ],
)
async def test_safe_http_normalizes_failures(
    mode: str,
    kind: ProviderErrorKind,
    attempts: int,
) -> None:
    calls = 0

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        if mode == "timeout":
            raise httpx.ReadTimeout("fixture timeout", request=request)
        if mode == "429":
            return httpx.Response(429, request=request)
        return httpx.Response(200, request=request, text="not-json")

    http, client = transport_client("fixture", handler, attempts=attempts)
    try:
        with pytest.raises(ProviderError) as raised:
            await http.request_json("GET", "https://fixture.invalid/data")
    finally:
        await client.aclose()
    assert raised.value.kind is kind
    assert calls == attempts


@pytest.mark.parametrize("items", [[], [{"id": 328609, "name": "Bocchi", "name_cn": "孤独摇滚"}]])
async def test_bangumi_contract_supports_empty_and_success(items: list[dict[str, Any]]) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.method == "POST"
        assert request.headers.get("user-agent") == "fixture-app/1.0"
        assert request.headers.get("authorization") == "Bearer fixture-credential"
        return json_response(request, {"data": items})

    http, client = transport_client("bangumi", handler)
    provider = BangumiSubjectProvider(
        token="fixture-credential",  # noqa: S106 - explicit non-secret test sentinel
        user_agent="fixture-app/1.0",
        http=http,
    )
    try:
        result = await provider.fetch(SubjectSearchQuery(query="Bocchi", limit=5))
    finally:
        await client.aclose()
    assert len(result.candidates) == len(items)
    assert all(candidate.provenance.source_url for candidate in result.candidates)


async def test_anitabi_contract_fetches_complete_points_and_reuses_cache() -> None:
    calls = 0

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        assert request.method == "GET"
        assert request.headers.get("user-agent") == "fixture-app/1.0"
        if request.url.path.endswith("/lite"):
            return json_response(
                request,
                {"id": 328609, "modified": 1_700_000_000_000, "pointsLength": 2},
            )
        return json_response(
            request,
            [
                {
                    "id": "point-a",
                    "cn": "下北泽站口",
                    "name": "下北沢駅前",
                    "ep": 1,
                    "s": 62,
                    "geo": [35.6615, 139.6670],
                    "image": "https://image.anitabi.cn/points/328609/point-a.jpg?plan=h160",
                    "origin": "Official fixture source",
                    "originURL": "https://example.org/source-a",
                },
                {
                    "id": "point-b",
                    "name": "Shelter",
                    "ep": "OP",
                    "geo": [35.6618, 139.6678],
                },
            ],
        )

    http, client = transport_client("anitabi", handler)
    provider = AnitabiProvider(http=http, user_agent="fixture-app/1.0")
    query = PilgrimagePointQuery(subject_id="328609", provider="anitabi")
    try:
        first = await provider.fetch(query)
        second = await provider.fetch(query)
    finally:
        await client.aclose()
    assert calls == 2
    assert first == second
    assert first.is_complete
    assert len(first.points) == 2
    assert first.points[0].source_label == "Official fixture source"
    assert str(first.points[0].image_url).endswith("point-a.jpg?plan=h160")
    assert str(first.points[0].provenance.source_url) == "https://example.org/source-a"
    assert first.points[1].latitude == 35.6618
    assert "OP" in first.points[1].episode_refs[0]


async def test_anitabi_contract_marks_count_mismatch_and_invalid_points_partial() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path.endswith("/lite"):
            return json_response(request, {"id": 328609, "pointsLength": 3})
        return json_response(
            request,
            [
                {"id": "valid", "name": "Valid", "geo": [35.66, 139.66]},
                {"id": "invalid", "name": "Invalid", "geo": [135.66, 139.66]},
            ],
        )

    http, client = transport_client("anitabi", handler)
    provider = AnitabiProvider(http=http)
    try:
        result = await provider.fetch(
            PilgrimagePointQuery(subject_id="328609", provider="anitabi")
        )
    finally:
        await client.aclose()
    assert not result.is_complete
    assert len(result.points) == 1
    assert any("screenshot-detail count" in warning for warning in result.warnings)
    assert any("invalid Anitabi point" in warning for warning in result.warnings)


async def test_anitabi_contract_discloses_documented_detail_subset() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path.endswith("/lite"):
            return json_response(
                request,
                {"id": 328609, "pointsLength": 414, "imagesLength": 1},
            )
        return json_response(
            request,
            [{"id": "detailed", "name": "Detailed", "geo": [35.66, 139.66]}],
        )

    http, client = transport_client("anitabi", handler)
    try:
        result = await AnitabiProvider(http=http).fetch(
            PilgrimagePointQuery(subject_id="328609", provider="anitabi")
        )
    finally:
        await client.aclose()
    assert not result.is_complete
    assert len(result.points) == 1
    assert any("414 total map points" in warning for warning in result.warnings)


async def test_ors_contract_uses_longitude_latitude_and_normalizes_all_outputs() -> None:
    seen_bodies: list[dict[str, Any]] = []

    def handler(request: httpx.Request) -> httpx.Response:
        if request.method == "POST":
            seen_bodies.append(__import__("json").loads(request.content))
        if "geocode" in str(request.url):
            return json_response(
                request,
                {
                    "features": [
                        {
                            "geometry": {"coordinates": [139.66, 35.66]},
                            "properties": {"label": "下北沢", "region": "東京", "country": "日本"},
                        }
                    ]
                },
            )
        if "/directions/" in str(request.url):
            return json_response(
                request,
                {"routes": [{"summary": {"distance": 800, "duration": 600}, "geometry": "x"}]},
            )
        return json_response(
            request,
            {"durations": [[0, 600], [600, 0]], "distances": [[0, 800], [800, 0]]},
        )

    http, client = transport_client("openrouteservice", handler)
    provider = OpenRouteServiceProvider(api_key="fixture-credential", http=http)
    coordinates = (
        GeoCoordinate(latitude=35.66, longitude=139.66),
        GeoCoordinate(latitude=35.67, longitude=139.67),
    )
    try:
        places = await provider.geocode(PlaceSearchQuery(text="下北沢"))
        leg = await provider.directions(DirectionsQuery(coordinates=coordinates))
        matrix = await provider.matrix(MatrixQuery(coordinates=coordinates))
    finally:
        await client.aclose()
    assert places.candidates[0].coordinate.longitude == 139.66
    assert leg.distance_meters == 800
    assert matrix.durations_seconds[0][1] == 600
    assert seen_bodies[0]["coordinates"][0] == [139.66, 35.66]
    assert seen_bodies[1]["locations"][0] == [139.66, 35.66]


async def test_weather_contract_handles_live_and_out_of_range_without_invention() -> None:
    clock = date(2030, 1, 1)

    def handler(request: httpx.Request) -> httpx.Response:
        return json_response(
            request,
            {
                "daily": {
                    "time": ["2030-01-02"],
                    "temperature_2m_max": [12.0],
                    "temperature_2m_min": [4.0],
                    "precipitation_probability_max": [30],
                    "weather_code": [2],
                }
            },
        )

    http, client = transport_client("open-meteo", handler)
    provider = OpenMeteoProvider(http=http, today=lambda: clock)
    coordinate = GeoCoordinate(latitude=35.66, longitude=139.66)
    try:
        live = await provider.fetch(
            WeatherForecastQuery(
                coordinate=coordinate,
                start_date=clock + timedelta(days=1),
                end_date=clock + timedelta(days=1),
            )
        )
        unknown = await provider.fetch(
            WeatherForecastQuery(
                coordinate=coordinate,
                start_date=clock + timedelta(days=30),
                end_date=clock + timedelta(days=30),
            )
        )
    finally:
        await client.aclose()
    assert live.available and live.windows[0].temperature_max_c == 12
    assert not unknown.available and unknown.windows == ()


async def test_searchapi_contract_never_sends_credential_in_query_or_follows_booking() -> None:
    calls = 0

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        assert "api_key" not in request.url.params
        assert request.headers.get("authorization") == "Bearer fixture-credential"
        if request.url.params["engine"] == "google_flights_calendar":
            return json_response(
                request,
                {"calendar": [{"departure": "2030-02-01", "return": "2030-02-03", "price": 19000}]},
            )
        return json_response(
            request,
            {
                "best_flights": [
                    {
                        "price": 18400,
                        "total_duration": 70,
                        "booking_token": "must-not-be-returned",
                        "flights": [
                            {
                                "departure_airport": {
                                    "id": "HND",
                                    "date": "2030-02-01",
                                    "time": "09:00",
                                },
                                "arrival_airport": {
                                    "id": "ITM",
                                    "date": "2030-02-01",
                                    "time": "10:10",
                                },
                                "airline": "Fixture Air",
                                "flight_number": "FX101",
                            }
                        ],
                    }
                ]
            },
        )

    http, client = transport_client("searchapi", handler)
    provider = SearchApiFlightProvider(api_key="fixture-credential", http=http)
    try:
        flights = await provider.fetch(
            FlightSearchQuery(
                departure_id="HND",
                arrival_id="ITM",
                outbound_date=date(2030, 2, 1),
            )
        )
        calendar = await provider.flexible(
            FlexibleFlightQuery(
                departure_id="HND",
                arrival_id="ITM",
                outbound_start=date(2030, 2, 1),
                outbound_end=date(2030, 2, 2),
                return_start=date(2030, 2, 3),
                return_end=date(2030, 2, 4),
            )
        )
    finally:
        await client.aclose()
    assert calls == 2
    assert flights.options[0].confirmation_url is None
    assert flights.options[0].segments[0].departure_at.hour == 9
    assert "must-not-be-returned" not in flights.model_dump_json()
    assert calendar.candidates[0].price == 19000


def test_imported_points_drop_invalid_and_route_a_deduplicates_with_sources(tmp_path: Any) -> None:
    provider = ImportedPilgrimagePointProvider(tmp_path / "unused.json")
    raw = {
        "points": [
            {
                "subject_id": "328609",
                "name": "Valid point",
                "latitude": 35.66,
                "longitude": 139.66,
                "confidence": "verified",
                "source_url": "https://example.org/source",
            },
            {
                "subject_id": "328609",
                "name": "Valid point",
                "latitude": 35.66,
                "longitude": 139.66,
                "confidence": "verified",
                "source_url": "https://example.org/source-2",
            },
            {
                "subject_id": "328609",
                "name": "Invalid coordinate",
                "latitude": 135.66,
                "longitude": 139.66,
                "source_url": "https://example.org/source-3",
            },
            {
                "subject_id": "328609",
                "name": "Missing source",
                "latitude": 35.67,
                "longitude": 139.67,
            },
        ]
    }
    imported = provider.parse(
        raw,
        query=PilgrimagePointQuery(subject_id="328609"),
        import_label="contract.json",
    )
    route = build_route_a(imported, subject_id="328609")
    assert len(imported.points) == 2
    assert len(route.points) == 1
    assert route.points[0].provenance.source_url is not None
    assert not route.is_complete
    assert any("duplicate" in warning.lower() for warning in route.warnings)
