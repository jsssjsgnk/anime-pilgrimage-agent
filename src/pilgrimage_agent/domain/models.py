"""Versioned Pydantic schemas used at API, LLM, and tool boundaries."""

from datetime import date, datetime, time
from enum import StrEnum
from typing import Annotated, Literal
from uuid import NAMESPACE_URL, UUID, uuid4, uuid5

from pydantic import BaseModel, ConfigDict, Field, HttpUrl, model_validator


class StrictModel(BaseModel):
    """Base model that rejects unknown boundary data."""

    model_config = ConfigDict(extra="forbid", frozen=True)


class DataStatus(StrEnum):
    LIVE = "live"
    CACHED = "cached"
    ESTIMATED = "estimated"
    COMMUNITY = "community"
    NEEDS_CONFIRMATION = "needs_confirmation"
    UNKNOWN = "unknown"


class DataProvenance(StrictModel):
    provider: str = Field(min_length=1, max_length=80)
    source_url: HttpUrl | None = None
    fetched_at: datetime
    expires_at: datetime | None = None
    status: DataStatus
    schema_version: str = "1"


class Citation(StrictModel):
    evidence_id: str = Field(pattern=r"^[A-Z]-[A-Za-z0-9_-]+$")
    title: str = Field(min_length=1, max_length=300)
    url: HttpUrl
    accessed_at: date


class SubjectIntent(StrictModel):
    """Trip-owned intent; catalog facts remain in confirmed subject records."""

    intent_id: UUID = Field(default_factory=uuid4)
    query: str = Field(min_length=1, max_length=200)
    confirmed_subject_id: str | None = Field(default=None, min_length=1, max_length=50)
    confirmed_subject_ids: tuple[str, ...] = Field(default=(), max_length=5)
    priority: int = Field(default=3, ge=1, le=5)
    minimum_place_count: int | None = Field(default=None, ge=0, le=100)
    is_primary: bool = False
    status: Literal["proposed", "confirmed", "rejected"] = "proposed"

    @model_validator(mode="before")
    @classmethod
    def adapt_single_confirmed_subject(cls, value: object) -> object:
        if not isinstance(value, dict):
            return value
        adapted = dict(value)
        single = adapted.get("confirmed_subject_id")
        multiple = adapted.get("confirmed_subject_ids")
        if single and not multiple:
            adapted["confirmed_subject_ids"] = (single,)
        elif multiple and not single and isinstance(multiple, (tuple, list)) and multiple:
            adapted["confirmed_subject_id"] = multiple[0]
        return adapted

    @model_validator(mode="after")
    def confirmation_is_consistent(self) -> "SubjectIntent":
        if len(self.confirmed_subject_ids) != len(set(self.confirmed_subject_ids)):
            raise ValueError("confirmed catalog subject IDs must be unique")
        if self.status == "confirmed" and not self.confirmed_subject_ids:
            raise ValueError("confirmed subject intents require catalog subject IDs")
        if (
            self.confirmed_subject_id is not None
            and self.confirmed_subject_id not in self.confirmed_subject_ids
        ):
            raise ValueError("the compatibility subject ID must belong to the confirmed set")
        return self

    @property
    def catalog_subject_ids(self) -> tuple[str, ...]:
        return self.confirmed_subject_ids


