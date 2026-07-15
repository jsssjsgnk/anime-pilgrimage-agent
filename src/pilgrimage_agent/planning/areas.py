"""Stable Haversine DBSCAN area clustering over canonical visit places."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Literal
from uuid import NAMESPACE_URL, UUID, uuid5

from pilgrimage_agent.domain.models import StrictModel
from pilgrimage_agent.domain.workspace import AreaCluster, VisitPlace
from pilgrimage_agent.planning.geo import haversine_meters


class AreaClusteringPolicy(StrictModel):
    eps_meters: float = 1_200.0
    min_samples: int = 2
    max_internal_walking_minutes: int = 25
    visit_minutes_per_place: int = 30
    algorithm_version: str = "area-dbscan-v2"


def _neighbors(
    places: tuple[VisitPlace, ...], eps_meters: float
) -> dict[UUID, tuple[UUID, ...]]:
    return {
        place.place_id: tuple(
            sorted(
                (
                    candidate.place_id
                    for candidate in places
                    if haversine_meters(place.coordinate, candidate.coordinate)
                    <= eps_meters
                ),
                key=str,
            )
        )
        for place in places
    }


def _dbscan(
    places: tuple[VisitPlace, ...], policy: AreaClusteringPolicy
) -> tuple[tuple[UUID, ...], ...]:
    neighbor_map = _neighbors(places, policy.eps_meters)
    visited: set[UUID] = set()
    assigned: set[UUID] = set()
    clusters: list[tuple[UUID, ...]] = []
    for place_id in sorted(neighbor_map, key=str):
        if place_id in visited:
            continue
        visited.add(place_id)
        neighbors = neighbor_map[place_id]
        if len(neighbors) < policy.min_samples:
            continue
        members: set[UUID] = {place_id}
        assigned.add(place_id)
        queue = list(neighbors)
        while queue:
            candidate = queue.pop(0)
            if candidate not in visited:
                visited.add(candidate)
                candidate_neighbors = neighbor_map[candidate]
                if len(candidate_neighbors) >= policy.min_samples:
                    queue.extend(
                        item
                        for item in candidate_neighbors
                        if item not in queue and item not in members
                    )
            if candidate not in assigned:
                members.add(candidate)
                assigned.add(candidate)
        clusters.append(tuple(sorted(members, key=str)))
    all_ids = set(neighbor_map)
    for missing in sorted(all_ids - assigned, key=str):
        clusters.append((missing,))
    return tuple(sorted(clusters, key=lambda cluster: tuple(map(str, cluster))))


def _medoid(places: tuple[VisitPlace, ...]) -> VisitPlace:
    return min(
        places,
        key=lambda candidate: (
            sum(
                haversine_meters(candidate.coordinate, item.coordinate)
                for item in places
            ),
            str(candidate.place_id),
        ),
    )


def _road_duration(
    durations: Mapping[tuple[UUID, UUID], float], first: UUID, second: UUID
) -> float | None:
    return durations.get((first, second), durations.get((second, first)))


def _travel_time_correct(
    cluster: tuple[UUID, ...],
    by_id: dict[UUID, VisitPlace],
    policy: AreaClusteringPolicy,
    durations: Mapping[tuple[UUID, UUID], float] | None,
) -> tuple[tuple[UUID, ...], ...]:
    if durations is None or len(cluster) == 1:
        return (cluster,)
    medoid = _medoid(tuple(by_id[item] for item in cluster))
    retained: list[UUID] = []
    outliers: list[UUID] = []
    threshold = policy.max_internal_walking_minutes * 60
    for place_id in cluster:
        duration = _road_duration(durations, medoid.place_id, place_id)
        if duration is not None and duration > threshold:
            outliers.append(place_id)
        else:
            retained.append(place_id)
    result = [tuple(sorted(retained, key=str))] if retained else []
    result.extend((item,) for item in sorted(outliers, key=str))
    return tuple(result)


def cluster_places(
    places: tuple[VisitPlace, ...],
    *,
    policy: AreaClusteringPolicy | None = None,
    walking_durations_seconds: Mapping[tuple[UUID, UUID], float] | None = None,
) -> tuple[AreaCluster, ...]:
    """Cluster canonical places; input order cannot affect membership or IDs."""

    current = policy or AreaClusteringPolicy()
    if current.eps_meters <= 0 or current.min_samples < 1:
        raise ValueError("area DBSCAN parameters must be positive")
    ids = [place.place_id for place in places]
    if len(ids) != len(set(ids)):
        raise ValueError("canonical place IDs must be unique")
    if not places:
        return ()
    ordered = tuple(sorted(places, key=lambda place: str(place.place_id)))
    by_id = {place.place_id: place for place in ordered}
    corrected = tuple(
        segment
        for cluster in _dbscan(ordered, current)
        for segment in _travel_time_correct(
            cluster, by_id, current, walking_durations_seconds
        )
    )
    areas: list[AreaCluster] = []
    for members in corrected:
        member_places = tuple(by_id[item] for item in members)
        medoid = _medoid(member_places)
        distances = [
            haversine_meters(medoid.coordinate, item.coordinate)
            for item in member_places
            if item.place_id != medoid.place_id
        ]
        if walking_durations_seconds is None:
            travel_time_status: Literal["road", "haversine_fallback", "unverified"] = (
                "haversine_fallback"
            )
        else:
            has_complete_road_times = all(
                _road_duration(
                    walking_durations_seconds, medoid.place_id, item.place_id
                )
                is not None
                for item in member_places
                if item.place_id != medoid.place_id
            )
            travel_time_status = "road" if has_complete_road_times else "unverified"
        area_id = uuid5(
            NAMESPACE_URL, "area:" + ":".join(str(item) for item in sorted(members, key=str))
        )
        areas.append(
            AreaCluster(
                area_id=area_id,
                label=f"{medoid.canonical_name} 周边",
                representative_coordinate=medoid.coordinate,
                place_ids=tuple(sorted(members, key=str)),
                nearest_transport_nodes=tuple(
                    sorted(
                        {
                            item.transport_node
                            for item in member_places
                            if item.transport_node is not None
                        }
                    )
                ),
                estimated_visit_minutes=(
                    len(member_places) * current.visit_minutes_per_place
                    + round(sum(distances) / 80)
                ),
                internal_walking_meters=sum(distances),
                algorithm_version=current.algorithm_version,
                parameters={
                    "eps_meters": current.eps_meters,
                    "min_samples": current.min_samples,
                    "max_internal_walking_minutes": current.max_internal_walking_minutes,
                },
                confidence=0.9 if travel_time_status == "road" else 0.75,
                travel_time_status=travel_time_status,
                warnings=(
                    ("ORS walking times unavailable; area uses Haversine fallback.",)
                    if travel_time_status == "haversine_fallback"
                    else (
                        "Walking matrix coverage is partial; unverified pairs retain "
                        "Haversine membership.",
                    )
                    if travel_time_status == "unverified"
                    else ()
                ),
            )
        )
    membership = [place_id for area in areas for place_id in area.place_ids]
    if set(membership) != set(ids) or len(membership) != len(ids):
        raise RuntimeError("area clustering lost or duplicated a canonical place")
    return tuple(sorted(areas, key=lambda area: str(area.area_id)))
