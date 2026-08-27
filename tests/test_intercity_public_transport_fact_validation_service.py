from uuid import uuid4

import pytest

from app.models.enums import IntercityTravelMode
from app.schemas.map import GeoPoint, ResolvedLocation
from app.schemas.trip_public_transport_plan import ResolvedPublicTransportPlanningRequest
from app.services.intercity_public_transport_fact_validation_service import (
    IntercityPublicTransportFactInputError,
    IntercityPublicTransportFactValidationService,
)


def leg(
    departure_city_code: str | None, arrival_city_code: str | None
) -> dict[str, object]:
    return {
        "travel_mode": IntercityTravelMode.FLIGHT,
        "departure_node": ResolvedLocation(poi_id="DEPARTURE", name="出发机场", city_code=departure_city_code, coordinate=GeoPoint(latitude=39.9, longitude=116.4)),
        "arrival_node": ResolvedLocation(poi_id="ARRIVAL", name="到达机场", city_code=arrival_city_code, coordinate=GeoPoint(latitude=36.0, longitude=120.3)),
        "fact": {
            "service_identifier": "CA1234",
            "duration_seconds": 7200,
            "departure_time": "2026-10-01T09:00:00",
            "arrival_time": "2026-10-01T11:00:00",
        },
    }


def request(
    outbound_departure_city_code: str | None = "010",
    outbound_arrival_city_code: str | None = "0532",
) -> ResolvedPublicTransportPlanningRequest:
    return ResolvedPublicTransportPlanningRequest(
        trip_id=uuid4(),
        outbound_intercity=leg(outbound_departure_city_code, outbound_arrival_city_code),
        return_intercity=leg("0532", "010"),
        daily_places=[{"day_number": 1, "place_poi_ids": ["PLACE"]}],
    )


def test_validate_accepts_user_confirmed_cross_city_facts() -> None:
    IntercityPublicTransportFactValidationService().validate(request())


@pytest.mark.parametrize(
    ("departure_city_code", "arrival_city_code", "error_message"),
    [
        (None, "0532", "city_code"),
        ("010", None, "city_code"),
        ("010", "010", "different cities"),
    ],
)
def test_validate_rejects_incomplete_or_non_intercity_node_pairs(
    departure_city_code: str | None,
    arrival_city_code: str | None,
    error_message: str,
) -> None:
    with pytest.raises(IntercityPublicTransportFactInputError, match=error_message):
        IntercityPublicTransportFactValidationService().validate(
            request(departure_city_code, arrival_city_code)
        )
