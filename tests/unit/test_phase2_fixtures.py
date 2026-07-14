"""Exercise every Phase 2 fixture implementation and deterministic cache policy."""

from datetime import UTC, date, datetime, timedelta
from pathlib import Path

import pytest

from pilgrimage_agent.config import Settings
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
from pilgrimage_agent.providers.anitabi import FixtureAnitabiProvider
from pilgrimage_agent.providers.bangumi import (
    BangumiSubjectProvider,
    FixtureBangumiSubjectProvider,
)
from pilgrimage_agent.providers.base import ProviderError, ProviderErrorKind
from pilgrimage_agent.providers.cache import MemoryProviderCache, request_fingerprint
from pilgrimage_agent.providers.ors import (
    FixtureOpenRouteServiceProvider,
    OpenRouteServiceProvider,
)
from pilgrimage_agent.providers.points import build_route_a
from pilgrimage_agent.providers.searchapi import (
    FixtureSearchApiFlightProvider,
    SearchApiFlightProvider,
)
from pilgrimage_agent.providers.service import ProviderServices
from pilgrimage_agent.providers.weather import FixtureOpenMeteoProvider, OpenMeteoProvider


async def test_bangumi_fixture_success_empty_and_not_found() -> None:
    provider = FixtureBangumiSubjectProvider()
    success = await provider.fetch(SubjectSearchQuery(query="孤独摇滚"))
    empty = await provider.fetch(SubjectSearchQuery(query="unrelated"))
    confirmed = await provider.get_subject("328609")
    assert success.candidates[0].subject_id == confirmed.subject_id
    assert empty.candidates == ()
    with pytest.raises(ProviderError) as raised:
        await provider.get_subject("missing")
    assert raised.value.kind is ProviderErrorKind.NOT_FOUND


async def test_route_fixture_and_ors_fixture_contracts() -> None:
    point_provider = FixtureAnitabiProvider(Path("unused"))
    imported = await point_provider.fetch(
        PilgrimagePointQuery(subject_id="328609", provider="fixture")
    )
    route = build_route_a(imported, subject_id="328609")
    assert len(route.points) == 3
    assert all(point.provenance.source_url for point in route.points)

    ors = FixtureOpenRouteServiceProvider()
    hit = await ors.geocode(PlaceSearchQuery(text="下北沢"))
    empty = await ors.geocode(PlaceSearchQuery(text="unrelated"))
    coordinates = tuple(
        GeoCoordinate(latitude=35.66 + offset / 100, longitude=139.66 + offset / 100)
        for offset in range(3)
    )
    directions = await ors.directions(DirectionsQuery(coordinates=coordinates))
    matrix = await ors.matrix(MatrixQuery(coordinates=coordinates))
    assert len(hit.candidates) == 1 and empty.candidates == ()
    assert directions.duration_seconds == 660
    assert matrix.distances_meters[0][2] == 1500


async def test_weather_and_flight_fixtures_use_relative_clock() -> None:
    clock = date(2030, 3, 1)
    weather = FixtureOpenMeteoProvider(today=lambda: clock)
    coordinate = GeoCoordinate(latitude=35.66, longitude=139.66)
    live = await weather.fetch(
        WeatherForecastQuery(
            coordinate=coordinate,
            start_date=clock,
            end_date=clock + timedelta(days=2),
        )
    )
    unknown = await weather.fetch(
        WeatherForecastQuery(
            coordinate=coordinate,
            start_date=clock + timedelta(days=20),
            end_date=clock + timedelta(days=20),
        )
    )
    assert len(live.windows) == 3
    assert not unknown.available

    flights = FixtureSearchApiFlightProvider()
    options = await flights.fetch(
        FlightSearchQuery(
            departure_id="HND",
            arrival_id="ITM",
            outbound_date=clock + timedelta(days=60),
        )
    )
    calendar = await flights.flexible(
        FlexibleFlightQuery(
            departure_id="HND",
            arrival_id="ITM",
            outbound_start=clock + timedelta(days=60),
            outbound_end=clock + timedelta(days=61),
        )
    )
    assert options.requires_reconfirmation
    assert options.options[0].segments[0].departure_airport == "HND"
    assert calendar.candidates[0].price == 17_900


def test_fixture_service_composition_and_bounded_cache() -> None:
    services = ProviderServices(
        Settings(
            _env_file=None,
            DATABASE_URL="postgresql+asyncpg://fixture:fixture@localhost/fixture",
            provider_mode="fixture",
        )
    )
    assert isinstance(services.bangumi, FixtureBangumiSubjectProvider)
    assert isinstance(services.points, FixtureAnitabiProvider)
    assert isinstance(services.ors, FixtureOpenRouteServiceProvider)

    cache: MemoryProviderCache[str] = MemoryProviderCache(max_items=1)
    now = datetime(2030, 1, 1, tzinfo=UTC)
    first_query = SubjectSearchQuery(query="first")
    second_query = SubjectSearchQuery(query="second")
    first = request_fingerprint("fixture", first_query)
    second = request_fingerprint("fixture", second_query)
    cache.put(
        provider="fixture",
        fingerprint=first,
        value="first",
        ttl=timedelta(minutes=1),
        now=now,
    )
    assert cache.get(first, now=now) == "first"
    cache.put(
        provider="fixture",
        fingerprint=second,
        value="second",
        ttl=timedelta(minutes=1),
        now=now,
    )
    assert cache.get(first, now=now) is None
    assert cache.get(second, now=now + timedelta(minutes=2)) is None


def test_live_bangumi_mode_is_independent_from_other_provider_fixtures() -> None:
    services = ProviderServices(
        Settings(
            _env_file=None,
            provider_mode="fixture",
            BANGUMI_MODE="live",
            BANGUMI_USER_AGENT="fixture-agent/1.0",
        )
    )

    assert isinstance(services.bangumi, BangumiSubjectProvider)
    assert isinstance(services.ors, FixtureOpenRouteServiceProvider)
    assert isinstance(services.weather, FixtureOpenMeteoProvider)
    assert isinstance(services.flights, FixtureSearchApiFlightProvider)


def test_uppercase_live_mode_composes_real_provider_implementations(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("PROVIDER_MODE", "live")
    monkeypatch.setenv("BANGUMI_MODE", "live")
    monkeypatch.setenv("BANGUMI_ACCESS_TOKEN", "contract-sentinel")
    monkeypatch.setenv("ORS_API_KEY", "contract-sentinel")
    monkeypatch.setenv("SEARCHAPI_API_KEY", "contract-sentinel")
    settings = Settings(_env_file=None, PILGRIMAGE_POINT_MODE="fixture")

    services = ProviderServices(settings)

    assert settings.provider_mode == "live"
    assert settings.bangumi_mode == "live"
    assert isinstance(services.bangumi, BangumiSubjectProvider)
    assert isinstance(services.ors, OpenRouteServiceProvider)
    assert isinstance(services.weather, OpenMeteoProvider)
    assert isinstance(services.flights, SearchApiFlightProvider)
