"""Explainable area-first, place-second deterministic itinerary planning."""

from __future__ import annotations

from collections import defaultdict
from datetime import date, datetime, time, timedelta
from itertools import pairwise
from uuid import NAMESPACE_URL, UUID, uuid5
from zoneinfo import ZoneInfo

from pydantic import Field, model_validator

from pilgrimage_agent.domain.models import (
    PlaceFact,
    StrictModel,
    SubjectIntent,
    TripRequest,
    WeatherForecastResult,
)
from pilgrimage_agent.domain.planning import AccessSelection, BaseCandidate, ValidationIssue
from pilgrimage_agent.domain.workspace import (
    AreaCluster,
    AreaTransitEdge,
    CandidateDecision,
    CandidateEdge,
    DerivedKnowledgeRule,
    ItineraryDay,
    ItineraryVersion,
    PlaceWalkingEdge,
    PlanningStrategy,
    ScheduledPlace,
    ScoreComponent,
    StructuredOmission,
    SubjectCoverage,
    TripCandidateGraph,
    VisitPlace,
)
from pilgrimage_agent.planning.geo import haversine_meters

PLANNER_VERSION = "hierarchical-planner-v2"


class HierarchicalPlanningRequest(StrictModel):
    trip_id: UUID
    requirements: TripRequest
    places: tuple[VisitPlace, ...] = Field(min_length=1)
    areas: tuple[AreaCluster, ...] = Field(min_length=1)
    base: BaseCandidate
    access: AccessSelection | None = None
    timezone: str = Field(min_length=1, max_length=80)
    strategies: tuple[PlanningStrategy, ...] = Field(min_length=2, max_length=4)
    must_visit_place_ids: frozenset[UUID] = frozenset()
    excluded_place_ids: frozenset[UUID] = frozenset()
    graph_version: int = Field(default=1, ge=1)
    itinerary_version: int = Field(default=1, ge=1)
    visit_minutes: int = Field(default=30, ge=10, le=180)
    fixed_day_assignments: dict[UUID, int] = Field(default_factory=dict)
    fixed_positions: dict[UUID, int] = Field(default_factory=dict)
    knowledge_rules: tuple[DerivedKnowledgeRule, ...] = ()
    walking_edges: tuple[PlaceWalkingEdge, ...] = ()
    area_transit_edges: tuple[AreaTransitEdge, ...] = ()
    place_facts: dict[UUID, PlaceFact] = Field(default_factory=dict)
    weather_forecast: WeatherForecastResult | None = None

    @model_validator(mode="after")
    def references_and_dates_are_valid(self) -> HierarchicalPlanningRequest:
        if self.requirements.start_date is None or self.requirements.end_date is None:
            raise ValueError("hierarchical planning requires confirmed travel dates")
        place_ids = {item.place_id for item in self.places}
        area_place_ids = {item for area in self.areas for item in area.place_ids}
        if area_place_ids != place_ids:
            raise ValueError("areas must contain every canonical place exactly once")
        if len(area_place_ids) != sum(len(area.place_ids) for area in self.areas):
            raise ValueError("one canonical place cannot belong to multiple areas")
        if not (self.must_visit_place_ids | self.excluded_place_ids).issubset(place_ids):
            raise ValueError("must/exclude references must belong to the candidate graph")
        if self.must_visit_place_ids & self.excluded_place_ids:
            raise ValueError("one place cannot be both required and excluded")
        if not set(self.fixed_day_assignments).issubset(place_ids):
            raise ValueError("fixed day assignments must reference candidate places")
        if not set(self.fixed_positions).issubset(place_ids):
            raise ValueError("fixed positions must reference candidate places")
        day_count = (self.requirements.end_date - self.requirements.start_date).days + 1
        if any(day < 1 or day > day_count for day in self.fixed_day_assignments.values()):
            raise ValueError("fixed place day is outside the confirmed trip")
        if any(position < 0 or position > 100 for position in self.fixed_positions.values()):
            raise ValueError("fixed position is outside the supported range")
        if len(self.strategies) != len(set(self.strategies)):
            raise ValueError("planning strategies must be unique")
        if any(
            edge.source_place_id not in place_ids or edge.target_place_id not in place_ids
            for edge in self.walking_edges
        ):
            raise ValueError("walking edges must reference candidate places")
        area_ids = {item.area_id for item in self.areas}
        if any(
            edge.source_area_id not in area_ids or edge.target_area_id not in area_ids
            for edge in self.area_transit_edges
        ):
            raise ValueError("transit edges must reference candidate areas")
        if not set(self.place_facts).issubset(place_ids):
            raise ValueError("place facts must reference candidate places")
        ZoneInfo(self.timezone)
        return self


