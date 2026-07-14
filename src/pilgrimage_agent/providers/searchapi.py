"""Read-only SearchAPI Google Flights and Calendar providers."""

from __future__ import annotations

import hashlib
import json
from datetime import UTC, datetime, timedelta
from typing import Any

from pydantic import TypeAdapter, ValidationError

from pilgrimage_agent.domain.models import (
    FareDateCandidate,
    FlexibleFlightQuery,
    FlexibleFlightResult,
    FlightOption,
    FlightSearchQuery,
    FlightSearchResult,
    FlightSegment,
)
from pilgrimage_agent.providers.base import ProviderError, ProviderErrorKind, missing_credential
from pilgrimage_agent.providers.cache import MemoryProviderCache, request_fingerprint
from pilgrimage_agent.providers.common import provenance
from pilgrimage_agent.providers.http import SafeHttpClient

_DICT = TypeAdapter(dict[str, Any])


class SearchApiFlightProvider:
    provider = "searchapi"

    def __init__(self, *, api_key: str | None, http: SafeHttpClient) -> None:
        self.api_key = api_key
        self.http = http
        self.flight_cache: MemoryProviderCache[FlightSearchResult] = MemoryProviderCache()
        self.calendar_cache: MemoryProviderCache[FlexibleFlightResult] = MemoryProviderCache()

    def _headers(self) -> dict[str, str]:
        if not self.api_key:
            raise missing_credential(self.provider, "SEARCHAPI_API_KEY")
        return {"Authorization": f"Bearer {self.api_key}", "Accept": "application/json"}

    async def fetch(self, query: FlightSearchQuery) -> FlightSearchResult:
        fingerprint = request_fingerprint(f"{self.provider}-flights", query)
        cached = self.flight_cache.get(fingerprint)
        if cached is not None:
            return cached
        params: dict[str, str | int] = {
            "engine": "google_flights",
            "flight_type": "round_trip" if query.return_date else "one_way",
            "departure_id": query.departure_id,
            "arrival_id": query.arrival_id,
            "outbound_date": query.outbound_date.isoformat(),
            "adults": query.adults,
            "travel_class": "first_class" if query.cabin_class == "first" else query.cabin_class,
            "currency": query.currency,
        }
        if query.return_date:
            params["return_date"] = query.return_date.isoformat()
        raw = await self.http.request_json(
            "GET",
            "https://www.searchapi.io/api/v1/search",
            headers=self._headers(),
            params=params,
        )
        try:
            payload = _DICT.validate_python(raw)
            options_raw = [
                *self._list(payload.get("best_flights")),
                *self._list(payload.get("other_flights")),
            ]
            result_provenance = provenance(
                self.provider,
                "https://www.searchapi.io/docs/google-flights-api",
                ttl=timedelta(minutes=15),
            )
            options = tuple(
                self._flight_option(item, query.currency, result_provenance)
                for item in options_raw
                if isinstance(item, dict)
            )
            result = FlightSearchResult(options=options, provenance=result_provenance)
        except (ValidationError, ValueError, KeyError, TypeError):
            raise ProviderError(
                ProviderErrorKind.UPSTREAM,
                self.provider,
                "SearchAPI returned a response that did not match the expected schema.",
            ) from None
        self.flight_cache.put(
            provider=self.provider,
            fingerprint=fingerprint,
            value=result,
            ttl=timedelta(minutes=15),
        )
        return result

    async def flexible(self, query: FlexibleFlightQuery) -> FlexibleFlightResult:
        fingerprint = request_fingerprint(f"{self.provider}-calendar", query)
        cached = self.calendar_cache.get(fingerprint)
        if cached is not None:
            return cached
        params: dict[str, str | int] = {
            "engine": "google_flights_calendar",
            "flight_type": "round_trip" if query.return_start else "one_way",
            "departure_id": query.departure_id,
            "arrival_id": query.arrival_id,
            "outbound_date": query.outbound_start.isoformat(),
            "outbound_date_start": query.outbound_start.isoformat(),
            "outbound_date_end": query.outbound_end.isoformat(),
            "currency": query.currency,
        }
        if query.return_start and query.return_end:
            params.update(
                {
                    "return_date": query.return_start.isoformat(),
                    "return_date_start": query.return_start.isoformat(),
                    "return_date_end": query.return_end.isoformat(),
                }
            )
        raw = await self.http.request_json(
            "GET",
            "https://www.searchapi.io/api/v1/search",
            headers=self._headers(),
            params=params,
        )
        try:
            payload = _DICT.validate_python(raw)
            result_provenance = provenance(
                self.provider,
                "https://www.searchapi.io/docs/google-flights-calendar-api",
                ttl=timedelta(minutes=15),
            )
            candidates = tuple(
                FareDateCandidate(
                    outbound_date=item["departure"],
                    return_date=item.get("return"),
                    price=item.get("price"),
                    currency=query.currency,
                    has_no_flights=bool(item.get("has_no_flights", False)),
                )
                for item in self._list(payload.get("calendar"))
                if isinstance(item, dict)
            )
            result = FlexibleFlightResult(candidates=candidates, provenance=result_provenance)
        except (ValidationError, ValueError, KeyError, TypeError):
            raise ProviderError(
                ProviderErrorKind.UPSTREAM,
                self.provider,
                "SearchAPI calendar data did not match the expected schema.",
            ) from None
        self.calendar_cache.put(
            provider=self.provider,
            fingerprint=fingerprint,
            value=result,
            ttl=timedelta(minutes=15),
        )
        return result

    @staticmethod
    def _list(value: Any) -> list[Any]:
        return value if isinstance(value, list) else []

    @classmethod
    def _flight_option(
        cls,
        item: dict[str, Any],
        currency: str,
        item_provenance: Any,
    ) -> FlightOption:
        flights = cls._list(item.get("flights"))
        segments = tuple(cls._segment(segment) for segment in flights if isinstance(segment, dict))
        if not segments:
            raise ValueError
        stable = json.dumps(
            {
                "segments": [segment.model_dump(mode="json") for segment in segments],
                "price": item["price"],
            },
            sort_keys=True,
        )
        duration = int(
            (segments[-1].arrival_at - segments[0].departure_at).total_seconds() // 60
        )
        return FlightOption(
            option_id=hashlib.sha256(stable.encode()).hexdigest()[:20],
            price=item["price"],
            currency=currency,
            duration_minutes=duration,
            stops=max(0, len(segments) - 1),
            segments=segments,
            confirmation_url=None,
            provenance=item_provenance,
        )

    @staticmethod
    def _segment(item: dict[str, Any]) -> FlightSegment:
        departure = item["departure_airport"]
        arrival = item["arrival_airport"]
        if not isinstance(departure, dict) or not isinstance(arrival, dict):
            raise ValueError
        carrier = item.get("airline", item.get("airline_logo", "Unknown carrier"))
        return FlightSegment(
            departure_airport=str(departure.get("id", departure.get("name"))),
            arrival_airport=str(arrival.get("id", arrival.get("name"))),
            departure_at=SearchApiFlightProvider._airport_datetime(departure),
            arrival_at=SearchApiFlightProvider._airport_datetime(arrival),
            carrier=str(carrier),
            flight_number=str(item["flight_number"]) if item.get("flight_number") else None,
        )

    @staticmethod
    def _datetime(value: Any) -> datetime:
        parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
        return parsed if parsed.tzinfo else parsed.replace(tzinfo=UTC)

    @staticmethod
    def _airport_datetime(airport: dict[str, Any]) -> datetime:
        date_value = airport.get("date")
        time_value = airport["time"]
        combined = f"{date_value}T{time_value}" if date_value else time_value
        return SearchApiFlightProvider._datetime(combined)


