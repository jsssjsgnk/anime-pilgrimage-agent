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

