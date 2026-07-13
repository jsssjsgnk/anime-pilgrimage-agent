"""Deterministic base selection, clustering, schedule packing, and validation."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, timedelta
from uuid import UUID
from zoneinfo import ZoneInfo

from pilgrimage_agent.domain.models import GeoCoordinate, PilgrimagePoint, RouteA, RouteMatrix
from pilgrimage_agent.domain.planning import (
    AccessSelection,
    BaseCandidate,
    DayPlan,
    OmissionCode,
    OmissionReason,
    PlanningConstraints,
    PlanValidationReport,
    RouteBPlan,
    ScheduledVisit,
    ValidationIssue,
)
from pilgrimage_agent.planning.geo import google_maps_direction_urls, haversine_meters


def choose_base(
    candidates: tuple[BaseCandidate, ...],
    points: tuple[PilgrimagePoint, ...],
) -> BaseCandidate:
    if not candidates:
        raise ValueError("at least one base candidate is required")
    if not points:
        return min(candidates, key=lambda candidate: candidate.base_id)

    def score(candidate: BaseCandidate) -> tuple[float, str]:
        total = sum(
            haversine_meters(
                candidate.coordinate,
                GeoCoordinate(latitude=point.latitude, longitude=point.longitude),
            )
            for point in points
        )
        return total, candidate.base_id

    return min(candidates, key=score)


def cluster_points(
    points: tuple[PilgrimagePoint, ...],
    day_count: int,
) -> tuple[tuple[PilgrimagePoint, ...], ...]:
    """Create stable contiguous geographic clusters without dropping any point."""

    if day_count < 1:
        raise ValueError("day_count must be positive")
    clusters: list[list[PilgrimagePoint]] = [[] for _ in range(day_count)]
    ordered = sorted(points, key=lambda point: (point.longitude, point.latitude, str(point.id)))
    for index, point in enumerate(ordered):
        cluster_index = min(day_count - 1, index * day_count // max(1, len(ordered)))
        clusters[cluster_index].append(point)
    return tuple(tuple(cluster) for cluster in clusters)


@dataclass(slots=True)
class _DayState:
    date: date
    window_start: datetime
    window_end: datetime
    visits: list[ScheduledVisit]
    current_index: int
    current_time: datetime
    path_distance: float


def _daily_windows(constraints: PlanningConstraints) -> list[_DayState]:
    timezone = ZoneInfo(constraints.timezone)
    days = (constraints.end_date - constraints.start_date).days + 1
    states: list[_DayState] = []
    for offset in range(days):
        current_date = constraints.start_date + timedelta(days=offset)
        window_start = datetime.combine(current_date, constraints.day_start, timezone)
        window_end = datetime.combine(current_date, constraints.day_end, timezone)
        if current_date == constraints.start_date:
            arrival_ready = constraints.arrival_at.astimezone(timezone) + timedelta(
                minutes=constraints.arrival_buffer_minutes
            )
            window_start = max(window_start, arrival_ready)
        if current_date == constraints.end_date:
            depart_by = constraints.departure_at.astimezone(timezone) - timedelta(
                minutes=constraints.departure_buffer_minutes
            )
            window_end = min(window_end, depart_by)
        states.append(
            _DayState(
                date=current_date,
                window_start=window_start,
                window_end=window_end,
                visits=[],
                current_index=0,
                current_time=window_start,
                path_distance=0,
            )
        )
    return states


def _metric(matrix: tuple[tuple[float | None, ...], ...], first: int, second: int) -> float:
    value = matrix[first][second]
    if value is None or value < 0:
        raise ValueError("route matrix contains an unavailable metric")
    return value


def _point_window(
    constraints: PlanningConstraints,
    point_id: UUID,
    day: date,
) -> tuple[datetime, datetime] | None:
    timezone = ZoneInfo(constraints.timezone)
    for window in constraints.visit_windows:
        if window.point_id == point_id:
            return (
                datetime.combine(day, window.opens_at, timezone),
                datetime.combine(day, window.closes_at, timezone),
            )
    return None


def build_route_b(
    *,
    route_a: RouteA,
    base: BaseCandidate,
    matrix: RouteMatrix,
    constraints: PlanningConstraints,
    access: AccessSelection | None = None,
) -> RouteBPlan:
    """Pack points into bounded daily windows; every omission receives one reason."""

    points = tuple(route_a.points)
    expected_size = len(points) + 1
    if len(matrix.distances_meters) != expected_size:
        raise ValueError("matrix must contain base followed by every Route A point")
    point_index = {point.id: index + 1 for index, point in enumerate(points)}
    states = _daily_windows(constraints)
    clusters = cluster_points(points, len(states))
    assigned_day = {
        point.id: day_index
        for day_index, cluster in enumerate(clusters)
        for point in cluster
    }
    ordered = sorted(
        points,
        key=lambda point: (
            point.id not in constraints.must_visit_point_ids,
            assigned_day[point.id],
            point.longitude,
            str(point.id),
        ),
    )
    omitted: dict[UUID, OmissionReason] = {}
    for point in ordered:
        if point.id in constraints.excluded_point_ids:
            omitted[point.id] = OmissionReason(
                code=OmissionCode.EXCLUDED,
                detail="User explicitly excluded this Route A point.",
            )
            continue
        candidate_days = [assigned_day[point.id], *range(len(states))]
        placed = False
        walking_blocked = False
        time_blocked = False
        for day_index in dict.fromkeys(candidate_days):
            state = states[day_index]
            if state.window_end <= state.window_start:
                time_blocked = True
                continue
            index = point_index[point.id]
            try:
                incoming_distance = _metric(
                    matrix.distances_meters, state.current_index, index
                )
                incoming_duration = _metric(
                    matrix.durations_seconds, state.current_index, index
                )
                return_distance = _metric(matrix.distances_meters, index, 0)
                return_duration = _metric(matrix.durations_seconds, index, 0)
            except (IndexError, ValueError):
                omitted[point.id] = OmissionReason(
                    code=OmissionCode.INVALID_MATRIX,
                    detail="Routing matrix lacks a usable distance or duration.",
                )
                placed = True
                break
            projected_walk = state.path_distance + incoming_distance + return_distance
            if projected_walk > constraints.max_walking_meters_per_day:
                walking_blocked = True
                continue
            visit_start = state.current_time + timedelta(seconds=incoming_duration)
            window = _point_window(constraints, point.id, state.date)
            if window is not None:
                visit_start = max(visit_start, window[0])
            visit_end = visit_start + timedelta(minutes=constraints.visit_minutes)
            if window is not None and visit_end > window[1]:
                time_blocked = True
                continue
            if visit_end + timedelta(seconds=return_duration) > state.window_end:
                time_blocked = True
                continue
            state.visits.append(
                ScheduledVisit(
                    point_id=point.id,
                    start_at=visit_start,
                    end_at=visit_end,
                    incoming_distance_meters=incoming_distance,
                    incoming_duration_seconds=incoming_duration,
                )
            )
            state.current_index = index
            state.current_time = visit_end
            state.path_distance += incoming_distance
            placed = True
            break
        if not placed:
            code = OmissionCode.WALKING_LIMIT if walking_blocked else OmissionCode.TIME_WINDOW
            detail = (
                "Adding this point would exceed the daily walking limit."
                if walking_blocked and not time_blocked
                else "No daily visit window can fit travel, visit, and departure buffers."
            )
            omitted[point.id] = OmissionReason(code=code, detail=detail)

    day_plans: list[DayPlan] = []
    for state in states:
        if state.visits:
            return_distance = _metric(matrix.distances_meters, state.current_index, 0)
            coordinates = [base.coordinate]
            by_id = {point.id: point for point in points}
            coordinates.extend(
                GeoCoordinate(
                    latitude=by_id[visit.point_id].latitude,
                    longitude=by_id[visit.point_id].longitude,
                )
                for visit in state.visits
            )
            coordinates.append(base.coordinate)
            maps_urls = google_maps_direction_urls(tuple(coordinates))
        else:
            return_distance = 0
            maps_urls = ()
        day_plans.append(
            DayPlan(
                date=state.date,
                window_start=state.window_start,
                window_end=state.window_end,
                visits=tuple(state.visits),
                walking_distance_meters=state.path_distance + return_distance,
                maps_urls=maps_urls,
            )
        )
    return RouteBPlan(
        route_a_point_ids=frozenset(point_index),
        base=base,
        days=tuple(day_plans),
        omitted_reasons=omitted,
        matrix_status=(
            "straight_line_estimate"
            if matrix.provenance.provider == "haversine"
            else "road"
        ),
        access=access,
    )


def validate_route_b(
    plan: RouteBPlan,
    constraints: PlanningConstraints,
) -> PlanValidationReport:
    issues: list[ValidationIssue] = []
    scheduled = {visit.point_id for day in plan.days for visit in day.visits}
    for point_id in constraints.must_visit_point_ids - scheduled:
        issues.append(
            ValidationIssue(
                code="missing_must_visit",
                detail="A required Route A point was not scheduled.",
                point_id=point_id,
            )
        )
    for point_id in constraints.excluded_point_ids & scheduled:
        issues.append(
            ValidationIssue(
                code="scheduled_excluded",
                detail="An explicitly excluded point was scheduled.",
                point_id=point_id,
            )
        )
    for day in plan.days:
        if day.walking_distance_meters > constraints.max_walking_meters_per_day + 0.01:
            issues.append(
                ValidationIssue(
                    code="walking_limit",
                    detail="Daily walking distance exceeds the configured limit.",
                    day=day.date,
                )
            )
        previous_end = day.window_start
        for visit in day.visits:
            if visit.start_at < previous_end or visit.end_at > day.window_end:
                issues.append(
                    ValidationIssue(
                        code="time_window",
                        detail="A visit is outside or overlaps its daily planning window.",
                        point_id=visit.point_id,
                        day=day.date,
                    )
                )
            previous_end = visit.end_at
    return PlanValidationReport(valid=not issues, issues=tuple(issues))
