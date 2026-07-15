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
            update={
                "provider_mode": "live",
                "bangumi_mode": "live",
                "pilgrimage_point_mode": "anitabi",
            }
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
        if anitabi.provenance.provider != "anitabi_static" or not anitabi.points:
            failures.append("Anitabi")
            print("FAIL Anitabi: live response was empty or missed the static source")
        elif (
            not anitabi.is_complete
            or anitabi.loaded_count != anitabi.expected_count
            or anitabi.loaded_count < 400
        ):
            failures.append("Anitabi")
            print(
                "FAIL Anitabi: static collection was incomplete "
                f"({anitabi.loaded_count}/{anitabi.expected_count})"
            )
        else:
            print(
                "PASS Anitabi: "
                f"{anitabi.loaded_count}/{anitabi.expected_count} complete static points"
            )

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
    print(
        "UNVERIFIED SearchAPI transit/place live endpoints: fixture contracts passed, "
        "but this bounded smoke intentionally spends at most one SearchAPI request."
    )
    return 1 if failures else 0


def main() -> int:
    return asyncio.run(main_async())


if __name__ == "__main__":
    raise SystemExit(main())
