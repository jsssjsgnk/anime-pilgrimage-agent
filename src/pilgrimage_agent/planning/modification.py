"""Deterministic natural-language local itinerary modification."""

from __future__ import annotations

import re

from pilgrimage_agent.agent.schemas import PlanModification
from pilgrimage_agent.domain.models import GeoCoordinate, RouteA
from pilgrimage_agent.domain.planning import (
    OmissionCode,
    OmissionReason,
    RouteBPlan,
    ScheduledVisit,
)
from pilgrimage_agent.planning.geo import google_maps_direction_urls, haversine_meters

_CN_DAY = {"一": 1, "二": 2, "三": 3, "四": 4, "五": 5, "六": 6, "七": 7}


def parse_local_modification(instruction: str) -> PlanModification:
    day_match = re.search(r"第\s*([一二三四五六七\d]+)\s*天", instruction)
    percent_match = re.search(r"(\d{1,2})\s*%", instruction)
    if day_match is None:
        raise ValueError("The modification must identify one affected day")
    raw_day = day_match.group(1)
    day = int(raw_day) if raw_day.isdigit() else _CN_DAY.get(raw_day)
    if day is None:
        raise ValueError("The requested day is outside the supported itinerary")
    percent = int(percent_match.group(1)) if percent_match else 30
    return PlanModification(
        target_day=day,
        walking_reduction_percent=percent,
        reason=instruction,
    )


def _point_coordinate(route_a: RouteA, visit: ScheduledVisit) -> GeoCoordinate:
    by_id = {point.id: point for point in route_a.points}
    point = by_id[visit.point_id]
    return GeoCoordinate(latitude=point.latitude, longitude=point.longitude)


def _estimated_path(
    base: GeoCoordinate,
    route_a: RouteA,
    visits: tuple[ScheduledVisit, ...],
) -> tuple[float, tuple[ScheduledVisit, ...], tuple[GeoCoordinate, ...]]:
    previous = base
    distance = 0.0
    updated: list[ScheduledVisit] = []
    coordinates = [base]
    for visit in visits:
        coordinate = _point_coordinate(route_a, visit)
        incoming = haversine_meters(previous, coordinate)
        distance += incoming
        updated.append(visit.model_copy(update={"incoming_distance_meters": incoming}))
        coordinates.append(coordinate)
        previous = coordinate
    if visits:
        distance += haversine_meters(previous, base)
        coordinates.append(base)
    return distance, tuple(updated), tuple(coordinates)


def replan_local_walking(
    plan: RouteBPlan,
    route_a: RouteA,
    modification: PlanModification,
) -> tuple[RouteBPlan, tuple[str, ...]]:
    index = modification.target_day - 1
    if index >= len(plan.days):
        raise ValueError("The requested day is outside this itinerary")
    original = plan.days[index]
    target = original.walking_distance_meters * (
        1 - modification.walking_reduction_percent / 100
    )
    retained = original.visits
    removed: list[ScheduledVisit] = []
    estimated, updated, coordinates = _estimated_path(
        plan.base.coordinate, route_a, retained
    )
    if retained:
        removed.insert(0, retained[-1])
        retained = retained[:-1]
        estimated, updated, coordinates = _estimated_path(
            plan.base.coordinate, route_a, retained
        )
    while retained and estimated > target:
        removed.insert(0, retained[-1])
        retained = retained[:-1]
        estimated, updated, coordinates = _estimated_path(
            plan.base.coordinate, route_a, retained
        )
    next_day = original.model_copy(
        update={
            "visits": updated,
            "walking_distance_meters": estimated,
            "maps_urls": google_maps_direction_urls(coordinates),
        }
    )
    days = list(plan.days)
    days[index] = next_day
    omissions = dict(plan.omitted_reasons)
    for visit in removed:
        omissions[visit.point_id] = OmissionReason(
            code=OmissionCode.WALKING_LIMIT,
            detail=(
                f"Removed by the confirmed Day {modification.target_day} local walking "
                f"reduction of {modification.walking_reduction_percent}%."
            ),
        )
    warnings = (
        "Only the selected day changed; all other day objects remain byte-for-byte stable.",
        "The modified day uses a labelled Haversine walking estimate and must be reconfirmed.",
    )
    return plan.model_copy(update={"days": tuple(days), "omitted_reasons": omissions}), warnings
