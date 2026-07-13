"""Legally imported JSON/GeoJSON pilgrimage-point provider."""

from __future__ import annotations

import json
import unicodedata
from datetime import timedelta
from pathlib import Path
from typing import Any
from uuid import NAMESPACE_URL, uuid5

from pydantic import TypeAdapter, ValidationError

from pilgrimage_agent.domain.models import (
    DataProvenance,
    DataStatus,
    PilgrimagePoint,
    PilgrimagePointQuery,
    PilgrimagePointResult,
    RouteA,
)
from pilgrimage_agent.providers.base import ProviderError, ProviderErrorKind
from pilgrimage_agent.providers.common import provenance

_DICT = TypeAdapter(dict[str, Any])


class ImportedPilgrimagePointProvider:
    """Read only one explicitly configured project-owned import file."""

    provider = "imported"

    def __init__(self, import_path: Path) -> None:
        self.import_path = import_path

    async def fetch(self, query: PilgrimagePointQuery) -> PilgrimagePointResult:
        try:
            raw = json.loads(self.import_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            raise ProviderError(
                ProviderErrorKind.UPSTREAM,
                self.provider,
                "The configured pilgrimage-point import is unavailable or invalid JSON.",
            ) from None
        return self.parse(raw, query=query, import_label=self.import_path.name)

    def parse(
        self,
        raw: object,
        *,
        query: PilgrimagePointQuery,
        import_label: str,
    ) -> PilgrimagePointResult:
        try:
            payload = _DICT.validate_python(raw)
        except ValidationError:
            raise ProviderError(
                ProviderErrorKind.VALIDATION,
                self.provider,
                "The imported point document must be a JSON object or GeoJSON FeatureCollection.",
            ) from None
        items = self._items(payload)
        points: list[PilgrimagePoint] = []
        warnings: list[str] = []
        result_provenance = provenance(
            self.provider,
            f"https://local.invalid/imports/{import_label}",
            ttl=timedelta(days=365),
            status=DataStatus.COMMUNITY,
        )
        for index, item in enumerate(items):
            try:
                point = self._point(item, query.subject_id, result_provenance)
            except (ValidationError, ValueError, KeyError, TypeError):
                warnings.append(f"Skipped invalid imported point at index {index}.")
                continue
            if point.subject_id == query.subject_id:
                points.append(point)
        return PilgrimagePointResult(
            points=tuple(points),
            is_complete=not warnings,
            warnings=tuple(warnings),
            provenance=result_provenance,
        )

    @staticmethod
    def _items(payload: dict[str, Any]) -> list[dict[str, Any]]:
        if payload.get("type") == "FeatureCollection":
            features = payload.get("features")
            if not isinstance(features, list):
                raise ProviderError(
                    ProviderErrorKind.VALIDATION,
                    "imported",
                    "GeoJSON features must be an array.",
                )
            return [item for item in features if isinstance(item, dict)]
        points = payload.get("points")
        if not isinstance(points, list):
            raise ProviderError(
                ProviderErrorKind.VALIDATION,
                "imported",
                "JSON imports require a points array.",
            )
        return [item for item in points if isinstance(item, dict)]

    @staticmethod
    def _point(
        item: dict[str, Any],
        default_subject_id: str,
        result_provenance: DataProvenance,
    ) -> PilgrimagePoint:
        if item.get("type") == "Feature":
            properties = item.get("properties")
            geometry = item.get("geometry")
            if not isinstance(properties, dict) or not isinstance(geometry, dict):
                raise ValueError
            coordinates = geometry.get("coordinates")
            if geometry.get("type") != "Point" or not isinstance(coordinates, list):
                raise ValueError
            longitude, latitude = coordinates[:2]
            data = properties
        else:
            data = item
            latitude = data["latitude"]
            longitude = data["longitude"]
        subject_id = str(data.get("subject_id", default_subject_id))
        name = str(data["name"]).strip()
        source_url = data.get("source_url")
        if not isinstance(source_url, str) or not source_url.startswith(("http://", "https://")):
            raise ValueError
        stable_key = f"{subject_id}:{name}:{float(latitude):.6f}:{float(longitude):.6f}"
        refs = data.get("episode_refs", [])
        if not isinstance(refs, list) or not all(isinstance(ref, str) for ref in refs):
            raise ValueError
        confidence = data.get("confidence", "community")
        return PilgrimagePoint(
            id=uuid5(NAMESPACE_URL, stable_key),
            subject_id=subject_id,
            name=name,
            latitude=latitude,
            longitude=longitude,
            episode_refs=tuple(refs),
            confidence=confidence,
            provenance=DataProvenance.model_validate(
                {**result_provenance.model_dump(), "source_url": source_url}
            ),
        )


class FixturePilgrimagePointProvider(ImportedPilgrimagePointProvider):
    provider = "fixture"

    async def fetch(self, query: PilgrimagePointQuery) -> PilgrimagePointResult:
        return self.parse(
            FIXTURE_POINTS,
            query=query,
            import_label="phase-2-points.geojson",
        )


def build_route_a(result: PilgrimagePointResult, *, subject_id: str) -> RouteA:
    """Clean and deduplicate sourced points without deleting unique valid candidates."""

    seen: set[tuple[str, float, float]] = set()
    points: list[PilgrimagePoint] = []
    warnings = list(result.warnings)
    for point in result.points:
        if point.subject_id != subject_id:
            warnings.append(f"Excluded point {point.id}: subject mismatch.")
            continue
        if point.provenance.source_url is None:
            warnings.append(f"Excluded point {point.id}: missing source URL.")
            continue
        normalized_name = unicodedata.normalize("NFKC", point.name).casefold().strip()
        key = (normalized_name, round(point.latitude, 5), round(point.longitude, 5))
        if key in seen:
            warnings.append(f"Removed duplicate point {point.id}.")
            continue
        seen.add(key)
        points.append(point)
    return RouteA(
        subject_id=subject_id,
        points=tuple(points),
        is_complete=result.is_complete,
        warnings=tuple(warnings),
    )


FIXTURE_POINTS: dict[str, Any] = {
    "type": "FeatureCollection",
    "features": [
        {
            "type": "Feature",
            "geometry": {"type": "Point", "coordinates": [139.66792, 35.66161]},
            "properties": {
                "subject_id": "328609",
                "name": "下北沢SHELTER周边",
                "episode_refs": ["第8话"],
                "confidence": "community",
                "source_url": "https://www.city.setagaya.lg.jp/",
            },
        },
        {
            "type": "Feature",
            "geometry": {"type": "Point", "coordinates": [139.66842, 35.66213]},
            "properties": {
                "subject_id": "328609",
                "name": "下北泽站东口",
                "episode_refs": ["第1话"],
                "confidence": "community",
                "source_url": "https://www.odakyu.jp/station/shimo_kitazawa/",
            },
        },
        {
            "type": "Feature",
            "geometry": {"type": "Point", "coordinates": [139.67103, 35.66317]},
            "properties": {
                "subject_id": "328609",
                "name": "下北泽一番街",
                "episode_refs": ["第2话"],
                "confidence": "community",
                "source_url": "https://www.shimokita1ban.com/",
            },
        },
    ],
}