class HierarchicalPlanningResult(StrictModel):
    candidate_graph: TripCandidateGraph
    itineraries: tuple[ItineraryVersion, ...] = Field(min_length=2)


def _walking_limit(request: TripRequest) -> float:
    if request.max_walking_meters_per_day is not None:
        return request.max_walking_meters_per_day
    return {"low": 3_000.0, "medium": 5_000.0, "high": 8_000.0}.get(
        request.walking_preference or "medium", 5_000.0
    )


def _priority_map(intents: tuple[SubjectIntent, ...]) -> dict[str, int]:
    return {
        subject_id: item.priority
        for item in intents
        if item.status == "confirmed"
        for subject_id in item.catalog_subject_ids
    }


def _primary_subjects(intents: tuple[SubjectIntent, ...]) -> frozenset[str]:
    return frozenset(
        subject_id
        for item in intents
        if item.is_primary and item.status == "confirmed"
        for subject_id in item.catalog_subject_ids
    )


def _area_components(
    area: AreaCluster,
    places: dict[UUID, VisitPlace],
    base: BaseCandidate,
    intents: tuple[SubjectIntent, ...],
) -> dict[str, float]:
    area_places = tuple(places[item] for item in area.place_ids)
    priorities = _priority_map(intents)
    primary = _primary_subjects(intents)
    appearance_subjects = {
        appearance.subject_id
        for place in area_places
        for appearance in place.subject_appearances
    }
    subject_priority = float(sum(priorities.get(item, 1) for item in appearance_subjects))
    primary_coverage = float(
        sum(
            1
            for place in area_places
            if primary
            and any(item.subject_id in primary for item in place.subject_appearances)
        )
    )
    shared_place_value = float(
        sum(max(0, len(place.subject_appearances) - 1) for place in area_places)
    )
    density = len(area_places) / max(1.0, area.internal_walking_meters / 1_000)
    base_distance = haversine_meters(
        base.coordinate, area.representative_coordinate
    ) / 1_000
    return {
        "subject_priority": subject_priority,
        "primary_coverage": primary_coverage,
        "shared_place_value": shared_place_value,
        "area_density": density,
        "base_distance_km": base_distance,
    }


def _strategy_score(strategy: PlanningStrategy, components: dict[str, float]) -> float:
    coverage = components["subject_priority"]
    primary = components["primary_coverage"]
    shared = components["shared_place_value"]
    density = components["area_density"]
    distance = components["base_distance_km"]
    if strategy is PlanningStrategy.PRIMARY_SUBJECT_FIRST:
        return coverage + primary * 5 + shared * 2 + density - distance * 0.1
    if strategy is PlanningStrategy.LOW_WALKING:
        return coverage + shared * 2 + density * 2 - distance * 2
    if strategy is PlanningStrategy.GEOGRAPHIC_EFFICIENCY:
        return coverage + shared + density * 4 - distance
    return coverage + primary * 2 + shared * 3 + density * 2 - distance * 0.5