class TripRequest(StrictModel):
    origin: str | None = Field(default=None, max_length=200)
    destination: str | None = Field(default=None, max_length=200)
    base_preference: str | None = Field(default=None, max_length=200)
    start_date: date | None = None
    end_date: date | None = None
    anime_query: str | None = Field(default=None, max_length=200)
    subject_intents: tuple[SubjectIntent, ...] = Field(default=(), max_length=12)
    budget_level: Literal["low", "medium", "high"] | None = None
    walking_preference: Literal["low", "medium", "high"] | None = None
    transit_route_preference: Literal[
        "best", "fewer_transfers", "less_walking", "wheelchair_accessible"
    ] = "best"
    transit_vehicle_preferences: tuple[
        Literal["bus", "subway", "train", "tram_and_light_rail"], ...
    ] = ()
    max_walking_meters_per_day: float | None = Field(default=None, gt=0, le=50_000)
    origin_iata: str | None = Field(default=None, pattern=r"^[A-Z]{3}$")
    destination_iata: str | None = Field(default=None, pattern=r"^[A-Z]{3}$")
    adults: int = Field(default=1, ge=1, le=9)
    cabin_class: Literal["economy", "premium_economy", "business", "first"] = "economy"
    currency: str = Field(default="JPY", pattern=r"^[A-Z]{3}$")
    must_visit_point_ids: tuple[UUID, ...] = ()
    excluded_point_ids: tuple[UUID, ...] = ()

    @model_validator(mode="before")
    @classmethod
    def adapt_legacy_anime_query(cls, value: object) -> object:
        """Map the old single query to one primary intent without hiding compatibility."""

        if not isinstance(value, dict):
            return value
        query = value.get("anime_query")
        if value.get("subject_intents") or not isinstance(query, str) or not query.strip():
            return value
        adapted = dict(value)
        normalized = query.strip()
        adapted["subject_intents"] = (
            {
                "intent_id": str(uuid5(NAMESPACE_URL, f"legacy-anime:{normalized}")),
                "query": normalized,
                "priority": 5,
                "is_primary": True,
                "status": "proposed",
            },
        )
        return adapted

    @model_validator(mode="after")
    def dates_are_ordered(self) -> "TripRequest":
        if self.start_date and self.end_date and self.end_date < self.start_date:
            raise ValueError("end_date must not precede start_date")
        intent_ids = [item.intent_id for item in self.subject_intents]
        if len(intent_ids) != len(set(intent_ids)):
            raise ValueError("subject intent IDs must be unique")
        primary = [item for item in self.subject_intents if item.is_primary]
        if self.subject_intents and len(primary) != 1:
            raise ValueError("one and only one subject intent must be primary")
        confirmed_ids = [
            subject_id
            for item in self.subject_intents
            for subject_id in item.catalog_subject_ids
        ]
        if len(confirmed_ids) != len(set(confirmed_ids)):
            raise ValueError("one catalog subject cannot satisfy multiple intents")
        if len(self.transit_vehicle_preferences) != len(
            set(self.transit_vehicle_preferences)
        ):
            raise ValueError("transit vehicle preferences must be unique")
        return self

    @property
    def primary_subject_query(self) -> str | None:
        primary = next((item.query for item in self.subject_intents if item.is_primary), None)
        return primary or self.anime_query


class ConfirmedSubject(StrictModel):
    subject_id: str = Field(min_length=1, max_length=50)
    name: str = Field(min_length=1, max_length=300)
    name_cn: str | None = Field(default=None, max_length=300)
    aliases: tuple[str, ...] = ()
    provenance: DataProvenance


class SubjectSearchQuery(StrictModel):
    query: str = Field(min_length=1, max_length=200)
    limit: int = Field(default=5, ge=1, le=20)


class SubjectCandidate(StrictModel):
    subject_id: str = Field(min_length=1, max_length=50)
    name: str = Field(min_length=1, max_length=300)
    name_cn: str | None = Field(default=None, max_length=300)
    aliases: tuple[str, ...] = ()
    image_url: HttpUrl | None = None
    score: float | None = Field(default=None, ge=0, le=10)
    provenance: DataProvenance


class SubjectSearchResult(StrictModel):
    candidates: tuple[SubjectCandidate, ...]
    provenance: DataProvenance


Latitude = Annotated[float, Field(ge=-90, le=90)]
Longitude = Annotated[float, Field(ge=-180, le=180)]


class PilgrimagePoint(StrictModel):
    id: UUID = Field(default_factory=uuid4)
    subject_id: str = Field(min_length=1, max_length=50)
    name: str = Field(min_length=1, max_length=300)
    latitude: Latitude
    longitude: Longitude
    episode_refs: tuple[str, ...] = ()
    image_url: HttpUrl | None = None
    description: str | None = Field(default=None, max_length=2000)
    confidence: Literal["verified", "community", "unverified"]
    source_label: str | None = Field(default=None, max_length=200)
    provenance: DataProvenance


class PilgrimagePointQuery(StrictModel):
    subject_id: str = Field(min_length=1, max_length=50)
    provider: Literal["anitabi", "imported", "fixture"] = "anitabi"


