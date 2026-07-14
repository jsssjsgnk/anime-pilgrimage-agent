"""Strict Phase 3 schemas for deterministic access and itinerary planning."""

from __future__ import annotations

from datetime import date, datetime, time
from enum import StrEnum
from typing import Literal
from uuid import UUID
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from pydantic import Field, HttpUrl, field_validator, model_validator

from pilgrimage_agent.domain.models import DataProvenance, GeoCoordinate, StrictModel


class AccessMode(StrEnum):
    FLIGHT = "flight"
    TRAIN = "train"
    BUS = "bus"
    MANUAL = "manual"


class AccessOption(StrictModel):
    option_id: str = Field(min_length=1, max_length=100)
    mode: AccessMode
    origin: str = Field(min_length=1, max_length=200)
    destination: str = Field(min_length=1, max_length=200)
    departure_at: datetime
    arrival_at: datetime
    price: int | None = Field(default=None, ge=0)
    currency: str | None = Field(default=None, pattern=r"^[A-Z]{3}$")
    confirmation_url: HttpUrl | None = None
    comparison_labels: tuple[
        Literal["recommended", "fastest", "cheapest", "fewest_transfers"], ...
    ] = ()
    provenance: DataProvenance

    @model_validator(mode="after")
    def access_times_and_price_are_consistent(self) -> AccessOption:
        if self.departure_at.tzinfo is None or self.arrival_at.tzinfo is None:
            raise ValueError("access timestamps must be timezone-aware")
        if self.arrival_at <= self.departure_at:
            raise ValueError("access arrival must follow departure")
        if (self.price is None) != (self.currency is None):
            raise ValueError("price and currency must be provided together")
        return self


class ManualIntercityQuery(StrictModel):
    origin: str = Field(min_length=1, max_length=200)
    destination: str = Field(min_length=1, max_length=200)
    earliest_departure: datetime
    latest_arrival: datetime

    @model_validator(mode="after")
    def window_is_valid(self) -> ManualIntercityQuery:
        if self.earliest_departure.tzinfo is None or self.latest_arrival.tzinfo is None:
            raise ValueError("manual intercity query timestamps must be timezone-aware")
        if self.latest_arrival <= self.earliest_departure:
            raise ValueError("manual intercity query window is reversed")
        return self


class AccessSelection(StrictModel):
    inbound: AccessOption
    outbound: AccessOption
    alternatives: tuple[AccessOption, ...] = ()


class BaseCandidate(StrictModel):
    base_id: str = Field(min_length=1, max_length=100)
    name: str = Field(min_length=1, max_length=200)
    coordinate: GeoCoordinate
    provenance: DataProvenance


class VisitWindow(StrictModel):
    point_id: UUID
    opens_at: time
    closes_at: time

    @model_validator(mode="after")
    def closes_after_opening(self) -> VisitWindow:
        if self.closes_at <= self.opens_at:
            raise ValueError("visit window must close after opening")
        return self


class PlanningConstraints(StrictModel):
    start_date: date
    end_date: date
    timezone: str = "Asia/Tokyo"
    arrival_at: datetime
    departure_at: datetime
    arrival_buffer_minutes: int = Field(default=90, ge=0, le=360)
    departure_buffer_minutes: int = Field(default=120, ge=0, le=360)
    day_start: time = time(9, 0)
    day_end: time = time(18, 0)
    visit_minutes: int = Field(default=35, ge=10, le=240)
    max_walking_meters_per_day: float = Field(default=8_000, gt=0, le=50_000)
    must_visit_point_ids: frozenset[UUID] = frozenset()
    excluded_point_ids: frozenset[UUID] = frozenset()
    visit_windows: tuple[VisitWindow, ...] = ()

    @field_validator("timezone")
    @classmethod
    def timezone_exists(cls, value: str) -> str:
        try:
            ZoneInfo(value)
        except ZoneInfoNotFoundError:
            raise ValueError("timezone must be a valid IANA identifier") from None
        return value

    @model_validator(mode="after")
    def constraints_are_consistent(self) -> PlanningConstraints:
        if self.end_date < self.start_date:
            raise ValueError("end_date must not precede start_date")
        if self.day_end <= self.day_start:
            raise ValueError("daily end time must follow start time")
        if self.arrival_at.tzinfo is None or self.departure_at.tzinfo is None:
            raise ValueError("arrival and departure timestamps must be timezone-aware")
        if self.departure_at <= self.arrival_at:
            raise ValueError("trip departure must follow arrival")
        if self.must_visit_point_ids & self.excluded_point_ids:
            raise ValueError("a point cannot be both required and excluded")
        return self


class ScheduledVisit(StrictModel):
    point_id: UUID
    start_at: datetime
    end_at: datetime
    incoming_distance_meters: float = Field(ge=0)
    incoming_duration_seconds: float = Field(ge=0)


class DayPlan(StrictModel):
    date: date
    window_start: datetime
    window_end: datetime
    visits: tuple[ScheduledVisit, ...]
    walking_distance_meters: float = Field(ge=0)
    maps_urls: tuple[HttpUrl, ...] = ()


class OmissionCode(StrEnum):
    EXCLUDED = "excluded"
    WALKING_LIMIT = "walking_limit"
    TIME_WINDOW = "time_window"
    NO_AVAILABLE_DAY = "no_available_day"
    INVALID_MATRIX = "invalid_matrix"


class OmissionReason(StrictModel):
    code: OmissionCode
    detail: str = Field(min_length=1, max_length=300)


class RouteBPlan(StrictModel):
    route_a_point_ids: frozenset[UUID]
    base: BaseCandidate
    days: tuple[DayPlan, ...]
    omitted_reasons: dict[UUID, OmissionReason]
    matrix_status: Literal["road", "straight_line_estimate"]
    access: AccessSelection | None = None

    @model_validator(mode="after")
    def itinerary_is_complete_subset(self) -> RouteBPlan:
        scheduled = [visit.point_id for day in self.days for visit in day.visits]
        scheduled_set = set(scheduled)
        if len(scheduled) != len(scheduled_set):
            raise ValueError("a Route B point may be scheduled only once")
        if not scheduled_set.issubset(self.route_a_point_ids):
            raise ValueError("Route B points must belong to Route A")
        omitted = self.route_a_point_ids - scheduled_set
        if set(self.omitted_reasons) != omitted:
            raise ValueError("every omitted Route A point needs exactly one reason")
        return self


class ValidationIssue(StrictModel):
    code: str = Field(min_length=1, max_length=80)
    detail: str = Field(min_length=1, max_length=300)
    point_id: UUID | None = None
    day: date | None = None


class PlanValidationReport(StrictModel):
    valid: bool
    issues: tuple[ValidationIssue, ...] = ()


class PlanningOptions(StrictModel):
    access_options: tuple[AccessOption, ...]
    base_candidates: tuple[BaseCandidate, ...]
    recommended_base_id: str
    start_date: date
    end_date: date


class RouteBRequest(StrictModel):
    inbound_option_id: str = Field(min_length=1, max_length=100)
    outbound_option_id: str = Field(min_length=1, max_length=100)
    base_id: str = Field(min_length=1, max_length=100)
    max_walking_meters_per_day: float = Field(default=8_000, gt=0, le=50_000)
    must_visit_point_ids: frozenset[UUID] = frozenset()
    excluded_point_ids: frozenset[UUID] = frozenset()
