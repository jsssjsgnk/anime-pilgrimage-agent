"""Run bounded credential-safe, read-only requests for Phase 2 external Providers."""

from __future__ import annotations

import asyncio
from datetime import date, timedelta

from pilgrimage_agent.config import get_settings
from pilgrimage_agent.domain.models import (
    FlightSearchQuery,
    GeoCoordinate,
    PilgrimagePointQuery,
    PlaceSearchQuery,
    SubjectSearchQuery,
    WeatherForecastQuery,
)
from pilgrimage_agent.providers.base import ProviderError, ProviderErrorKind
from pilgrimage_agent.providers.service import ProviderServices


async def main_async() -> int:
    settings = get_settings()
    services = ProviderServices(
        settings.model_copy(
            update={"provider_mode": "live", "pilgrimage_point_mode": "anitabi"}
        )
    )
    today = date.today()
    failures: list[str] = []

    try:
        anitabi = await services.points.fetch(
            PilgrimagePointQuery(subject_id="328609", provider="anitabi")
        )
    except ProviderError as error:
        failures.append("Anitabi")
        print(f"FAIL Anitabi: {error.kind.value} ({error.safe_message})")
    else:
        if anitabi.provenance.provider != "anitabi" or not anitabi.points:
            failures.append("Anitabi")
            print("FAIL Anitabi: live response was empty or used the import fallback")
        elif not anitabi.is_complete and not anitabi.warnings:
            failures.append("Anitabi")
            print("FAIL Anitabi: partial data lacked an explicit warning")
        else:
            scope = "complete" if anitabi.is_complete else "explicitly partial"
            print(f"PASS Anitabi: {len(anitabi.points)} {scope} sourced points")

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
            settings.capability_status()["searchapi"] and settings.searchapi_live_smoke,
            services.flights.fetch(
                FlightSearchQuery(
                    departure_id="HND",
                    arrival_id="ITM",
                    outbound_date=today + timedelta(days=60),
                )
            ),
        ),
    ]
    transient_kinds = {
        ProviderErrorKind.QUOTA,
        ProviderErrorKind.RATE_LIMIT,
        ProviderErrorKind.TIMEOUT,
        ProviderErrorKind.UPSTREAM,
    }
    for name, enabled, operation in checks:
        if not enabled:
            operation.close()
            print(f"SKIP {name}: live smoke disabled or credential not configured")
            continue
        try:
            await operation
        except ProviderError as error:
            if error.kind in transient_kinds:
                print(
                    f"DEGRADED {name}: normalized {error.kind.value} "
                    f"({error.safe_message})"
                )
            else:
                failures.append(name)
                print(f"FAIL {name}: {error.kind.value} ({error.safe_message})")
        else:
            print(f"PASS {name}: one read-only request")
    searchapi_count = (
        1
        if settings.capability_status()["searchapi"] and settings.searchapi_live_smoke
        else 0
    )
    print(f"SearchAPI live request count: {searchapi_count}")
    return 1 if failures else 0


def main() -> int:
    return asyncio.run(main_async())


if __name__ == "__main__":
    raise SystemExit(main())
