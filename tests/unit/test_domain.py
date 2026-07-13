from datetime import UTC, date, datetime
from uuid import uuid4

import pytest
from pydantic import ValidationError

from pilgrimage_agent.domain.models import (
    DataProvenance,
    DataStatus,
    PilgrimagePoint,
    RouteB,
    TripRequest,
)


def provenance() -> DataProvenance:
    return DataProvenance(
        provider="fixture",
        source_url="https://example.test/point/1",
        fetched_at=datetime.now(UTC),
        status=DataStatus.CACHED,
    )


def test_trip_request_rejects_reversed_dates() -> None:
    with pytest.raises(ValidationError, match="end_date must not precede"):
        TripRequest(start_date=date(2030, 2, 2), end_date=date(2030, 2, 1))


def test_point_rejects_invalid_coordinate() -> None:
    with pytest.raises(ValidationError):
        PilgrimagePoint(
            subject_id="subject-1",
            name="Invalid",
            latitude=91,
            longitude=139.7,
            confidence="verified",
            provenance=provenance(),
        )


def test_route_b_is_a_complete_explained_subset() -> None:
    selected, omitted = uuid4(), uuid4()
    route = RouteB(
        route_a_point_ids=frozenset({selected, omitted}),
        selected_point_ids=(selected,),
        omitted_reasons={omitted: "time_window"},
    )
    assert route.selected_point_ids == (selected,)


@pytest.mark.parametrize(
    ("selected", "reasons"),
    [
        ((uuid4(),), {}),
        ((), {}),
    ],
)
def test_route_b_rejects_non_members_or_missing_reasons(
    selected: tuple[object, ...], reasons: dict[object, str]
) -> None:
    route_a_id = uuid4()
    with pytest.raises(ValidationError):
        RouteB(
            route_a_point_ids=frozenset({route_a_id}),
            selected_point_ids=selected,
            omitted_reasons=reasons,
        )


def test_boundary_models_reject_unknown_fields() -> None:
    with pytest.raises(ValidationError):
        TripRequest.model_validate({"origin": "Kyoto", "invented": True})
