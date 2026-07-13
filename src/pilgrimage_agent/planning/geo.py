"""Deterministic geospatial fallback and Google Maps URL construction."""

from __future__ import annotations

import math
from datetime import timedelta
from typing import Protocol
from urllib.parse import urlencode

from pilgrimage_agent.domain.models import (
    DataStatus,
    GeoCoordinate,
    MatrixQuery,
    RouteMatrix,
)
from pilgrimage_agent.providers.base import ProviderError
from pilgrimage_agent.providers.common import provenance

EARTH_RADIUS_METERS = 6_371_008.8
WALKING_METERS_PER_SECOND = 1.25
GOOGLE_MAPS_MAX_URL_LENGTH = 2_048
GOOGLE_MAPS_MOBILE_WAYPOINT_LIMIT = 3


class MatrixProvider(Protocol):
    async def matrix(self, query: MatrixQuery) -> RouteMatrix: ...


def haversine_meters(first: GeoCoordinate, second: GeoCoordinate) -> float:
    """Return straight-line distance using a fixed mean Earth radius."""

    lat1, lat2 = math.radians(first.latitude), math.radians(second.latitude)
    delta_lat = lat2 - lat1
    delta_lon = math.radians(second.longitude - first.longitude)
    value = (
        math.sin(delta_lat / 2) ** 2
        + math.cos(lat1) * math.cos(lat2) * math.sin(delta_lon / 2) ** 2
    )
    return 2 * EARTH_RADIUS_METERS * math.asin(math.sqrt(value))


def haversine_matrix(coordinates: tuple[GeoCoordinate, ...]) -> RouteMatrix:
    distances = tuple(
        tuple(haversine_meters(source, destination) for destination in coordinates)
        for source in coordinates
    )
    durations = tuple(
        tuple(distance / WALKING_METERS_PER_SECOND for distance in row)
        for row in distances
    )
    return RouteMatrix(
        durations_seconds=durations,
        distances_meters=distances,
        provenance=provenance(
            "haversine",
            "https://en.wikipedia.org/wiki/Haversine_formula",
            ttl=timedelta(days=365),
            status=DataStatus.ESTIMATED,
        ),
    )


async def matrix_with_fallback(provider: MatrixProvider, query: MatrixQuery) -> RouteMatrix:
    """Use ORS when available and explicit straight-line estimates on normalized failure."""

    try:
        result = await provider.matrix(query)
        if not isinstance(result, RouteMatrix):
            raise TypeError("matrix provider returned an invalid boundary type")
        return result
    except (ProviderError, TypeError):
        return haversine_matrix(query.coordinates)


def _coordinate_text(coordinate: GeoCoordinate) -> str:
    return f"{coordinate.latitude:.6f},{coordinate.longitude:.6f}"


def _maps_url(chunk: tuple[GeoCoordinate, ...]) -> str:
    parameters: dict[str, str] = {
        "api": "1",
        "origin": _coordinate_text(chunk[0]),
        "destination": _coordinate_text(chunk[-1]),
        "travelmode": "walking",
    }
    if len(chunk) > 2:
        parameters["waypoints"] = "|".join(_coordinate_text(point) for point in chunk[1:-1])
    return "https://www.google.com/maps/dir/?" + urlencode(parameters)


def google_maps_direction_urls(
    coordinates: tuple[GeoCoordinate, ...],
) -> tuple[str, ...]:
    """Build conservative cross-platform chunks with continuity and bounded length."""

    if len(coordinates) < 2:
        return ()
    maximum_locations = GOOGLE_MAPS_MOBILE_WAYPOINT_LIMIT + 2
    urls: list[str] = []
    start = 0
    while start < len(coordinates) - 1:
        end = min(len(coordinates), start + maximum_locations)
        chunk = coordinates[start:end]
        url = _maps_url(chunk)
        while len(url) > GOOGLE_MAPS_MAX_URL_LENGTH and len(chunk) > 2:
            chunk = chunk[:-1]
            url = _maps_url(chunk)
        if len(url) > GOOGLE_MAPS_MAX_URL_LENGTH:
            raise ValueError("a two-coordinate Google Maps URL exceeded 2,048 characters")
        urls.append(url)
        start += len(chunk) - 1
    return tuple(urls)
