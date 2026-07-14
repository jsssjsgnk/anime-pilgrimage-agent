"""Deterministic helpers for the integrated Agent planning path."""

from __future__ import annotations

from datetime import datetime, time, timedelta
from math import cos, radians
from uuid import UUID
from zoneinfo import ZoneInfo

from pilgrimage_agent.domain.models import (
    DataStatus,
    FlightSearchResult,
    GeoCoordinate,
    RouteA,
    TripRequest,
)
from pilgrimage_agent.domain.planning import (
    AccessMode,
    AccessOption,
    AccessSelection,
    BaseCandidate,
    OmissionCode,
    OmissionReason,
    PlanningOptions,
    RouteBPlan,
)
from pilgrimage_agent.providers.common import provenance

MAX_MATRIX_POINTS = 49


def walking_limit(request: TripRequest) -> float:
    if request.max_walking_meters_per_day is not None:
        return request.max_walking_meters_per_day
    return {"low": 3_000.0, "medium": 5_000.0, "high": 8_000.0}.get(
        request.walking_preference or "medium", 5_000.0
    )


def _route_centroid(route_a: RouteA) -> GeoCoordinate:
    if not route_a.points:
        raise ValueError("Route A needs at least one point before base planning")
    return GeoCoordinate(
        latitude=sum(point.latitude for point in route_a.points) / len(route_a.points),
        longitude=sum(point.longitude for point in route_a.points) / len(route_a.points),
    )


def build_planning_options(
    request: TripRequest,
    route_a: RouteA,
    *,
    geocoded_base: GeoCoordinate | None = None,
) -> PlanningOptions:
    """Build honest manual candidates and coordinate-derived base choices."""

    if not all(
        (
            request.origin,
            request.destination,
            request.start_date,
            request.end_date,
        )
    ):
        raise ValueError("origin, destination, start date and end date require confirmation")
    assert request.origin is not None
    assert request.destination is not None
    assert request.start_date is not None
    assert request.end_date is not None
    timezone = ZoneInfo("Asia/Tokyo")
    manual = provenance(
        "manual-intercity",
        None,
        ttl=timedelta(hours=12),
        status=DataStatus.NEEDS_CONFIRMATION,
    )
    access_options = (
        AccessOption(
            option_id="manual-inbound",
            mode=AccessMode.MANUAL,
            origin=request.origin,
            destination=request.destination,
            departure_at=datetime.combine(request.start_date, time(7), timezone),
            arrival_at=datetime.combine(request.start_date, time(9, 30), timezone),
            price=None,
            currency=None,
            confirmation_url=None,
            provenance=manual,
        ),
        AccessOption(
            option_id="manual-outbound",
            mode=AccessMode.MANUAL,
            origin=request.destination,
            destination=request.origin,
            departure_at=datetime.combine(request.end_date, time(18), timezone),
            arrival_at=datetime.combine(request.end_date, time(20, 30), timezone),
            price=None,
            currency=None,
            confirmation_url=None,
            provenance=manual,
        ),
    )
    centroid = _route_centroid(route_a)
    route_source = route_a.points[0].provenance.source_url
    estimated = provenance(
        "deterministic-base",
        str(route_source) if route_source else None,
        ttl=timedelta(hours=12),
        status=DataStatus.ESTIMATED,
    )
    bases = [
        BaseCandidate(
            base_id="route-centroid",
            name=f"{request.destination} · Route A 中心候选",
            coordinate=centroid,
            provenance=estimated,
        )
    ]
    if geocoded_base is not None and geocoded_base != centroid:
        bases.append(
            BaseCandidate(
                base_id="destination-center",
                name=f"{request.destination} · 地理编码中心候选",
                coordinate=geocoded_base,
                provenance=estimated,
            )
        )
    return PlanningOptions(
        access_options=access_options,
        base_candidates=tuple(bases),
        recommended_base_id="route-centroid",
        start_date=request.start_date,
        end_date=request.end_date,
    )


