"""Run at most one credential-safe, read-only request per Phase 2 external provider."""

from __future__ import annotations

import asyncio
from datetime import date, timedelta

from pilgrimage_agent.config import get_settings
from pilgrimage_agent.domain.models import (
    FlightSearchQuery,
    GeoCoordinate,
    PlaceSearchQuery,
    SubjectSearchQuery,
    WeatherForecastQuery,
)
from pilgrimage_agent.providers.base import ProviderError
from pilgrimage_agent.providers.service import ProviderServices


async def main_async() -> int:
    settings = get_settings()
    services = ProviderServices(settings.model_copy(update={"provider_mode": "live"}))
    today = date.today()
    failures: list[str] = []

    checks = [
        (
            "Bangumi",
            settings.capability_status()["bangumi"],
            services.bangumi.fetch(SubjectSearchQuery(query="孤独摇滚", limit=1)),
        ),
        (
            "openrouteservice",
            settings.capability_status()["ors"],
            services.ors.geocode(PlaceSearchQuery(text="下北沢", limit=1)),
        ),
        (
            "Open-Meteo",
            True,
            services.weather.fetch(
                WeatherForecastQuery(
                    coordinate=GeoCoordinate(latitude=35.66, longitude=139.66),
                    start_date=today + timedelta(days=1),
                    end_date=today + timedelta(days=1),
                )
            ),
        ),
        (
            "SearchAPI",
            settings.capability_status()["searchapi"],
            services.flights.fetch(
                FlightSearchQuery(
                    departure_id="HND",
                    arrival_id="ITM",
                    outbound_date=today + timedelta(days=60),
                )
            ),
        ),
    ]
    for name, enabled, operation in checks:
        if not enabled:
            operation.close()
            print(f"SKIP {name}: credential not configured")
            continue
        try:
            await operation
        except ProviderError as error:
            failures.append(name)
            print(f"FAIL {name}: {error.kind.value} ({error.safe_message})")
        else:
            print(f"PASS {name}: one read-only request")
    searchapi_count = 1 if settings.capability_status()["searchapi"] else 0
    print(f"SearchAPI live request count: {searchapi_count}")
    return 1 if failures else 0


def main() -> int:
    return asyncio.run(main_async())


if __name__ == "__main__":
    raise SystemExit(main())