class PilgrimagePointResult(StrictModel):
    points: tuple[PilgrimagePoint, ...]
    is_complete: bool
    expected_count: int = Field(default=0, ge=0)
    loaded_count: int = Field(default=0, ge=0)
    data_version: str | None = Field(default=None, max_length=120)
    warnings: tuple[str, ...] = ()
    provenance: DataProvenance

    @model_validator(mode="before")
    @classmethod
    def populate_legacy_counts(cls, value: object) -> object:
        """Accept older persisted/tool payloads while making counts explicit."""

        if not isinstance(value, dict):
            return value
        normalized = dict(value)
        points = normalized.get("points")
        point_count = len(points) if isinstance(points, (list, tuple)) else 0
        normalized.setdefault("loaded_count", point_count)
        normalized.setdefault("expected_count", normalized["loaded_count"])
        return normalized

    @model_validator(mode="after")
    def completeness_counts_are_consistent(self) -> "PilgrimagePointResult":
        if self.loaded_count != len(self.points):
            raise ValueError("loaded point count must equal the normalized point array")
        if self.loaded_count > self.expected_count:
            raise ValueError("loaded point count cannot exceed the expected point count")
        if self.is_complete and self.loaded_count != self.expected_count:
            raise ValueError("complete point results must load the expected point count")
        return self


class GeoCoordinate(StrictModel):
    latitude: Latitude
    longitude: Longitude


class PlaceSearchQuery(StrictModel):
    text: str = Field(min_length=2, max_length=200)
    language: str = Field(default="ja", pattern=r"^[a-z]{2}(?:-[A-Z]{2})?$")
    limit: int = Field(default=5, ge=1, le=10)


class PlaceCandidate(StrictModel):
    label: str = Field(min_length=1, max_length=300)
    coordinate: GeoCoordinate
    region: str | None = Field(default=None, max_length=200)
    country: str | None = Field(default=None, max_length=100)
    provenance: DataProvenance


class PlaceSearchResult(StrictModel):
    candidates: tuple[PlaceCandidate, ...]
    provenance: DataProvenance


TravelProfile = Literal["foot-walking", "cycling-regular", "driving-car"]


class DirectionsQuery(StrictModel):
    coordinates: tuple[GeoCoordinate, ...] = Field(min_length=2, max_length=50)
    profile: TravelProfile = "foot-walking"


class RouteLeg(StrictModel):
    distance_meters: float = Field(ge=0)
    duration_seconds: float = Field(ge=0)
    encoded_geometry: str | None = Field(default=None, max_length=100_000)
    is_straight_line_estimate: bool = False
    provenance: DataProvenance


class MatrixQuery(StrictModel):
    coordinates: tuple[GeoCoordinate, ...] = Field(min_length=2, max_length=50)
    profile: TravelProfile = "foot-walking"


class RouteMatrix(StrictModel):
    durations_seconds: tuple[tuple[float | None, ...], ...]
    distances_meters: tuple[tuple[float | None, ...], ...]
    provenance: DataProvenance

    @model_validator(mode="after")
    def matrices_are_square_and_aligned(self) -> "RouteMatrix":
        size = len(self.durations_seconds)
        if size == 0 or len(self.distances_meters) != size:
            raise ValueError("route matrices must be non-empty and aligned")
        if any(len(row) != size for row in self.durations_seconds):
            raise ValueError("duration matrix must be square")
        if any(len(row) != size for row in self.distances_meters):
            raise ValueError("distance matrix must be square")
        return self


class WeatherForecastQuery(StrictModel):
    coordinate: GeoCoordinate
    start_date: date
    end_date: date

    @model_validator(mode="after")
    def dates_are_ordered_and_bounded(self) -> "WeatherForecastQuery":
        if self.end_date < self.start_date:
            raise ValueError("end_date must not precede start_date")
        if (self.end_date - self.start_date).days > 15:
            raise ValueError("weather query window cannot exceed 16 days")
        return self


class WeatherWindow(StrictModel):
    date: date
    temperature_max_c: float | None = None
    temperature_min_c: float | None = None
    precipitation_probability_max: int | None = Field(default=None, ge=0, le=100)
    weather_code: int | None = Field(default=None, ge=0)


