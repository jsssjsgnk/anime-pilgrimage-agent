"""Relative-clock Kyoto-to-Tokyo three-day Phase 3 acceptance scenario."""

from datetime import date

from pilgrimage_agent.domain.planning import RouteBRequest
from pilgrimage_agent.planning.demo import fixture_route_a, plan_demo_route_b, planning_options


async def test_kyoto_tokyo_three_day_low_walking_scenario() -> None:
    clock = date(2030, 4, 1)
    options = await planning_options(today=lambda: clock)
    assert options.start_date > clock
    assert (options.end_date - options.start_date).days == 2
    assert {option.mode.value for option in options.access_options} == {"train", "bus"}

    route_a = await fixture_route_a("328609")
    plan = await plan_demo_route_b(
        route_a,
        RouteBRequest(
            inbound_option_id="train-kyoto-tokyo-early",
            outbound_option_id="train-tokyo-kyoto-evening",
            base_id=options.recommended_base_id,
            max_walking_meters_per_day=5_000,
        ),
        today=lambda: clock,
    )
    scheduled = [visit for day in plan.days for visit in day.visits]
    assert len(scheduled) == len(route_a.points)
    assert plan.omitted_reasons == {}
    assert plan.base.base_id == "shimokitazawa"
    assert plan.matrix_status == "road"
    assert all(day.walking_distance_meters <= 5_000 for day in plan.days)
    assert all(day.maps_urls for day in plan.days if day.visits)

    assert all(
        day.window_start <= visit.start_at < visit.end_at <= day.window_end
        for day in plan.days
        for visit in day.visits
    )