def _candidate_graph(request: HierarchicalPlanningRequest) -> TripCandidateGraph:
    edges: list[CandidateEdge] = []
    for place in request.places:
        for appearance in place.subject_appearances:
            edges.append(
                CandidateEdge(
                    source_type="subject",
                    source_id=appearance.subject_id,
                    relation="appearance",
                    target_type="place",
                    target_id=str(place.place_id),
                )
            )
        for evidence_id in place.scene_evidence_ids:
            edges.append(
                CandidateEdge(
                    source_type="place",
                    source_id=str(place.place_id),
                    relation="supported_by",
                    target_type="scene_evidence",
                    target_id=str(evidence_id),
                )
            )
    for area in request.areas:
        for place_id in area.place_ids:
            edges.append(
                CandidateEdge(
                    source_type="area",
                    source_id=str(area.area_id),
                    relation="contains",
                    target_type="place",
                    target_id=str(place_id),
                )
            )
    for walking_edge_item in request.walking_edges:
        edges.append(
            CandidateEdge(
                source_type="place",
                source_id=str(walking_edge_item.source_place_id),
                relation="reachable",
                target_type="place",
                target_id=str(walking_edge_item.target_place_id),
            )
        )
    for area_edge_item in request.area_transit_edges:
        edges.append(
            CandidateEdge(
                source_type="area",
                source_id=str(area_edge_item.source_area_id),
                relation="reachable",
                target_type="area",
                target_id=str(area_edge_item.target_area_id),
            )
        )
    decisions = tuple(
        CandidateDecision(
            entity_type="place",
            entity_id=place.place_id,
            status=(
                "excluded"
                if place.place_id in request.excluded_place_ids
                else "included"
            ),
            reason_code=(
                "user_excluded"
                if place.place_id in request.excluded_place_ids
                else "source_grounded_candidate"
            ),
            detail=(
                "User explicitly excluded this canonical place."
                if place.place_id in request.excluded_place_ids
                else "Canonical place has visible scene evidence in this trip."
            ),
        )
        for place in sorted(request.places, key=lambda item: str(item.place_id))
    )
    graph_id = uuid5(
        NAMESPACE_URL,
        f"candidate-graph:{request.trip_id}:{request.graph_version}:"
        + ":".join(sorted(str(item.place_id) for item in request.places)),
    )
    return TripCandidateGraph(
        graph_id=graph_id,
        trip_id=request.trip_id,
        version=request.graph_version,
        subject_intent_ids=tuple(item.intent_id for item in request.requirements.subject_intents),
        place_ids=tuple(sorted((item.place_id for item in request.places), key=str)),
        area_ids=tuple(sorted((item.area_id for item in request.areas), key=str)),
        decisions=decisions,
        edges=tuple(
            sorted(
                edges,
                key=lambda item: (
                    item.source_type,
                    item.source_id,
                    item.relation,
                    item.target_id,
                ),
            )
        ),
        evidence_status=(
            "partial"
            if any(place.verification_status == "unverified" for place in request.places)
            else "complete"
        ),
        created_at=datetime.now(ZoneInfo(request.timezone)),
    )


def _path_distance(
    order: tuple[VisitPlace, ...], base: BaseCandidate
) -> float:
    coordinates = [base.coordinate, *(item.coordinate for item in order), base.coordinate]
    return sum(
        haversine_meters(first, second)
        for first, second in pairwise(coordinates)
    )


def _nearest_neighbor(
    places: tuple[VisitPlace, ...], base: BaseCandidate
) -> tuple[VisitPlace, ...]:
    remaining = list(sorted(places, key=lambda item: str(item.place_id)))
    current = base.coordinate
    ordered: list[VisitPlace] = []
    while remaining:
        selected = min(
            remaining,
            key=lambda item: (
                haversine_meters(current, item.coordinate),
                str(item.place_id),
            ),
        )
        ordered.append(selected)
        remaining.remove(selected)
        current = selected.coordinate
    return tuple(ordered)


def _two_opt(
    order: tuple[VisitPlace, ...], base: BaseCandidate
) -> tuple[VisitPlace, ...]:
    best = order
    best_distance = _path_distance(best, base)
    for _pass in range(2):
        improved = False
        for left in range(0, max(0, len(best) - 1)):
            for right in range(left + 2, len(best) + 1):
                candidate = (*best[:left], *reversed(best[left:right]), *best[right:])
                distance = _path_distance(candidate, base)
                if distance + 0.01 < best_distance:
                    best = candidate
                    best_distance = distance
                    improved = True
        if not improved:
            break
    return best


def _day_windows(request: HierarchicalPlanningRequest) -> tuple[tuple[datetime, datetime], ...]:
    start_date = request.requirements.start_date
    end_date = request.requirements.end_date
    assert start_date is not None
    assert end_date is not None
    timezone = ZoneInfo(request.timezone)
    windows: list[tuple[datetime, datetime]] = []
    for offset in range((end_date - start_date).days + 1):
        day = start_date + timedelta(days=offset)
        start = datetime.combine(day, time(10), timezone)
        end = datetime.combine(day, time(18), timezone)
        if request.access is not None and offset == 0:
            start = max(
                start,
                request.access.inbound.arrival_at.astimezone(timezone)
                + timedelta(minutes=90),
            )
        if request.access is not None and day == end_date:
            end = min(
                end,
                request.access.outbound.departure_at.astimezone(timezone)
                - timedelta(minutes=120),
            )
        windows.append((start, end))
    return tuple(windows)


