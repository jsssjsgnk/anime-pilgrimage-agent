"""Read-only openrouteservice geocoding, directions, and matrix providers."""

from __future__ import annotations

from datetime import timedelta
from typing import Any

from pydantic import TypeAdapter, ValidationError

from pilgrimage_agent.domain.models import (
    DirectionsQuery,
    GeoCoordinate,
    MatrixQuery,
    PlaceCandidate,
    PlaceSearchQuery,
    PlaceSearchResult,
    RouteLeg,
    RouteMatrix,
)
from pilgrimage_agent.providers.base import ProviderError, ProviderErrorKind, missing_credential
from pilgrimage_agent.providers.cache import MemoryProviderCache, request_fingerprint
from pilgrimage_agent.providers.common import provenance
from pilgrimage_agent.providers.http import SafeHttpClient

_DICT = TypeAdapter(dict[str, Any])


class OpenRouteServiceProvider:
    provider = "openrouteservice"

    def __init__(self, *, api_key: str | None, http: SafeHttpClient) -> None:
        self.api_key = api_key
        self.http = http
        self.geocode_cache: MemoryProviderCache[PlaceSearchResult] = MemoryProviderCache()

    def _headers(self) -> dict[str, str]:
        if not self.api_key:
            raise missing_credential(self.provider, "ORS_API_KEY")
        return {"Authorization": self.api_key, "Accept": "application/json"}

    async def geocode(self, query: PlaceSearchQuery) -> PlaceSearchResult:
        fingerprint = request_fingerprint(f"{self.provider}-geocode", query)
        cached = self.geocode_cache.get(fingerprint)
        if cached is not None:
            return cached
        raw = await self.http.request_json(
            "GET",
            "https://api.openrouteservice.org/geocode/search",
            headers=self._headers(),
            params={"text": query.text, "lang": query.language, "size": query.limit},
        )
        try:
            payload = _DICT.validate_python(raw)
            features = payload.get("features", [])
            if not isinstance(features, list):
                raise ValueError
            result_provenance = provenance(
                self.provider,
                "https://api.openrouteservice.org/geocode/search",
                ttl=timedelta(days=30),
            )
            candidates = tuple(
                self._place(feature, result_provenance)
                for feature in features[: query.limit]
                if isinstance(feature, dict)
            )
            result = PlaceSearchResult(candidates=candidates, provenance=result_provenance)
        except (ValidationError, ValueError, KeyError, TypeError, IndexError):
            raise ProviderError(
                ProviderErrorKind.UPSTREAM,
                self.provider,
                "The geocoder response did not match the expected schema.",
            ) from None
        self.geocode_cache.put(
            provider=self.provider,
            fingerprint=fingerprint,
            value=result,
            ttl=timedelta(days=30),
        )
        return result

    @staticmethod
    def _place(feature: dict[str, Any], item_provenance: Any) -> PlaceCandidate:
        geometry = feature["geometry"]
        properties = feature["properties"]
        coordinates = geometry["coordinates"]
        return PlaceCandidate(
            label=str(properties["label"]),
            coordinate=GeoCoordinate(latitude=coordinates[1], longitude=coordinates[0]),
            region=str(properties["region"]) if properties.get("region") else None,
            country=str(properties["country"]) if properties.get("country") else None,
            provenance=item_provenance,
        )

    async def directions(self, query: DirectionsQuery) -> RouteLeg:
        raw = await self.http.request_json(
            "POST",
            f"https://api.openrouteservice.org/v2/directions/{query.profile}",
            headers=self._headers(),
            json_body={
                "coordinates": [
                    [coordinate.longitude, coordinate.latitude]
                    for coordinate in query.coordinates
                ]
            },
        )
        try:
            payload = _DICT.validate_python(raw)
            route = payload["routes"][0]
            summary = route["summary"]
            return RouteLeg(
                distance_meters=summary["distance"],
                duration_seconds=summary["duration"],
                encoded_geometry=route.get("geometry"),
                provenance=provenance(
                    self.provider,
                    "https://api.openrouteservice.org/v2/directions",
                    ttl=timedelta(days=1),
                ),
            )
        except (ValidationError, ValueError, KeyError, TypeError, IndexError):
            raise ProviderError(
                ProviderErrorKind.UPSTREAM,
                self.provider,
                "The directions response did not match the expected schema.",
            ) from None

    async def matrix(self, query: MatrixQuery) -> RouteMatrix:
        raw = await self.http.request_json(
            "POST",
            f"https://api.openrouteservice.org/v2/matrix/{query.profile}",
            headers=self._headers(),
            json_body={
                "locations": [
                    [coordinate.longitude, coordinate.latitude]
                    for coordinate in query.coordinates
                ],
                "metrics": ["distance", "duration"],
            },
        )
        try:
            payload = _DICT.validate_python(raw)
            return RouteMatrix(
                durations_seconds=payload["durations"],
                distances_meters=payload["distances"],
                provenance=provenance(
                    self.provider,
                    "https://api.openrouteservice.org/v2/matrix",
                    ttl=timedelta(days=1),
                ),
            )
        except (ValidationError, ValueError, KeyError, TypeError):
            raise ProviderError(
                ProviderErrorKind.UPSTREAM,
                self.provider,
                "The matrix response did not match the expected schema.",
            ) from None


class FixtureOpenRouteServiceProvider:
    provider = "openrouteservice-fixture"

    async def geocode(self, query: PlaceSearchQuery) -> PlaceSearchResult:
        prov = provenance(
            self.provider,
            "https://openrouteservice.org/dev/#/api-docs/geocode",
            ttl=timedelta(days=365),
        )
        candidates: tuple[PlaceCandidate, ...] = ()
        if "下北" in query.text or "shimokita" in query.text.casefold():
            candidates = (
                PlaceCandidate(
                    label="下北沢駅, 世田谷区, 東京都, 日本",
                    coordinate=GeoCoordinate(latitude=35.6615, longitude=139.6669),
                    region="東京都",
                    country="日本",
                    provenance=prov,
                ),
            )
        return PlaceSearchResult(candidates=candidates[: query.limit], provenance=prov)

    async def directions(self, query: DirectionsQuery) -> RouteLeg:
        return RouteLeg(
            distance_meters=820.0,
            duration_seconds=660.0,
            encoded_geometry="fixture-encoded-polyline",
            provenance=provenance(
                self.provider,
                "https://openrouteservice.org/dev/#/api-docs/v2/directions",
                ttl=timedelta(days=365),
            ),
        )

    async def matrix(self, query: MatrixQuery) -> RouteMatrix:
        size = len(query.coordinates)
        durations = tuple(
            tuple(
                0.0 if row == column else float(abs(row - column) * 600)
                for column in range(size)
            )
            for row in range(size)
        )
        distances = tuple(
            tuple(
                0.0 if row == column else float(abs(row - column) * 750)
                for column in range(size)
            )
            for row in range(size)
        )
        return RouteMatrix(
            durations_seconds=durations,
            distances_meters=distances,
            provenance=provenance(
                self.provider,
                "https://openrouteservice.org/dev/#/api-docs/v2/matrix",
                ttl=timedelta(days=365),
            ),
        )
