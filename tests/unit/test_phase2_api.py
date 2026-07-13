"""HTTP contract for explicit subject confirmation and Route A."""

from fastapi.testclient import TestClient

from pilgrimage_agent.api.main import app


def test_subject_confirmation_route_a_flow() -> None:
    with TestClient(app) as client:
        search = client.get("/api/subjects/search", params={"query": "孤独摇滚", "limit": 5})
        assert search.status_code == 200
        candidate = search.json()["candidates"][0]
        assert candidate["subject_id"] == "328609"

        confirmation = client.post(f"/api/subjects/{candidate['subject_id']}/confirm")
        assert confirmation.status_code == 200
        assert confirmation.json()["subject_id"] == candidate["subject_id"]

        route = client.get(f"/api/subjects/{candidate['subject_id']}/route-a")
        assert route.status_code == 200
        points = route.json()["points"]
        assert len(points) == 3
        assert all(point["provenance"]["source_url"] for point in points)