def _closed_by_rule(
    place_id: UUID, day: date, rules: tuple[DerivedKnowledgeRule, ...]
) -> bool:
    for rule in rules:
        if rule.status != "active_constraint" or rule.rule_type != "closure_date_range":
            continue
        target_ids = {
            item.entity_id for item in rule.target_refs if item.entity_type == "place"
        }
        if str(place_id) not in target_ids:
            continue
        raw_start = rule.value.get("closed_from")
        raw_end = rule.value.get("closed_until")
        if not isinstance(raw_start, str) or not isinstance(raw_end, str):
            continue
        try:
            closed_from = date.fromisoformat(raw_start)
            closed_until = date.fromisoformat(raw_end)
        except ValueError:
            continue
        if closed_from <= day <= closed_until:
            return True
    return False


def _area_transit_edge(
    request: HierarchicalPlanningRequest, first: UUID, second: UUID
) -> AreaTransitEdge | None:
    return next(
        (
            edge
            for edge in request.area_transit_edges
            if {edge.source_area_id, edge.target_area_id} == {first, second}
        ),
        None,
    )


def _area_transfer_seconds(
    request: HierarchicalPlanningRequest,
    first: AreaCluster | None,
    second: AreaCluster,
) -> float:
    if first is None:
        distance = haversine_meters(
            request.base.coordinate, second.representative_coordinate
        )
        return max(15 * 60, distance / 13.9)
    edge = _area_transit_edge(request, first.area_id, second.area_id)
    if edge is not None:
        return float(edge.duration_seconds)
    distance = haversine_meters(
        first.representative_coordinate, second.representative_coordinate
    )
    return max(15 * 60, distance / 13.9)


def _walking_edge(
    request: HierarchicalPlanningRequest, first: UUID, second: UUID
) -> PlaceWalkingEdge | None:
    return next(
        (
            edge
            for edge in request.walking_edges
            if edge.source_place_id == first and edge.target_place_id == second
        ),
        None,
    )


def _fit_opening_window(
    request: HierarchicalPlanningRequest,
    place_id: UUID,
    proposed_start: datetime,
) -> tuple[datetime, datetime] | None:
    fact = request.place_facts.get(place_id)
    visit_duration = timedelta(minutes=request.visit_minutes)
    if fact is None or fact.match_confidence < 0.85:
        return proposed_start, proposed_start + visit_duration
    if fact.temporarily_closed is True:
        return None
    windows = tuple(
        item for item in fact.opening_windows if item.weekday == proposed_start.weekday()
    )
    if not windows:
        return proposed_start, proposed_start + visit_duration
    normalized = tuple(
        item for item in windows if item.opens_at is not None and item.closes_at is not None
    )
    if not normalized:
        if any(
            item.raw_text is not None
            and item.raw_text.strip().casefold() in {"closed", "休業", "定休日"}
            for item in windows
        ):
            return None
        return proposed_start, proposed_start + visit_duration
    for window in sorted(normalized, key=lambda item: item.opens_at or time.min):
        assert window.opens_at is not None and window.closes_at is not None
        opens = datetime.combine(proposed_start.date(), window.opens_at, proposed_start.tzinfo)
        closes = datetime.combine(
            proposed_start.date(), window.closes_at, proposed_start.tzinfo
        )
        if closes <= opens:
            closes += timedelta(days=1)
        visit_start = max(proposed_start, opens)
        visit_end = visit_start + visit_duration
        if visit_end <= closes:
            return visit_start, visit_end
    return None


def _weather_risk(
    request: HierarchicalPlanningRequest, day: date
) -> tuple[bool, bool]:
    if request.weather_forecast is None or not request.weather_forecast.available:
        return False, False
    window = next(
        (item for item in request.weather_forecast.windows if item.date == day), None
    )
    if window is None:
        return False, False
    rain = (window.precipitation_probability_max or 0) >= 60
    hard = (
        (window.precipitation_probability_max or 0) >= 90
        or (window.temperature_max_c is not None and window.temperature_max_c >= 38)
        or (window.temperature_min_c is not None and window.temperature_min_c <= -5)
    )
    return rain, hard


