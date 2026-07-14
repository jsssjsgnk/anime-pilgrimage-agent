"""Provider composition root shared by HTTP API and read-only MCP tools."""

from __future__ import annotations

from functools import lru_cache
from pathlib import Path

from pilgrimage_agent.config import Settings, get_settings
from pilgrimage_agent.providers.anitabi import AnitabiProvider, FixtureAnitabiProvider
from pilgrimage_agent.providers.bangumi import (
    BangumiSubjectProvider,
    FixtureBangumiSubjectProvider,
)
from pilgrimage_agent.providers.http import SafeHttpClient
from pilgrimage_agent.providers.ors import (
    FixtureOpenRouteServiceProvider,
    OpenRouteServiceProvider,
)
from pilgrimage_agent.providers.points import (
    FallbackPilgrimagePointProvider,
    ImportedPilgrimagePointProvider,
)
from pilgrimage_agent.providers.searchapi import (
    FixtureSearchApiFlightProvider,
    SearchApiFlightProvider,
)
from pilgrimage_agent.providers.weather import FixtureOpenMeteoProvider, OpenMeteoProvider

ROOT = Path(__file__).resolve().parents[3]


class ProviderServices:
    """Explicitly select fixture or real read-only providers."""

    def __init__(self, settings: Settings) -> None:
        self.settings = settings
        self.bangumi: FixtureBangumiSubjectProvider | BangumiSubjectProvider
        self.points: (
            FixtureAnitabiProvider
            | FallbackPilgrimagePointProvider
            | ImportedPilgrimagePointProvider
        )
        self.ors: FixtureOpenRouteServiceProvider | OpenRouteServiceProvider
        self.weather: FixtureOpenMeteoProvider | OpenMeteoProvider
        self.flights: FixtureSearchApiFlightProvider | SearchApiFlightProvider
        import_path = settings.pilgrimage_points_import_path
        if not import_path.is_absolute():
            import_path = ROOT / import_path
        if settings.pilgrimage_point_mode == "fixture":
            self.points = FixtureAnitabiProvider(ROOT / "fixtures/providers/points.geojson")
        elif settings.pilgrimage_point_mode == "imported":
            self.points = ImportedPilgrimagePointProvider(import_path)
        else:
            anitabi_http = SafeHttpClient(
                provider="anitabi",
                timeout_seconds=settings.provider_timeout_seconds,
                max_attempts=settings.provider_max_attempts,
            )
            self.points = FallbackPilgrimagePointProvider(
                AnitabiProvider(
                    http=anitabi_http,
                    base_url=settings.anitabi_base_url,
                    user_agent=settings.anitabi_user_agent,
                ),
                ImportedPilgrimagePointProvider(import_path),
            )

        if settings.bangumi_mode == "fixture":
            self.bangumi = FixtureBangumiSubjectProvider()
        else:
            bangumi_http = SafeHttpClient(
                provider="bangumi",
                timeout_seconds=settings.provider_timeout_seconds,
                max_attempts=settings.provider_max_attempts,
            )
            self.bangumi = BangumiSubjectProvider(
                token=(
                    settings.bangumi_access_token.get_secret_value()
                    if settings.bangumi_access_token
                    else None
                ),
                user_agent=settings.bangumi_user_agent,
                http=bangumi_http,
            )

        if settings.provider_mode == "fixture":
            self.ors = FixtureOpenRouteServiceProvider()
            self.weather = FixtureOpenMeteoProvider()
            self.flights = FixtureSearchApiFlightProvider()
            return

        ors_http = SafeHttpClient(
            provider="openrouteservice",
            timeout_seconds=settings.provider_timeout_seconds,
            max_attempts=settings.provider_max_attempts,
        )
        weather_http = SafeHttpClient(
            provider="open-meteo",
            timeout_seconds=settings.provider_timeout_seconds,
            max_attempts=settings.provider_max_attempts,
        )
        searchapi_http = SafeHttpClient(
            provider="searchapi",
            timeout_seconds=settings.provider_timeout_seconds,
            max_attempts=settings.provider_max_attempts,
        )
        self.ors = OpenRouteServiceProvider(
            api_key=settings.ors_api_key.get_secret_value() if settings.ors_api_key else None,
            http=ors_http,
        )
        self.weather = OpenMeteoProvider(http=weather_http)
        self.flights = SearchApiFlightProvider(
            api_key=(
                settings.searchapi_api_key.get_secret_value()
                if settings.searchapi_api_key
                else None
            ),
            http=searchapi_http,
        )


@lru_cache
def get_provider_services() -> ProviderServices:
    return ProviderServices(get_settings())
