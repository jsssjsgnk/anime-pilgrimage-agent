"""Read-only Open-Meteo forecast provider with explicit horizon handling."""

from __future__ import annotations

from collections.abc import Callable
from datetime import date, timedelta
from typing import Any

from pydantic import TypeAdapter, ValidationError

from pilgrimage_agent.domain.models import (
    DataStatus,
    WeatherForecastQuery,
    WeatherForecastResult,
    WeatherWindow,
)
from pilgrimage_agent.providers.base import ProviderError, ProviderErrorKind
from pilgrimage_agent.providers.cache import MemoryProviderCache, request_fingerprint
from pilgrimage_agent.providers.common import provenance
from pilgrimage_agent.providers.http import SafeHttpClient

_DICT = TypeAdapter(dict[str, Any])


class OpenMeteoProvider:
    provider = "open-meteo"

    def __init__(self, *, http: SafeHttpClient, today: Callable[[], date] = date.today) -> None:
        self.http = http
        self.today = today
        self.cache: MemoryProviderCache[WeatherForecastResult] = MemoryProviderCache()

    async def fetch(self, query: WeatherForecastQuery) -> WeatherForecastResult:
        today = self.today()
        if query.start_date < today or query.end_date > today + timedelta(days=15):
            return WeatherForecastResult(
                windows=(),
                available=False,
                reason="Requested dates are outside the live 16-day forecast window.",
                provenance=provenance(
                    self.provider,
                    "https://open-meteo.com/en/docs",
                    ttl=timedelta(hours=1),
                    status=DataStatus.UNKNOWN,
                ),
            )
        fingerprint = request_fingerprint(self.provider, query)
        cached = self.cache.get(fingerprint)
        if cached is not None:
            return cached
        raw = await self.http.request_json(
            "GET",
            "https://api.open-meteo.com/v1/forecast",
            params={
                "latitude": str(query.coordinate.latitude),
                "longitude": str(query.coordinate.longitude),
                "daily": (
                    "temperature_2m_max,temperature_2m_min,"
                    "precipitation_probability_max,weather_code"
                ),
                "timezone": "auto",
                "start_date": query.start_date.isoformat(),
                "end_date": query.end_date.isoformat(),
            },
        )
        try:
            payload = _DICT.validate_python(raw)
            daily = payload["daily"]
            days = daily["time"]
            lengths = {
                len(days),
                len(daily["temperature_2m_max"]),
                len(daily["temperature_2m_min"]),
                len(daily["precipitation_probability_max"]),
                len(daily["weather_code"]),
            }
            if len(lengths) != 1:
                raise ValueError
            windows = tuple(
                WeatherWindow(
                    date=day,
                    temperature_max_c=daily["temperature_2m_max"][index],
                    temperature_min_c=daily["temperature_2m_min"][index],
                    precipitation_probability_max=daily[
                        "precipitation_probability_max"
                    ][index],
                    weather_code=daily["weather_code"][index],
                )
                for index, day in enumerate(days)
            )
            result = WeatherForecastResult(
                windows=windows,
                available=True,
                provenance=provenance(
                    self.provider,
                    "https://api.open-meteo.com/v1/forecast",
                    ttl=timedelta(hours=1),
                ),
            )
        except (ValidationError, ValueError, KeyError, TypeError):
            raise ProviderError(
                ProviderErrorKind.UPSTREAM,
                self.provider,
                "Open-Meteo returned a response that did not match the expected schema.",
            ) from None
        self.cache.put(
            provider=self.provider,
            fingerprint=fingerprint,
            value=result,
            ttl=timedelta(hours=1),
        )
        return result


class FixtureOpenMeteoProvider:
    provider = "open-meteo-fixture"

    def __init__(self, *, today: Callable[[], date] = date.today) -> None:
        self.today = today

    async def fetch(self, query: WeatherForecastQuery) -> WeatherForecastResult:
        today = self.today()
        prov = provenance(
            self.provider,
            "https://open-meteo.com/en/docs",
            ttl=timedelta(days=365),
        )
        if query.start_date < today or query.end_date > today + timedelta(days=15):
            return WeatherForecastResult(
                windows=(),
                available=False,
                reason="Requested dates are outside the live 16-day forecast window.",
                provenance=prov.model_copy(update={"status": DataStatus.UNKNOWN}),
            )
        windows = tuple(
            WeatherWindow(
                date=query.start_date + timedelta(days=offset),
                temperature_max_c=24.0 + offset,
                temperature_min_c=17.0,
                precipitation_probability_max=20,
                weather_code=1,
            )
            for offset in range((query.end_date - query.start_date).days + 1)
        )
        return WeatherForecastResult(windows=windows, available=True, provenance=prov)