def _plan_strategy(
    request: HierarchicalPlanningRequest,
    graph: TripCandidateGraph,
    strategy: PlanningStrategy,
) -> ItineraryVersion:
    by_place = {item.place_id: item for item in request.places}
    components = {
        area.area_id: _area_components(
            area, by_place, request.base, request.requirements.subject_intents
        )
        for area in request.areas
    }
    area_order = tuple(
        sorted(
            request.areas,
            key=lambda item: (
                -_strategy_score(strategy, components[item.area_id]),
                str(item.area_id),
            ),
        )
    )
    windows = _day_windows(request)
    assignments: dict[int, list[AreaCluster]] = defaultdict(list)
    omissions: dict[UUID, StructuredOmission] = {}
    reachable_areas: list[AreaCluster] = []
    for area in area_order:
        base_distance = haversine_meters(
            request.base.coordinate, area.representative_coordinate
        )
        estimated_one_way_seconds = max(15 * 60, base_distance / 13.9)
        if estimated_one_way_seconds > 3 * 60 * 60:
            for place_id in area.place_ids:
                omissions[place_id] = StructuredOmission(
                    place_id=place_id,
                    reason_code="unreachable",
                    detail=(
                        "The area is outside the bounded three-hour estimated "
                        "one-way access radius from the selected base."
                    ),
                )
            continue
        reachable_areas.append(area)
    allocated_seconds = [0.0 for _window in windows]
    for area in reachable_areas:
        fixed_days = sorted(
            {
                request.fixed_day_assignments[place_id] - 1
                for place_id in area.place_ids
                if place_id in request.fixed_day_assignments
            }
        )
        candidate_days = fixed_days or list(range(len(windows)))
        choices: list[tuple[float, int, float]] = []
        for day_index in candidate_days:
            previous = assignments[day_index][-1] if assignments[day_index] else None
            transfer = _area_transfer_seconds(request, previous, area)
            available = (
                windows[day_index][1] - windows[day_index][0]
            ).total_seconds() - allocated_seconds[day_index]
            minimum_useful = request.visit_minutes * 60 + transfer
            if available + 0.01 < minimum_useful:
                continue
            strategy_penalty = (
                transfer * 2 if strategy is PlanningStrategy.LOW_WALKING else transfer
            )
            choices.append(
                (allocated_seconds[day_index] + strategy_penalty, day_index, transfer)
            )
        if not choices:
            for place_id in area.place_ids:
                omissions[place_id] = StructuredOmission(
                    place_id=place_id,
                    reason_code="time_limit",
                    detail="No confirmed day has enough time for this additional area.",
                )
            continue
        _score, selected_day, transfer = min(choices)
        assignments[selected_day].append(area)
        allocated_seconds[selected_day] += (
            transfer + area.estimated_visit_minutes * 60
        )

    days: list[ItineraryDay] = []
    walking_limit = _walking_limit(request.requirements)
    scheduled_ids: set[UUID] = set()
    for day_index, (window_start, window_end) in enumerate(windows):
        day_number = day_index + 1
        assigned_candidate_ids = {
            place_id
            for area in assignments[day_index]
            for place_id in area.place_ids
            if request.fixed_day_assignments.get(place_id, day_number) == day_number
        }
        assigned_candidate_ids.update(
            place_id
            for place_id, target_day in request.fixed_day_assignments.items()
            if target_day == day_number
        )
        candidates = tuple(
            by_place[place_id]
            for place_id in sorted(assigned_candidate_ids, key=str)
            if place_id not in request.excluded_place_ids
        )
        day_areas = tuple(
            area
            for area in request.areas
            if set(area.place_ids).intersection(assigned_candidate_ids)
        )
        area_ids = tuple(
            sorted(
                {area.area_id for area in day_areas},
                key=str,
            )
        )
        ordered_list = list(
            _two_opt(_nearest_neighbor(candidates, request.base), request.base)
        )
        for place_id, position in sorted(
            request.fixed_positions.items(), key=lambda item: (item[1], str(item[0]))
        ):
            selected = next(
                (item for item in ordered_list if item.place_id == place_id), None
            )
            if selected is not None:
                ordered_list.remove(selected)
                ordered_list.insert(min(position, len(ordered_list)), selected)
        rain_risk, hard_weather_risk = _weather_risk(
            request, window_start.date()
        )
        if rain_risk:
            original_position = {
                item.place_id: index for index, item in enumerate(ordered_list)
            }
            ordered_list.sort(
                key=lambda item: (
                    item.place_type != "facility",
                    original_position[item.place_id],
                )
            )
        ordered = tuple(ordered_list)
        visits: list[ScheduledPlace] = []
        local_origin = (
            day_areas[0].representative_coordinate
            if day_areas
            else request.base.coordinate
        )
        origin_area = day_areas[0] if day_areas else None
        transfer_distance = haversine_meters(request.base.coordinate, local_origin)
        transfer_seconds = max(15 * 60, transfer_distance / 13.9) if day_areas else 0.0
        current_coordinate = local_origin
        current_time = window_start + timedelta(seconds=transfer_seconds)
        effective_window_end = window_end - timedelta(seconds=transfer_seconds)
        walked = 0.0
        current_place_id: UUID | None = None
        current_area = origin_area
        for place in ordered:
            if _closed_by_rule(place.place_id, window_start.date(), request.knowledge_rules):
                omissions[place.place_id] = StructuredOmission(
                    place_id=place.place_id,
                    reason_code="visit_window",
                    detail="An accepted high-authority closure rule blocks this visit date.",
                )
                continue
            if hard_weather_risk and place.place_type != "facility":
                omissions[place.place_id] = StructuredOmission(
                    place_id=place.place_id,
                    reason_code="unverified",
                    detail=(
                        "The current forecast has an extreme outdoor risk; refresh or "
                        "confirm before scheduling this place."
                    ),
                )
                continue
            target_area = next(
                area for area in request.areas if place.place_id in area.place_ids
            )
            if current_place_id is not None and current_area == target_area:
                road_edge = _walking_edge(request, current_place_id, place.place_id)
            else:
                road_edge = None
            if road_edge is not None:
                incoming = road_edge.distance_meters
                duration_seconds = road_edge.duration_seconds
            elif current_place_id is not None and current_area != target_area:
                transit_edge = (
                    _area_transit_edge(request, current_area.area_id, target_area.area_id)
                    if current_area is not None
                    else None
                )
                if transit_edge is not None:
                    incoming = transit_edge.walking_seconds * 1.25
                    duration_seconds = float(transit_edge.duration_seconds)
                else:
                    area_distance = haversine_meters(
                        current_area.representative_coordinate,
                        target_area.representative_coordinate,
                    ) if current_area is not None else 0.0
                    incoming = 0.0
                    duration_seconds = max(15 * 60, area_distance / 13.9)
            else:
                incoming = haversine_meters(current_coordinate, place.coordinate)
                duration_seconds = incoming / 1.25
            if origin_area is not None and target_area.area_id != origin_area.area_id:
                return_edge = _area_transit_edge(
                    request, target_area.area_id, origin_area.area_id
                )
                if return_edge is not None:
                    return_distance = return_edge.walking_seconds * 1.25
                    return_duration = float(return_edge.duration_seconds)
                else:
                    area_distance = haversine_meters(
                        target_area.representative_coordinate,
                        origin_area.representative_coordinate,
                    )
                    return_distance = 0.0
                    return_duration = max(15 * 60, area_distance / 13.9)
            else:
                return_distance = haversine_meters(place.coordinate, local_origin)
                return_duration = return_distance / 1.25
            projected = walked + incoming + return_distance
            if projected > walking_limit:
                omissions[place.place_id] = StructuredOmission(
                    place_id=place.place_id,
                    reason_code="walking_limit",
                    detail="Scheduling this place would exceed the daily walking limit.",
                )
                continue
            visit_window = _fit_opening_window(
                request,
                place.place_id,
                current_time + timedelta(seconds=duration_seconds),
            )
            if visit_window is None:
                omissions[place.place_id] = StructuredOmission(
                    place_id=place.place_id,
                    reason_code="visit_window",
                    detail="Current place facts do not provide an open visit window.",
                )
                continue
            visit_start, visit_end = visit_window
            if visit_end + timedelta(seconds=return_duration) > effective_window_end:
                omissions[place.place_id] = StructuredOmission(
                    place_id=place.place_id,
                    reason_code="time_limit",
                    detail="Travel, visit and return cannot fit the confirmed daily window.",
                )
                continue
            visits.append(
                ScheduledPlace(
                    place_id=place.place_id,
                    area_id=next(
                        area.area_id
                        for area in request.areas
                        if place.place_id in area.place_ids
                    ),
                    sequence=len(visits),
                    start_at=visit_start,
                    end_at=visit_end,
                    incoming_distance_meters=incoming,
                    incoming_duration_seconds=duration_seconds,
                )
            )
            scheduled_ids.add(place.place_id)
            current_coordinate = place.coordinate
            current_time = visit_end
            walked += incoming
            current_place_id = place.place_id
            current_area = target_area
        if visits and current_area is not None and origin_area is not None:
            if current_area.area_id == origin_area.area_id:
                return_distance = haversine_meters(current_coordinate, local_origin)
                return_duration = return_distance / 1.25
            else:
                return_edge = _area_transit_edge(
                    request, current_area.area_id, origin_area.area_id
                )
                if return_edge is not None:
                    return_distance = return_edge.walking_seconds * 1.25
                    return_duration = float(return_edge.duration_seconds)
                else:
                    return_distance = 0.0
                    return_duration = _area_transfer_seconds(
                        request, current_area, origin_area
                    )
        else:
            return_distance = 0.0
            return_duration = 0.0
        total_walk = walked + return_distance
        days.append(
            ItineraryDay(
                date=window_start.date(),
                area_ids=area_ids,
                visits=tuple(visits),
                walking_distance_meters=total_walk,
                duration_minutes=max(
                    0,
                    round(
                        (
                            (current_time - window_start).total_seconds()
                            + return_duration
                            + transfer_seconds
                        )
                        / 60
                    ),
                ),
            )
        )
    for place_id in request.excluded_place_ids:
        omissions[place_id] = StructuredOmission(
            place_id=place_id,
            reason_code="excluded",
            detail="User explicitly excluded this canonical place.",
        )
    for place in request.places:
        if place.place_id not in scheduled_ids and place.place_id not in omissions:
            omissions[place.place_id] = StructuredOmission(
                place_id=place.place_id,
                reason_code="lower_strategy_score",
                detail="This candidate was not selected by the bounded strategy plan.",
            )

    intents = request.requirements.subject_intents
    appearances_by_subject: dict[str, set[UUID]] = defaultdict(set)
    for place in request.places:
        if place.place_id not in scheduled_ids:
            continue
        for appearance in place.subject_appearances:
            appearances_by_subject[appearance.subject_id].add(place.place_id)
    coverage = tuple(
        SubjectCoverage(
            subject_id=subject_id,
            priority=intent.priority,
            scheduled_place_ids=tuple(
                sorted(appearances_by_subject[subject_id], key=str)
            ),
            minimum_place_count=intent.minimum_place_count,
            minimum_satisfied=(
                intent.minimum_place_count is None
                or len(appearances_by_subject[subject_id])
                >= intent.minimum_place_count
            ),
        )
        for intent in intents
        if intent.status == "confirmed"
        for subject_id in intent.catalog_subject_ids
    )
    issues: list[ValidationIssue] = []
    for place_id in request.must_visit_place_ids - scheduled_ids:
        issues.append(
            ValidationIssue(
                code="missing_must_visit",
                detail="A required canonical place was not scheduled.",
                point_id=place_id,
            )
        )
    for item in coverage:
        if not item.minimum_satisfied:
            issues.append(
                ValidationIssue(
                    code="subject_minimum_coverage",
                    detail=f"Minimum coverage was not met for subject {item.subject_id}.",
                )
            )
    for day in days:
        if day.walking_distance_meters > walking_limit + 0.01:
            issues.append(
                ValidationIssue(
                    code="walking_limit",
                    detail="Daily walking exceeds the configured limit.",
                    day=day.date,
                )
            )
        for previous_visit, current_visit in pairwise(day.visits):
            if current_visit.start_at < previous_visit.end_at:
                issues.append(
                    ValidationIssue(
                        code="visit_overlap",
                        detail="Scheduled visits overlap or move backward in time.",
                        day=day.date,
                    )
                )
        for visit in day.visits:
            if visit.place_id in request.excluded_place_ids:
                issues.append(
                    ValidationIssue(
                        code="excluded_place_scheduled",
                        detail="An explicitly excluded place was scheduled.",
                        point_id=visit.place_id,
                        day=day.date,
                    )
                )
    if request.access is not None and days:
        first_visits = days[0].visits
        last_visits = days[-1].visits
        timezone = ZoneInfo(request.timezone)
        if first_visits and first_visits[0].start_at < (
            request.access.inbound.arrival_at.astimezone(timezone)
            + timedelta(minutes=90)
        ):
            issues.append(
                ValidationIssue(
                    code="inbound_buffer",
                    detail="The first visit violates the configured arrival buffer.",
                    day=days[0].date,
                )
            )
        if last_visits and last_visits[-1].end_at > (
            request.access.outbound.departure_at.astimezone(timezone)
            - timedelta(minutes=120)
        ):
            issues.append(
                ValidationIssue(
                    code="outbound_buffer",
                    detail="The last visit violates the configured departure buffer.",
                    day=days[-1].date,
                )
            )
    now = datetime.now(ZoneInfo(request.timezone))
    for place_id in scheduled_ids:
        fact = request.place_facts.get(place_id)
        if fact is None:
            continue
        if fact.provenance.source_url is None or fact.provenance.expires_at is None:
            issues.append(
                ValidationIssue(
                    code="provider_fact_provenance",
                    detail="A scheduled place fact lacks a source or refresh deadline.",
                    point_id=place_id,
                )
            )
        elif fact.provenance.expires_at <= now:
            issues.append(
                ValidationIssue(
                    code="stale_provider_fact",
                    detail="A scheduled place fact is stale and must be refreshed.",
                    point_id=place_id,
                )
            )
    score_components = tuple(
        ScoreComponent(
            entity_id=area.area_id,
            component=name,
            value=value,
            policy_version=PLANNER_VERSION,
        )
        for area in area_order
        for name, value in sorted(components[area.area_id].items())
    )
    itinerary_id = uuid5(
        NAMESPACE_URL,
        f"itinerary:{request.trip_id}:{graph.graph_id}:{strategy}:"
        f"{request.itinerary_version}",
    )
    total_duration = sum(day.duration_minutes for day in days)
    return ItineraryVersion(
        itinerary_id=itinerary_id,
        trip_id=request.trip_id,
        candidate_graph_id=graph.graph_id,
        version=request.itinerary_version,
        strategy=strategy,
        timezone=request.timezone,
        access=request.access,
        base=request.base,
        days=tuple(days),
        subject_coverage=coverage,
        total_walking_meters=sum(day.walking_distance_meters for day in days),
        total_duration_minutes=total_duration,
        omissions=tuple(omissions[item] for item in sorted(omissions, key=str)),
        score_components=score_components,
        evidence_refs=tuple(
            sorted(
                {
                    str(evidence_id)
                    for place in request.places
                    for evidence_id in place.scene_evidence_ids
                }
            )
        ),
        warnings=(
            "Base is an estimated area unless explicitly confirmed from a sourced candidate.",
        ),
        validation_issues=tuple(issues),
        created_at=datetime.now(ZoneInfo(request.timezone)),
    )


def plan_hierarchical_itineraries(
    request: HierarchicalPlanningRequest,
) -> HierarchicalPlanningResult:
    """Create independent strategy versions from one immutable candidate graph."""

    graph = _candidate_graph(request)
    itineraries = tuple(
        _plan_strategy(request, graph, strategy) for strategy in request.strategies
    )
    graph_places = set(graph.place_ids)
    for itinerary in itineraries:
        scheduled = {
            visit.place_id for day in itinerary.days for visit in day.visits
        }
        if not scheduled.issubset(graph_places):
            raise RuntimeError("itinerary scheduled a place outside the candidate graph")
        omitted = {item.place_id for item in itinerary.omissions}
        if scheduled | omitted != graph_places or scheduled & omitted:
            raise RuntimeError("every candidate place must be scheduled or omitted exactly once")
    return HierarchicalPlanningResult(candidate_graph=graph, itineraries=itineraries)
