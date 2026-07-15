"""Relative-clock fixture scenario used by Phase 3 API and browser acceptance."""

from __future__ import annotations

from collections.abc import Callable
from datetime import date, datetime, time, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

from pilgrimage_agent.domain.models import (
    DataStatus,
    GeoCoordinate,
    MatrixQuery,
    PilgrimagePointQuery,
    RouteA,
)
from pilgrimage_agent.domain.planning import (
    AccessMode,
    AccessOption,
    BaseCandidate,
    ManualIntercityQuery,
    PlanningConstraints,
    PlanningOptions,
    RouteBPlan,
    RouteBRequest,
)
from pilgrimage_agent.planning.access import select_access_options
from pilgrimage_agent.planning.integrated import (
    matrix_candidate_route,
    restore_full_route_a_membership,
)
from pilgrimage_agent.planning.planner import build_route_b
from pilgrimage_agent.providers.common import provenance
from pilgrimage_agent.providers.intercity import FixtureManualIntercityProvider
from pilgrimage_agent.providers.ors import FixtureOpenRouteServiceProvider
from pilgrimage_agent.providers.points import FixturePilgrimagePointProvider, build_route_a


def _scenario(
    today: date,
) -> tuple[tuple[AccessOption, ...], tuple[BaseCandidate, ...], date, date]:
    timezone = ZoneInfo("Asia/Tokyo")
    start = today + timedelta(days=60)
    end = start + timedelta(days=2)
    manual_provenance = provenance(
        "manual-intercity-fixture",
        "https://global.jr-central.co.jp/en/",
        ttl=timedelta(days=365),
        status=DataStatus.NEEDS_CONFIRMATION,
    )
    access = (
        AccessOption(
            option_id="train-kyoto-tokyo-early",
            mode=AccessMode.TRAIN,
            origin="京都",
            destination="东京",
            departure_at=datetime.combine(start, time(6, 45), timezone),
            arrival_at=datetime.combine(start, time(9, 0), timezone),
            price=13_970,
            currency="JPY",
            confirmation_url="https://global.jr-central.co.jp/en/onlinebooking/",
            provenance=manual_provenance,
        ),
        AccessOption(
            option_id="bus-kyoto-tokyo-night",
            mode=AccessMode.BUS,
            origin="京都",
            destination="东京",
            departure_at=datetime.combine(start - timedelta(days=1), time(22, 30), timezone),
            arrival_at=datetime.combine(start, time(6, 45), timezone),
            price=6_800,
            currency="JPY",
            confirmation_url=None,
            provenance=manual_provenance,
        ),
        AccessOption(
            option_id="train-tokyo-kyoto-evening",
            mode=AccessMode.TRAIN,
            origin="东京",
            destination="京都",
            departure_at=datetime.combine(end, time(19, 30), timezone),
            arrival_at=datetime.combine(end, time(21, 45), timezone),
            price=13_970,
            currency="JPY",
            confirmation_url="https://global.jr-central.co.jp/en/onlinebooking/",
            provenance=manual_provenance,
        ),
    )
    base_provenance = provenance(
        "fixture-base",
        "https://www.odakyu.jp/station/shimo_kitazawa/",
        ttl=timedelta(days=365),
        status=DataStatus.NEEDS_CONFIRMATION,
    )
    bases = (
        BaseCandidate(
            base_id="shimokitazawa",
            name="下北泽站周边",
            coordinate=GeoCoordinate(latitude=35.6615, longitude=139.6669),
            provenance=base_provenance,
        ),
        BaseCandidate(
            base_id="shinjuku",
            name="新宿站周边",
            coordinate=GeoCoordinate(latitude=35.6896, longitude=139.7006),
            provenance=type(base_provenance).model_validate(
                {
                    **base_provenance.model_dump(),
                    "source_url": "https://www.jreast.co.jp/e/stations/e866.html",
                }
            ),
        ),
    )
    return access, bases, start, end


async def planning_options(
    *, today: Callable[[], date] = date.today
) -> PlanningOptions:
    access, bases, start, end = _scenario(today())
    timezone = ZoneInfo("Asia/Tokyo")
    inbound_provider = FixtureManualIntercityProvider(access)
    inbound = await inbound_provider.fetch(
        ManualIntercityQuery(
            origin="京都",
            destination="东京",
            earliest_departure=datetime.combine(start - timedelta(days=1), time(20), timezone),
            latest_arrival=datetime.combine(start, time(10), timezone),
        )
    )
    outbound = await inbound_provider.fetch(
        ManualIntercityQuery(
            origin="东京",
            destination="京都",
            earliest_departure=datetime.combine(end, time(18), timezone),
            latest_arrival=datetime.combine(end, time(23), timezone),
        )
    )
    if not inbound or not outbound:
        raise RuntimeError("relative-clock fixture access options are inconsistent")
    return PlanningOptions(
        access_options=(*inbound, *outbound),
        base_candidates=bases,
        recommended_base_id="shimokitazawa",
        start_date=start,
        end_date=end,
    )


async def plan_demo_route_b(
    route_a: RouteA,
    request: RouteBRequest,
    *,
    today: Callable[[], date] = date.today,
) -> RouteBPlan:
    options = await planning_options(today=today)
    by_option = {option.option_id: option for option in options.access_options}
    by_base = {base.base_id: base for base in options.base_candidates}
    if request.inbound_option_id not in by_option or request.outbound_option_id not in by_option:
        raise ValueError("selected access option is unavailable")
    if request.base_id not in by_base:
        raise ValueError("selected base is unavailable")
    inbound = by_option[request.inbound_option_id]
    outbound = by_option[request.outbound_option_id]
    access = select_access_options(inbound_options=(inbound,), outbound_options=(outbound,))
    base = by_base[request.base_id]
    constraints = PlanningConstraints(
        start_date=options.start_date,
        end_date=options.end_date,
        arrival_at=inbound.arrival_at,
        departure_at=outbound.departure_at,
        max_walking_meters_per_day=request.max_walking_meters_per_day,
        must_visit_point_ids=request.must_visit_point_ids,
        excluded_point_ids=request.excluded_point_ids,
    )
    candidate_route, matrix_omitted_ids = matrix_candidate_route(
        route_a,
        base,
        must_visit_point_ids=constraints.must_visit_point_ids,
        excluded_point_ids=constraints.excluded_point_ids,
    )
    coordinates = (
        base.coordinate,
        *(
            GeoCoordinate(latitude=point.latitude, longitude=point.longitude)
            for point in candidate_route.points
        ),
    )
    matrix = await FixtureOpenRouteServiceProvider().matrix(
        MatrixQuery(coordinates=coordinates)
    )
    candidate_plan = build_route_b(
        route_a=candidate_route,
        base=base,
        matrix=matrix,
        constraints=constraints,
        access=access,
    )
    return restore_full_route_a_membership(
        candidate_plan,
        route_a,
        matrix_omitted_ids=matrix_omitted_ids,
        excluded_point_ids=constraints.excluded_point_ids,
    )


async def fixture_route_a(subject_id: str) -> RouteA:
    provider = FixturePilgrimagePointProvider(Path("unused"))
    result = await provider.fetch(
        PilgrimagePointQuery(subject_id=subject_id, provider="fixture")
    )
    return build_route_a(result, subject_id=subject_id)