class FixtureSearchApiFlightProvider:
    provider = "searchapi-fixture"

    async def fetch(self, query: FlightSearchQuery) -> FlightSearchResult:
        prov = provenance(
            self.provider,
            "https://www.searchapi.io/docs/google-flights-api",
            ttl=timedelta(minutes=15),
        )
        departure = datetime.combine(query.outbound_date, datetime.min.time(), UTC).replace(hour=9)
        option = FlightOption(
            option_id="fixture-hnd-itm-001",
            price=18_400,
            currency=query.currency,
            duration_minutes=70,
            stops=0,
            segments=(
                FlightSegment(
                    departure_airport=query.departure_id,
                    arrival_airport=query.arrival_id,
                    departure_at=departure,
                    arrival_at=departure + timedelta(minutes=70),
                    carrier="Fixture Air",
                    flight_number="FX101",
                ),
            ),
            provenance=prov,
        )
        return FlightSearchResult(options=(option,), provenance=prov)

    async def flexible(self, query: FlexibleFlightQuery) -> FlexibleFlightResult:
        prov = provenance(
            self.provider,
            "https://www.searchapi.io/docs/google-flights-calendar-api",
            ttl=timedelta(minutes=15),
        )
        return FlexibleFlightResult(
            candidates=(
                FareDateCandidate(
                    outbound_date=query.outbound_start,
                    return_date=query.return_start,
                    price=17_900,
                    currency=query.currency,
                ),
            ),
            provenance=prov,
        )
