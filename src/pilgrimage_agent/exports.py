"""Versioned, machine-verifiable handoff export boundaries."""

from datetime import datetime
from typing import Literal
from uuid import UUID

from pydantic import Field, HttpUrl, model_validator

from pilgrimage_agent.domain.models import StrictModel
from pilgrimage_agent.domain.planning import RouteBPlan


class LocalWalkingConstraint(StrictModel):
    day: int = Field(ge=1, le=31)
    max_walking_meters: float = Field(gt=0, le=50_000)


class PlanExport(StrictModel):
    schema_version: Literal["1"]
    plan_version: int = Field(ge=1)
    subject_id: str = Field(min_length=1)
    generated_at: datetime
    route_a_point_ids: tuple[UUID, ...]
    route_b: RouteBPlan
    evidence_ids: tuple[str, ...]
    local_constraints: tuple[LocalWalkingConstraint, ...] = ()
    reconfirm_before_departure: tuple[str, ...] = Field(min_length=1)


class GeoJsonPoint(StrictModel):
    type: Literal["Point"]
    coordinates: tuple[float, float]

    @model_validator(mode="after")
    def coordinates_are_valid(self) -> "GeoJsonPoint":
        longitude, latitude = self.coordinates
        if not -180 <= longitude <= 180 or not -90 <= latitude <= 90:
            raise ValueError("GeoJSON point coordinates are outside WGS84 bounds")
        return self


class GeoJsonProperties(StrictModel):
    id: UUID
    name: str = Field(min_length=1)
    source_url: HttpUrl


class GeoJsonFeature(StrictModel):
    type: Literal["Feature"]
    geometry: GeoJsonPoint
    properties: GeoJsonProperties


class GeoJsonExport(StrictModel):
    type: Literal["FeatureCollection"]
    schema_version: Literal["1"]
    features: tuple[GeoJsonFeature, ...]


class StandaloneHtmlExport(StrictModel):
    content: str = Field(min_length=1, max_length=2_000_000)

    @model_validator(mode="after")
    def contains_no_active_or_external_content(self) -> "StandaloneHtmlExport":
        lowered = self.content.lower()
        forbidden = ("<script", " src=", "@import", "url(http", "javascript:")
        if not lowered.lstrip().startswith("<!doctype html>"):
            raise ValueError("standalone HTML must begin with a doctype")
        if any(marker in lowered for marker in forbidden):
            raise ValueError("standalone HTML must not contain active or external content")
        return self
