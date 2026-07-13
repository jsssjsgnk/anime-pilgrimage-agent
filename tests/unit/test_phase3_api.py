"""Phase 3 planning options and Route B HTTP boundary."""

from fastapi.testclient import TestClient

from pilgrimage_agent.api.main import app


def test_planning_options_to_route_b_http_flow() -> None:
    with TestClient(app) as client:
        options_response = client.get("/api/planning/options")
        assert options_response.status_code == 200
        options = options_response.json()
        assert len(options["access_options"]) == 3
        assert options["recommended_base_id"] == "shimokitazawa"

        plan_response = client.post(
            "/api/subjects/328609/route-b",
            json={
                "inbound_option_id": "train-kyoto-tokyo-early",
                "outbound_option_id": "train-tokyo-kyoto-evening",
                "base_id": "shimokitazawa",
                "max_walking_meters_per_day": 5000,
                "must_visit_point_ids": [],
                "excluded_point_ids": [],
            },
        )
        assert plan_response.status_code == 200
        plan = plan_response.json()
        scheduled = [visit for day in plan["days"] for visit in day["visits"]]
        assert len(scheduled) == 3
        assert plan["omitted_reasons"] == {}
        assert plan["matrix_status"] == "road"
        assert all(day["maps_urls"] for day in plan["days"] if day["visits"])