def with_flight_options(
    options: PlanningOptions,
    inbound: FlightSearchResult | None,
    outbound: FlightSearchResult | None,
    *,
    origin: str,
    destination: str,
) -> PlanningOptions:
    """Add bounded, labelled flight snapshots alongside manual choices."""

    converted: list[AccessOption] = []
    for direction, result, from_name, to_name in (
        ("inbound", inbound, origin, destination),
        ("outbound", outbound, destination, origin),
    ):
        if result is None:
            continue
        candidates = result.options[:5]
        if not candidates:
            continue
        fastest = min(item.duration_minutes for item in candidates)
        cheapest = min(item.price for item in candidates)
        fewest = min(item.stops for item in candidates)
        recommended = min(
            candidates,
            key=lambda item: (item.stops, item.duration_minutes, item.price, item.option_id),
        ).option_id
        for item in candidates:
            labels: list[str] = []
            if item.option_id == recommended:
                labels.append("recommended")
            if item.duration_minutes == fastest:
                labels.append("fastest")
            if item.price == cheapest:
                labels.append("cheapest")
            if item.stops == fewest:
                labels.append("fewest_transfers")
            first = item.segments[0]
            last = item.segments[-1]
            converted.append(
                AccessOption(
                    option_id=f"flight-{direction}-{item.option_id}",
                    mode=AccessMode.FLIGHT,
                    origin=from_name,
                    destination=to_name,
                    departure_at=first.departure_at,
                    arrival_at=last.arrival_at,
                    price=item.price,
                    currency=item.currency,
                    confirmation_url=item.confirmation_url,
                    comparison_labels=tuple(labels),
                    provenance=item.provenance,
                )
            )
    return options.model_copy(
        update={"access_options": (*options.access_options, *converted)}
    )


def confirmed_access(
    options: PlanningOptions,
    *,
    inbound_option_id: str,
    outbound_option_id: str,
) -> AccessSelection:
    by_id = {option.option_id: option for option in options.access_options}
    try:
        inbound = by_id[inbound_option_id]
        outbound = by_id[outbound_option_id]
    except KeyError:
        raise ValueError("confirmed access option is unavailable") from None
    return AccessSelection(inbound=inbound, outbound=outbound)


def _distance_rank(base: BaseCandidate, point_latitude: float, point_longitude: float) -> float:
    latitude_scale = cos(radians(base.coordinate.latitude))
    delta_latitude = point_latitude - base.coordinate.latitude
    delta_longitude = (point_longitude - base.coordinate.longitude) * latitude_scale
    return delta_latitude * delta_latitude + delta_longitude * delta_longitude


def matrix_candidate_route(
    route_a: RouteA,
    base: BaseCandidate,
    *,
    must_visit_point_ids: frozenset[UUID],
    excluded_point_ids: frozenset[UUID],
) -> tuple[RouteA, frozenset[UUID]]:
    """Bound ORS input while retaining the full Route A for final omission accounting."""

    route_ids = {point.id for point in route_a.points}
    unknown_constraints = (must_visit_point_ids | excluded_point_ids) - route_ids
    if unknown_constraints:
        raise ValueError("must/exclude constraints contain points outside Route A")
    ordered = sorted(
        (point for point in route_a.points if point.id not in excluded_point_ids),
        key=lambda point: (
            point.id not in must_visit_point_ids,
            _distance_rank(base, point.latitude, point.longitude),
            str(point.id),
        ),
    )
    selected = tuple(ordered[:MAX_MATRIX_POINTS])
    selected_ids = frozenset(point.id for point in selected)
    not_selected = frozenset(route_ids - selected_ids)
    return (
        RouteA(
            subject_id=route_a.subject_id,
            points=selected,
            is_complete=route_a.is_complete,
            warnings=route_a.warnings,
        ),
        not_selected,
    )


def restore_full_route_a_membership(
    candidate_plan: RouteBPlan,
    full_route_a: RouteA,
    *,
    matrix_omitted_ids: frozenset[UUID],
    excluded_point_ids: frozenset[UUID],
) -> RouteBPlan:
    omissions = dict(candidate_plan.omitted_reasons)
    for point_id in matrix_omitted_ids:
        if point_id in excluded_point_ids:
            omissions[point_id] = OmissionReason(
                code=OmissionCode.EXCLUDED,
                detail="User explicitly excluded this Route A point.",
            )
        else:
            omissions[point_id] = OmissionReason(
                code=OmissionCode.NO_AVAILABLE_DAY,
                detail=(
                    "The point remained in complete Route A but was outside the bounded "
                    "road-matrix candidate set for this trip."
                ),
            )
    return candidate_plan.model_copy(
        update={
            "route_a_point_ids": frozenset(point.id for point in full_route_a.points),
            "omitted_reasons": omissions,
        }
    )
