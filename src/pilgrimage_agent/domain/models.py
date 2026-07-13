"""Versioned Pydantic schemas used at API, LLM, and tool boundaries."""

from datetime import date, datetime
from enum import StrEnum
from typing import Annotated, Literal
from uuid import UUID, uuid4

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


class TripRequest(StrictModel):
    origin: str | None = Field(default=None, max_length=200)
    destination: str | None = Field(default=None, max_length=200)
    start_date: date | None = None
    end_date: date | None = None
    anime_query: str | None = Field(default=None, max_length=200)
    budget_level: Literal["low", "medium", "high"] | None = None
    walking_preference: Literal["low", "medium", "high"] | None = None
    must_visit_point_ids: tuple[UUID, ...] = ()
    excluded_point_ids: tuple[UUID, ...] = ()

    @model_validator(mode="after")
    def dates_are_ordered(self) -> "TripRequest":
        if self.start_date and self.end_date and self.end_date < self.start_date:
            raise ValueError("end_date must not precede start_date")
        return self


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
    confidence: Literal["verified", "community", "unverified"]
    provenance: DataProvenance


class PilgrimagePointQuery(StrictModel):
    subject_id: str = Field(min_length=1, max_length=50)
    provider: Literal["imported", "fixture"] = "imported"


class PilgrimagePointResult(StrictModel):
    points: tuple[PilgrimagePoint, ...]
    is_complete: bool
    warnings: tuple[str, ...] = ()
    provenance: DataProvenance


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


class FlightOption(StrictModel):
    option_id: str = Field(min_length=1, max_length=200)
    price: int = Field(ge=0)
    currency: str = Field(pattern=r"^[A-Z]{3}$")
    duration_minutes: int = Field(ge=0)
    stops: int = Field(ge=0)
    segments: tuple[FlightSegment, ...]
    confirmation_url: HttpUrl | None = None
    provenance: DataProvenance


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