class WeatherForecastResult(StrictModel):
    windows: tuple[WeatherWindow, ...]
    available: bool
    reason: str | None = Field(default=None, max_length=300)
    provenance: DataProvenance


class FlightSearchQuery(StrictModel):
    departure_id: str = Field(pattern=r"^[A-Z]{3}$")
    arrival_id: str = Field(pattern=r"^[A-Z]{3}$")
    outbound_date: date
    return_date: date | None = None
    adults: int = Field(default=1, ge=1, le=9)
    cabin_class: Literal["economy", "premium_economy", "business", "first"] = "economy"
    currency: str = Field(default="JPY", pattern=r"^[A-Z]{3}$")

    @model_validator(mode="after")
    def return_is_after_departure(self) -> "FlightSearchQuery":
        if self.return_date and self.return_date < self.outbound_date:
            raise ValueError("return_date must not precede outbound_date")
        return self


class FlightSegment(StrictModel):
    departure_airport: str = Field(min_length=3, max_length=100)
    arrival_airport: str = Field(min_length=3, max_length=100)
    departure_at: datetime
    arrival_at: datetime
    carrier: str = Field(min_length=1, max_length=100)
    flight_number: str | None = Field(default=None, max_length=30)

    @model_validator(mode="after")
    def timestamps_are_aware_and_ordered(self) -> "FlightSegment":
        if self.departure_at.utcoffset() is None or self.arrival_at.utcoffset() is None:
            raise ValueError("flight segment timestamps must include timezone offsets")
        if self.arrival_at <= self.departure_at:
            raise ValueError("flight segment arrival must follow departure")
        return self


class FlightOption(StrictModel):
    option_id: str = Field(min_length=1, max_length=200)
    price: int = Field(ge=0)
    currency: str = Field(pattern=r"^[A-Z]{3}$")
    duration_minutes: int = Field(ge=0)
    stops: int = Field(ge=0)
    segments: tuple[FlightSegment, ...] = Field(min_length=1)
    confirmation_url: HttpUrl | None = None
    provenance: DataProvenance

    @model_validator(mode="after")
    def segments_are_continuous_and_duration_is_deterministic(self) -> "FlightOption":
        if self.stops != len(self.segments) - 1:
            raise ValueError("flight stop count must match the segment sequence")
        for previous, current in zip(self.segments, self.segments[1:], strict=False):
            if previous.arrival_airport != current.departure_airport:
                raise ValueError("connecting flight airports must be continuous")
            if current.departure_at < previous.arrival_at:
                raise ValueError("a connecting flight cannot depart before arrival")
        elapsed_minutes = int(
            (self.segments[-1].arrival_at - self.segments[0].departure_at).total_seconds()
            // 60
        )
        if self.duration_minutes != elapsed_minutes:
            raise ValueError("flight duration must equal timezone-aware elapsed time")
        return self


class FlightSearchResult(StrictModel):
    options: tuple[FlightOption, ...]
    requires_reconfirmation: bool = True
    provenance: DataProvenance


class FlexibleFlightQuery(StrictModel):
    departure_id: str = Field(pattern=r"^[A-Z]{3}$")
    arrival_id: str = Field(pattern=r"^[A-Z]{3}$")
    outbound_start: date
    outbound_end: date
    return_start: date | None = None
    return_end: date | None = None
    currency: str = Field(default="JPY", pattern=r"^[A-Z]{3}$")

    @model_validator(mode="after")
    def windows_are_valid(self) -> "FlexibleFlightQuery":
        if self.outbound_end < self.outbound_start:
            raise ValueError("outbound date window is reversed")
        if (self.outbound_end - self.outbound_start).days > 30:
            raise ValueError("outbound date window cannot exceed 31 days")
        if (self.return_start is None) != (self.return_end is None):
            raise ValueError("both return window bounds are required")
        if self.return_start and self.return_end and self.return_end < self.return_start:
            raise ValueError("return date window is reversed")
        return self


