"""Read-only SearchAPI Google Flights and Calendar providers."""

from __future__ import annotations

import hashlib
import json
import re
from datetime import UTC, datetime, time, timedelta
from difflib import SequenceMatcher
from typing import Any
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from pydantic import TypeAdapter, ValidationError

from pilgrimage_agent.domain.models import (
    FareDateCandidate,
    FlexibleFlightQuery,
    FlexibleFlightResult,
    FlightOption,
    FlightSearchQuery,
    FlightSearchResult,
    FlightSegment,
    GeoCoordinate,
    OpeningWindow,
    PlaceDetailsQuery,
    PlaceFact,
    PlaceFactsResult,
    PlaceFactsSearchQuery,
    TransitOption,
    TransitRouteQuery,
    TransitRouteResult,
    TransitStep,
    TransitStop,
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
        self.transit_cache: MemoryProviderCache[TransitRouteResult] = MemoryProviderCache()
        self.place_search_cache: MemoryProviderCache[PlaceFactsResult] = MemoryProviderCache()
        self.place_detail_cache: MemoryProviderCache[PlaceFactsResult] = MemoryProviderCache()

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

    async def transit(self, query: TransitRouteQuery) -> TransitRouteResult:
        """Fetch one waypoint-free public-transport edge and normalize its steps."""

        fingerprint = request_fingerprint(f"{self.provider}-transit", query)
        cached = self.transit_cache.get(fingerprint)
        if cached is not None:
            return cached
        if query.time_mode == "last_available":
            time_parameter = "last_available"
        else:
            if query.at is None:  # guarded by TransitRouteQuery validation
                raise ValueError("transit timestamp is required")
            time_parameter = f"{query.time_mode}:{int(query.at.timestamp())}"
        params: dict[str, str] = {
            "engine": "google_maps_directions",
            "start_addr": query.origin,
            "end_addr": query.destination,
            "travel_mode": "transit",
            "time": time_parameter,
            "route": query.route,
            "hl": query.language,
            "gl": query.country,
        }
        if query.prefer:
            params["prefer"] = ",".join(query.prefer)
        raw = await self.http.request_json(
            "GET",
            "https://www.searchapi.io/api/v1/search",
            headers=self._headers(),
            params=params,
        )
        try:
            payload = _DICT.validate_python(raw)
            prov = provenance(
                self.provider,
                "https://www.searchapi.io/docs/google-maps-directions-api",
                ttl=timedelta(minutes=10),
            )
            options = tuple(
                self._transit_option(item, query, prov)
                for item in self._list(payload.get("directions"))
                if isinstance(item, dict)
            )
            result = TransitRouteResult(
                options=options,
                warnings=(
                    ()
                    if options
                    else (
                        "No public-transport option was returned; no schedule was inferred.",
                    )
                ),
                provenance=prov,
            )
        except (ValidationError, ValueError, KeyError, TypeError, ZoneInfoNotFoundError):
            raise ProviderError(
                ProviderErrorKind.UPSTREAM,
                self.provider,
                "SearchAPI transit data did not match the expected schema.",
            ) from None
        self.transit_cache.put(
            provider=self.provider,
            fingerprint=fingerprint,
            value=result,
            ttl=timedelta(minutes=10),
        )
        return result

    async def search_places(self, query: PlaceFactsSearchQuery) -> PlaceFactsResult:
        """Search place candidates without silently converting a name match to a fact."""

        fingerprint = request_fingerprint(f"{self.provider}-place-search", query)
        cached = self.place_search_cache.get(fingerprint)
        if cached is not None:
            return cached
        params: dict[str, str] = {
            "engine": "google_maps",
            "q": query.query,
            "hl": query.language,
            "gl": query.country,
        }
        if query.coordinate_hint is not None:
            params["ll"] = (
                f"@{query.coordinate_hint.latitude},{query.coordinate_hint.longitude},"
                f"{query.zoom}z"
            )
        raw = await self.http.request_json(
            "GET",
            "https://www.searchapi.io/api/v1/search",
            headers=self._headers(),
            params=params,
        )
        try:
            payload = _DICT.validate_python(raw)
            prov = provenance(
                self.provider,
                "https://www.searchapi.io/docs/google-maps",
                ttl=timedelta(hours=6),
            )
            candidates = tuple(
                self._place_fact(item, prov, query_text=query.query, exact=False)
                for item in self._list(payload.get("local_results"))[: query.limit]
                if isinstance(item, dict)
                and (item.get("place_id") or item.get("data_id"))
                and item.get("title")
            )
            result = PlaceFactsResult(
                candidates=candidates,
                warnings=(
                    ()
                    if candidates
                    else ("No matching place fact was returned; the place remains unknown.",)
                ),
                provenance=prov,
            )
        except (ValidationError, ValueError, KeyError, TypeError):
            raise ProviderError(
                ProviderErrorKind.UPSTREAM,
                self.provider,
                "SearchAPI place search data did not match the expected schema.",
            ) from None
        self.place_search_cache.put(
            provider=self.provider,
            fingerprint=fingerprint,
            value=result,
            ttl=timedelta(hours=6),
        )
        return result

    async def place_details(self, query: PlaceDetailsQuery) -> PlaceFactsResult:
        """Fetch exact details for an already selected provider place identifier."""

        fingerprint = request_fingerprint(f"{self.provider}-place-detail", query)
        cached = self.place_detail_cache.get(fingerprint)
        if cached is not None:
            return cached
        params: dict[str, str] = {
            "engine": "google_maps_place",
            "hl": query.language,
            "gl": query.country,
        }
        if query.place_id is not None:
            params["place_id"] = query.place_id
        if query.data_id is not None:
            params["data_id"] = query.data_id
        raw = await self.http.request_json(
            "GET",
            "https://www.searchapi.io/api/v1/search",
            headers=self._headers(),
            params=params,
        )
        try:
            payload = _DICT.validate_python(raw)
            raw_place = payload.get("place_result")
            prov = provenance(
                self.provider,
                "https://www.searchapi.io/docs/google-maps-place",
                ttl=timedelta(hours=6),
            )
            candidates = (
                (self._place_fact(raw_place, prov, query_text=None, exact=True),)
                if isinstance(raw_place, dict)
                and (raw_place.get("place_id") or raw_place.get("data_id"))
                and raw_place.get("title")
                else ()
            )
            result = PlaceFactsResult(
                candidates=candidates,
                warnings=(
                    ()
                    if candidates
                    else ("The selected place has no current detail record.",)
                ),
                provenance=prov,
            )
        except (ValidationError, ValueError, KeyError, TypeError):
            raise ProviderError(
                ProviderErrorKind.UPSTREAM,
                self.provider,
                "SearchAPI place detail data did not match the expected schema.",
            ) from None
        self.place_detail_cache.put(
            provider=self.provider,
            fingerprint=fingerprint,
            value=result,
            ttl=timedelta(hours=6),
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

    @classmethod
    def _transit_option(
        cls,
        item: dict[str, Any],
        query: TransitRouteQuery,
        item_provenance: Any,
    ) -> TransitOption:
        time_window = item.get("time_window")
        if not isinstance(time_window, dict):
            raise ValueError
        reference = query.at or datetime.now(UTC)
        departure = cls._provider_datetime(
            time_window.get("depart_at"),
            time_window.get("depart_at_tz"),
            reference,
        )
        arrival = cls._provider_datetime(
            time_window.get("arrive_at"),
            time_window.get("arrive_at_tz"),
            reference,
        )
        if arrival <= departure:
            arrival += timedelta(days=1)
        instructions = cls._list(item.get("directions") or item.get("instructions"))
        steps = tuple(
            cls._transit_step(step, reference)
            for step in instructions
            if isinstance(step, dict)
        )
        if not steps:
            raise ValueError
        elapsed = int((arrival - departure).total_seconds())
        walking = sum(step.duration_seconds for step in steps if step.mode == "walk")
        transit_legs = sum(step.mode == "transit" for step in steps)
        stable = json.dumps(
            {
                "origin": query.origin,
                "destination": query.destination,
                "departure": departure.isoformat(),
                "steps": [step.model_dump(mode="json") for step in steps],
            },
            ensure_ascii=False,
            sort_keys=True,
        )
        return TransitOption(
            option_id=hashlib.sha256(stable.encode()).hexdigest()[:20],
            origin=query.origin,
            destination=query.destination,
            departure_at=departure,
            arrival_at=arrival,
            duration_seconds=elapsed,
            distance_meters=cls._metric_value(item.get("distance")),
            walking_seconds=walking,
            transfers=max(0, transit_legs - 1),
            waiting_seconds=max(0, elapsed - sum(step.duration_seconds for step in steps)),
            steps=steps,
            provenance=item_provenance,
        )

    @classmethod
    def _transit_step(cls, item: dict[str, Any], reference: datetime) -> TransitStep:
        mode_text = str(item.get("travel_mode", item.get("mode", ""))).lower()
        transit_detail = item.get("transit_details")
        details = transit_detail if isinstance(transit_detail, dict) else item
        depart_from = details.get("depart_from")
        arrive_at = details.get("arrive_at")
        depart = depart_from if isinstance(depart_from, dict) else {}
        arrive = arrive_at if isinstance(arrive_at, dict) else {}
        vehicle = details.get("vehicle")
        line_name = details.get("line_name")
        line_number = details.get("line_number")
        mode = (
            "transit"
            if "transit" in mode_text or any((vehicle, line_name, line_number, depart_from))
            else "walk"
        )
        origin = str(
            depart.get("place")
            or item.get("origin")
            or item.get("from")
            or "Walking segment start"
        )
        destination = str(
            arrive.get("place")
            or item.get("destination")
            or item.get("to")
            or "Walking segment end"
        )
        timezone = depart.get("timezone") or arrive.get("timezone")
        departure = cls._optional_provider_datetime(
            depart.get("at") or details.get("depart_at"), timezone, reference
        )
        arrival = cls._optional_provider_datetime(
            arrive.get("at") or details.get("arrive_at"), timezone, reference
        )
        if departure is not None and arrival is not None and arrival <= departure:
            arrival += timedelta(days=1)
        stops = tuple(
            stop
            for stop in (
                cls._transit_stop(value, reference)
                for value in cls._list(details.get("stops"))
                if isinstance(value, dict)
            )
            if stop is not None
        )
        return TransitStep(
            mode=mode,
            origin=origin,
            destination=destination,
            departure_at=departure if arrival is not None else None,
            arrival_at=arrival if departure is not None else None,
            duration_seconds=int(cls._metric_value(item.get("duration")) or 0),
            distance_meters=cls._metric_value(item.get("distance")),
            vehicle=str(vehicle) if mode == "transit" and vehicle else None,
            line_name=str(line_name) if mode == "transit" and line_name else None,
            line_number=str(line_number) if mode == "transit" and line_number else None,
            stops=stops,
        )

    @classmethod
    def _transit_stop(cls, item: dict[str, Any], reference: datetime) -> TransitStop | None:
        name = item.get("place") or item.get("name")
        if not name:
            return None
        coordinate = cls._coordinate(item)
        timezone = str(item["timezone"]) if item.get("timezone") else None
        return TransitStop(
            name=str(name),
            coordinate=coordinate,
            at=cls._optional_provider_datetime(item.get("at"), timezone, reference),
            timezone=timezone,
        )

    @classmethod
    def _place_fact(
        cls,
        item: dict[str, Any],
        item_provenance: Any,
        *,
        query_text: str | None,
        exact: bool,
    ) -> PlaceFact:
        title = str(item["title"])
        confidence = (
            1.0
            if exact
            else round(
                SequenceMatcher(
                    None,
                    cls._normalized_name(query_text or ""),
                    cls._normalized_name(title),
                ).ratio(),
                4,
            )
        )
        status_text = str(
            item.get("business_status", item.get("open_state", ""))
        ).lower()
        temporarily_closed: bool | None = None
        if "temporarily" in status_text or "临时" in status_text or "一時" in status_text:
            temporarily_closed = True
        elif status_text:
            temporarily_closed = False
        return PlaceFact(
            place_id=str(item["place_id"]) if item.get("place_id") else None,
            data_id=str(item["data_id"]) if item.get("data_id") else None,
            name=title,
            address=str(item["address"]) if item.get("address") else None,
            coordinate=cls._coordinate(item),
            opening_windows=cls._opening_windows(item),
            temporarily_closed=temporarily_closed,
            match_confidence=confidence,
            provenance=item_provenance,
        )

    @classmethod
    def _opening_windows(cls, item: dict[str, Any]) -> tuple[OpeningWindow, ...]:
        raw = item.get("open_hours", item.get("opening_hours", item.get("hours")))
        if not isinstance(raw, dict):
            return ()
        week = {
            "monday": 0,
            "tuesday": 1,
            "wednesday": 2,
            "thursday": 3,
            "friday": 4,
            "saturday": 5,
            "sunday": 6,
            "月曜日": 0,
            "火曜日": 1,
            "水曜日": 2,
            "木曜日": 3,
            "金曜日": 4,
            "土曜日": 5,
            "日曜日": 6,
        }
        windows: list[OpeningWindow] = []
        for day_name, values in raw.items():
            weekday = week.get(str(day_name).strip().lower())
            if weekday is None:
                continue
            entries = values if isinstance(values, list) else [values]
            for entry in entries:
                raw_text = str(entry).strip()
                parsed = cls._opening_pair(raw_text)
                windows.append(
                    OpeningWindow(
                        weekday=weekday,
                        opens_at=parsed[0] if parsed else None,
                        closes_at=parsed[1] if parsed else None,
                        raw_text=raw_text,
                    )
                )
        return tuple(windows)

    @staticmethod
    def _opening_pair(value: str) -> tuple[time, time] | None:
        parts = re.split(
            r"\s*[\u2013\u2014-]\s*", value.replace("\u202f", " "), maxsplit=1
        )
        if len(parts) != 2:
            return None
        parsed: list[time] = []
        for part in parts:
            for pattern in ("%I:%M %p", "%I %p", "%H:%M"):
                try:
                    parsed.append(datetime.strptime(part.strip().upper(), pattern).time())
                    break
                except ValueError:
                    continue
            else:
                return None
        return parsed[0], parsed[1]

    @staticmethod
    def _normalized_name(value: str) -> str:
        return "".join(character.casefold() for character in value if character.isalnum())

    @staticmethod
    def _metric_value(value: Any) -> float | None:
        if isinstance(value, (int, float)):
            return float(value)
        if isinstance(value, dict):
            raw = value.get("value")
            if isinstance(raw, (int, float)):
                return float(raw)
        return None

    @staticmethod
    def _coordinate(item: dict[str, Any]) -> GeoCoordinate | None:
        raw = item.get("gps_coordinates", item.get("coordinates"))
        if not isinstance(raw, dict):
            return None
        latitude = raw.get("latitude", raw.get("lat"))
        longitude = raw.get("longitude", raw.get("lng", raw.get("lon")))
        if not isinstance(latitude, (int, float)) or not isinstance(longitude, (int, float)):
            return None
        return GeoCoordinate(latitude=float(latitude), longitude=float(longitude))

    @classmethod
    def _provider_datetime(
        cls, value: Any, timezone_name: Any, reference: datetime
    ) -> datetime:
        parsed = cls._optional_provider_datetime(value, timezone_name, reference)
        if parsed is None:
            raise ValueError
        return parsed

    @staticmethod
    def _optional_provider_datetime(
        value: Any, timezone_name: Any, reference: datetime
    ) -> datetime | None:
        if value is None:
            return None
        raw = str(value).replace("\u202f", " ").strip()
        try:
            parsed = datetime.fromisoformat(raw.replace("Z", "+00:00"))
            if parsed.tzinfo is not None:
                return parsed
        except ValueError:
            pass
        timezone = (
            ZoneInfo(str(timezone_name))
            if timezone_name
            else reference.tzinfo
        )
        if timezone is None:
            raise ValueError
        for pattern in ("%I:%M %p", "%I %p", "%H:%M"):
            try:
                parsed_time = datetime.strptime(raw.upper(), pattern).time()
                return datetime.combine(
                    reference.astimezone(timezone).date(), parsed_time, timezone
                )
            except ValueError:
                continue
        raise ValueError


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

    async def transit(self, query: TransitRouteQuery) -> TransitRouteResult:
        prov = provenance(
            self.provider,
            "https://www.searchapi.io/docs/google-maps-directions-api",
            ttl=timedelta(minutes=10),
        )
        departure = query.at or datetime.now(UTC).replace(second=0, microsecond=0)
        arrival = departure + timedelta(minutes=42)
        steps = (
            TransitStep(
                mode="walk",
                origin=query.origin,
                destination="Fixture Station",
                duration_seconds=420,
                distance_meters=520,
            ),
            TransitStep(
                mode="transit",
                origin="Fixture Station",
                destination=query.destination,
                departure_at=departure + timedelta(minutes=10),
                arrival_at=arrival,
                duration_seconds=1_920,
                vehicle="train",
                line_name="Fixture Line",
                line_number="F1",
                stops=(TransitStop(name=query.destination, at=arrival),),
            ),
        )
        option = TransitOption(
            option_id="fixture-transit-001",
            origin=query.origin,
            destination=query.destination,
            departure_at=departure,
            arrival_at=arrival,
            duration_seconds=2_520,
            distance_meters=12_000,
            walking_seconds=420,
            transfers=0,
            waiting_seconds=180,
            steps=steps,
            provenance=prov,
        )
        return TransitRouteResult(options=(option,), provenance=prov)

    async def search_places(self, query: PlaceFactsSearchQuery) -> PlaceFactsResult:
        prov = provenance(
            self.provider,
            "https://www.searchapi.io/docs/google-maps",
            ttl=timedelta(hours=6),
        )
        fact = PlaceFact(
            place_id="fixture-place-001",
            data_id="fixture-data-001",
            name=query.query,
            address="Fixture address",
            coordinate=query.coordinate_hint,
            opening_windows=(
                OpeningWindow(
                    weekday=0,
                    opens_at=time(9),
                    closes_at=time(18),
                    raw_text="9:00 AM-6:00 PM",
                ),
            ),
            temporarily_closed=False,
            match_confidence=1.0,
            provenance=prov,
        )
        return PlaceFactsResult(candidates=(fact,), provenance=prov)

    async def place_details(self, query: PlaceDetailsQuery) -> PlaceFactsResult:
        prov = provenance(
            self.provider,
            "https://www.searchapi.io/docs/google-maps-place",
            ttl=timedelta(hours=6),
        )
        fact = PlaceFact(
            place_id=query.place_id,
            data_id=query.data_id,
            name="Fixture place detail",
            address="Fixture address",
            coordinate=GeoCoordinate(latitude=35.6812, longitude=139.7671),
            opening_windows=(),
            temporarily_closed=False,
            match_confidence=1.0,
            provenance=prov,
        )
        return PlaceFactsResult(candidates=(fact,), provenance=prov)