class FareDateCandidate(StrictModel):
    outbound_date: date
    return_date: date | None = None
    price: int | None = Field(default=None, ge=0)
    currency: str = Field(pattern=r"^[A-Z]{3}$")
    has_no_flights: bool = False


class FlexibleFlightResult(StrictModel):
    candidates: tuple[FareDateCandidate, ...]
    provenance: DataProvenance


TransitTimeMode = Literal["depart_at", "arrive_by", "last_available"]
TransitRoutePreference = Literal[
    "best", "fewer_transfers", "less_walking", "wheelchair_accessible"
]
TransitVehiclePreference = Literal["bus", "subway", "train", "tram_and_light_rail"]


class TransitRouteQuery(StrictModel):
    origin: str = Field(min_length=1, max_length=300)
    destination: str = Field(min_length=1, max_length=300)
    time_mode: TransitTimeMode = "depart_at"
    at: datetime | None = None
    route: TransitRoutePreference = "best"
    prefer: tuple[TransitVehiclePreference, ...] = ()
    language: str = Field(default="ja", pattern=r"^[a-z]{2}(?:-[A-Z]{2})?$")
    country: str = Field(default="jp", pattern=r"^[a-z]{2}$")

    @model_validator(mode="after")
    def time_and_preferences_are_valid(self) -> "TransitRouteQuery":
        if self.time_mode == "last_available" and self.at is not None:
            raise ValueError("last_available must not include a timestamp")
        if self.time_mode != "last_available" and self.at is None:
            raise ValueError("depart_at and arrive_by require a timestamp")
        if self.at is not None and self.at.utcoffset() is None:
            raise ValueError("transit timestamps must include a timezone offset")
        if len(self.prefer) != len(set(self.prefer)):
            raise ValueError("transit vehicle preferences must be unique")
        return self


class TransitStop(StrictModel):
    name: str = Field(min_length=1, max_length=300)
    coordinate: GeoCoordinate | None = None
    at: datetime | None = None
    timezone: str | None = Field(default=None, max_length=80)

    @model_validator(mode="after")
    def timestamp_is_aware(self) -> "TransitStop":
        if self.at is not None and self.at.utcoffset() is None:
            raise ValueError("transit stop timestamps must include a timezone offset")
        return self


class TransitStep(StrictModel):
    mode: Literal["walk", "transit"]
    origin: str = Field(min_length=1, max_length=300)
    destination: str = Field(min_length=1, max_length=300)
    departure_at: datetime | None = None
    arrival_at: datetime | None = None
    duration_seconds: int = Field(ge=0)
    distance_meters: float | None = Field(default=None, ge=0)
    vehicle: str | None = Field(default=None, max_length=100)
    line_name: str | None = Field(default=None, max_length=200)
    line_number: str | None = Field(default=None, max_length=80)
    stops: tuple[TransitStop, ...] = ()

    @model_validator(mode="after")
    def timestamps_are_consistent(self) -> "TransitStep":
        if (self.departure_at is None) != (self.arrival_at is None):
            raise ValueError("transit step timestamps must be provided together")
        if self.departure_at is not None and self.arrival_at is not None:
            if self.departure_at.utcoffset() is None or self.arrival_at.utcoffset() is None:
                raise ValueError("transit step timestamps must include timezone offsets")
            if self.arrival_at <= self.departure_at:
                raise ValueError("transit step arrival must follow departure")
        if self.mode == "walk" and any((self.vehicle, self.line_name, self.line_number)):
            raise ValueError("walking steps cannot include transit line metadata")
        return self


class TransitOption(StrictModel):
    option_id: str = Field(min_length=1, max_length=200)
    origin: str = Field(min_length=1, max_length=300)
    destination: str = Field(min_length=1, max_length=300)
    departure_at: datetime
    arrival_at: datetime
    duration_seconds: int = Field(ge=0)
    distance_meters: float | None = Field(default=None, ge=0)
    walking_seconds: int = Field(default=0, ge=0)
    transfers: int = Field(default=0, ge=0)
    waiting_seconds: int | None = Field(default=None, ge=0)
    steps: tuple[TransitStep, ...] = Field(min_length=1, max_length=100)
    provenance: DataProvenance

    @model_validator(mode="after")
    def option_is_time_consistent(self) -> "TransitOption":
        if self.departure_at.utcoffset() is None or self.arrival_at.utcoffset() is None:
            raise ValueError("transit option timestamps must include timezone offsets")
        if self.arrival_at <= self.departure_at:
            raise ValueError("transit option arrival must follow departure")
        elapsed = int((self.arrival_at - self.departure_at).total_seconds())
        if abs(elapsed - self.duration_seconds) > 60:
            raise ValueError("transit duration must match the timezone-aware time window")
        if self.walking_seconds > self.duration_seconds:
            raise ValueError("walking time cannot exceed total transit duration")
        return self


class TransitRouteResult(StrictModel):
    options: tuple[TransitOption, ...]
    requires_reconfirmation: bool = True
    warnings: tuple[str, ...] = ()
    provenance: DataProvenance


class PlaceFactsSearchQuery(StrictModel):
    query: str = Field(min_length=2, max_length=300)
    coordinate_hint: GeoCoordinate | None = None
    zoom: int = Field(default=15, ge=3, le=21)
    language: str = Field(default="ja", pattern=r"^[a-z]{2}(?:-[A-Z]{2})?$")
    country: str = Field(default="jp", pattern=r"^[a-z]{2}$")
    limit: int = Field(default=5, ge=1, le=10)


class PlaceDetailsQuery(StrictModel):
    place_id: str | None = Field(default=None, min_length=1, max_length=300)
    data_id: str | None = Field(default=None, min_length=1, max_length=500)
    language: str = Field(default="ja", pattern=r"^[a-z]{2}(?:-[A-Z]{2})?$")
    country: str = Field(default="jp", pattern=r"^[a-z]{2}$")

    @model_validator(mode="after")
    def exactly_one_identifier_is_present(self) -> "PlaceDetailsQuery":
        if (self.place_id is None) == (self.data_id is None):
            raise ValueError("exactly one place identifier is required")
        return self


class OpeningWindow(StrictModel):
    weekday: int = Field(ge=0, le=6)
    opens_at: time | None = None
    closes_at: time | None = None
    raw_text: str | None = Field(default=None, min_length=1, max_length=200)

    @model_validator(mode="after")
    def window_has_normalized_or_raw_value(self) -> "OpeningWindow":
        if (self.opens_at is None) != (self.closes_at is None):
            raise ValueError("opening and closing times must be provided together")
        if self.opens_at is None and self.raw_text is None:
            raise ValueError("an opening window requires normalized times or source text")
        return self


class PlaceFact(StrictModel):
    place_id: str | None = Field(default=None, min_length=1, max_length=300)
    data_id: str | None = Field(default=None, min_length=1, max_length=500)
    name: str = Field(min_length=1, max_length=300)
    address: str | None = Field(default=None, max_length=500)
    coordinate: GeoCoordinate | None = None
    opening_windows: tuple[OpeningWindow, ...] = ()
    temporarily_closed: bool | None = None
    match_confidence: float = Field(ge=0, le=1)
    provenance: DataProvenance

    @model_validator(mode="after")
    def provider_identifier_is_present(self) -> "PlaceFact":
        if self.place_id is None and self.data_id is None:
            raise ValueError("place facts require a provider place identifier")
        return self


class PlaceFactsResult(StrictModel):
    candidates: tuple[PlaceFact, ...]
    warnings: tuple[str, ...] = ()
    provenance: DataProvenance


class RouteA(StrictModel):
    subject_id: str
    points: tuple[PilgrimagePoint, ...]
    is_complete: bool
    warnings: tuple[str, ...] = ()


class RouteB(StrictModel):
    route_a_point_ids: frozenset[UUID]
    selected_point_ids: tuple[UUID, ...]
    omitted_reasons: dict[UUID, str]

    @model_validator(mode="after")
    def selected_points_belong_to_route_a(self) -> "RouteB":
        selected = set(self.selected_point_ids)
        if not selected.issubset(self.route_a_point_ids):
            raise ValueError("Route B points must belong to Route A")
        omitted = self.route_a_point_ids - selected
        if set(self.omitted_reasons) != omitted:
            raise ValueError("Every omitted Route A point needs exactly one structured reason")
        return self
