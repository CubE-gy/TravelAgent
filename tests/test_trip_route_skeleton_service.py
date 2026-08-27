from uuid import uuid4

import pytest

from app.models.enums import IntercityTravelMode, TravelMode
from app.schemas.trip_public_transport_plan import (
    ResolvedPublicTransportPlanningRequest,
    TripRouteLegKind,
    TripRouteNodeKind,
)
from app.schemas.trip_state import LocationIntent, TripState
from app.services.trip_route_skeleton_service import TripRouteSkeletonService


def resolved_intent(poi_id: str, name: str, city_code: str) -> dict[str, object]:
    return {
        "query": name,
        "resolution_status": "resolved",
        "resolved_location": {
            "poi_id": poi_id,
            "name": name,
            "city_code": city_code,
            "coordinate": {"latitude": 39.9, "longitude": 116.4},
        },
    }


def intercity_leg(departure_poi_id: str, arrival_poi_id: str) -> dict[str, object]:
    return {
        "travel_mode": IntercityTravelMode.HIGH_SPEED_RAIL,
        "departure_node": {
            "poi_id": departure_poi_id,
            "name": "车站",
            "city_code": "010" if departure_poi_id == "NANJING_SOUTH" else "0532",
            "coordinate": {"latitude": 39.9, "longitude": 116.4},
        },
        "arrival_node": {
            "poi_id": arrival_poi_id,
            "name": "车站",
            "city_code": "0532" if arrival_poi_id == "QINGDAO_NORTH" else "010",
            "coordinate": {"latitude": 36.0, "longitude": 120.3},
        },
        "fact": {"service_identifier": "G123", "duration_seconds": 14400},
    }


def complete_state(*, trip_id: object, local_travel_mode: TravelMode = TravelMode.PUBLIC_TRANSPORT) -> TripState:
    return TripState(
        trip_id=trip_id,
        origin=resolved_intent("HOME", "家", "010"),
        destination=resolved_intent("QINGDAO", "青岛", "0532"),
        return_destination=resolved_intent("HOME_RETURN", "返程终点", "010"),
        departure_date="2026-10-01",
        return_date="2026-10-02",
        accommodation=resolved_intent("HOTEL", "酒店", "0532"),
        places=[
            resolved_intent("PLACE_A", "景点 A", "0532"),
            resolved_intent("PLACE_B", "景点 B", "0532"),
            resolved_intent("PLACE_C", "景点 C", "0532"),
        ],
        intercity_travel_mode=IntercityTravelMode.HIGH_SPEED_RAIL,
        local_travel_mode=local_travel_mode,
    )


def complete_request(trip_id: object) -> ResolvedPublicTransportPlanningRequest:
    return ResolvedPublicTransportPlanningRequest(
        trip_id=trip_id,
        outbound_intercity=intercity_leg("NANJING_SOUTH", "QINGDAO_NORTH"),
        return_intercity=intercity_leg("QINGDAO_NORTH", "NANJING_SOUTH"),
        daily_places=[
            {"day_number": 2, "place_poi_ids": ["PLACE_C"]},
            {"day_number": 1, "place_poi_ids": ["PLACE_A", "PLACE_B"]},
        ],
    )


def test_build_creates_a_complete_ordered_door_to_door_skeleton() -> None:
    trip_id = uuid4()

    skeleton = TripRouteSkeletonService().build(
        complete_state(trip_id=trip_id), complete_request(trip_id)
    )

    assert [node.kind for node in skeleton.nodes] == [
        TripRouteNodeKind.ORIGIN,
        TripRouteNodeKind.OUTBOUND_DEPARTURE_NODE,
        TripRouteNodeKind.OUTBOUND_ARRIVAL_NODE,
        TripRouteNodeKind.ACCOMMODATION,
        TripRouteNodeKind.PLACE,
        TripRouteNodeKind.PLACE,
        TripRouteNodeKind.ACCOMMODATION,
        TripRouteNodeKind.PLACE,
        TripRouteNodeKind.ACCOMMODATION,
        TripRouteNodeKind.RETURN_DEPARTURE_NODE,
        TripRouteNodeKind.RETURN_ARRIVAL_NODE,
        TripRouteNodeKind.RETURN_DESTINATION,
    ]
    assert [node.location.poi_id for node in skeleton.nodes] == [
        "HOME",
        "NANJING_SOUTH",
        "QINGDAO_NORTH",
        "HOTEL",
        "PLACE_A",
        "PLACE_B",
        "HOTEL",
        "PLACE_C",
        "HOTEL",
        "QINGDAO_NORTH",
        "NANJING_SOUTH",
        "HOME_RETURN",
    ]
    assert [leg.kind for leg in skeleton.legs] == [
        TripRouteLegKind.TO_OUTBOUND_DEPARTURE_NODE,
        TripRouteLegKind.OUTBOUND_INTERCITY,
        TripRouteLegKind.FROM_OUTBOUND_ARRIVAL_NODE,
        TripRouteLegKind.DAY_START,
        TripRouteLegKind.DAY_BETWEEN_PLACES,
        TripRouteLegKind.DAY_RETURN,
        TripRouteLegKind.DAY_START,
        TripRouteLegKind.DAY_RETURN,
        TripRouteLegKind.TO_RETURN_DEPARTURE_NODE,
        TripRouteLegKind.RETURN_INTERCITY,
        TripRouteLegKind.FROM_RETURN_ARRIVAL_NODE,
    ]
    assert [node.day_number for node in skeleton.nodes if node.kind is TripRouteNodeKind.PLACE] == [
        1,
        1,
        2,
    ]


@pytest.mark.parametrize(
    ("state_kwargs", "request_mutator", "error_message"),
    [
        ({"local_travel_mode": TravelMode.DRIVING}, None, "local_travel_mode"),
        ({}, lambda request: setattr(request, "trip_id", uuid4()), "trip_id"),
        (
            {},
            lambda request: request.daily_places.__setitem__(
                1,
                request.daily_places[1].model_copy(update={"place_poi_ids": ["PLACE_A"]}),
            ),
            "exactly once",
        ),
    ],
)
def test_build_rejects_incompatible_trip_state_or_daily_place_references(
    state_kwargs: dict[str, object],
    request_mutator: object,
    error_message: str,
) -> None:
    trip_id = uuid4()
    state = complete_state(trip_id=trip_id, **state_kwargs)
    request = complete_request(trip_id)
    if request_mutator is not None:
        request_mutator(request)

    with pytest.raises(ValueError, match=error_message):
        TripRouteSkeletonService().build(state, request)


def test_build_rejects_unresolved_required_trip_state_location() -> None:
    trip_id = uuid4()
    state = complete_state(trip_id=trip_id)
    state.accommodation = None

    with pytest.raises(ValueError, match="accommodation must be resolved"):
        TripRouteSkeletonService().build(state, complete_request(trip_id))


def test_build_rejects_intercity_mode_mismatch_and_unresolved_places() -> None:
    trip_id = uuid4()
    state = complete_state(trip_id=trip_id)
    request = complete_request(trip_id)
    request.outbound_intercity = request.outbound_intercity.model_copy(
        update={"travel_mode": IntercityTravelMode.TRAIN}
    )

    with pytest.raises(ValueError, match="must match"):
        TripRouteSkeletonService().build(state, request)

    state.places[1] = LocationIntent(query="尚未确认的景点")
    with pytest.raises(ValueError, match="places must be resolved"):
        TripRouteSkeletonService().build(state, complete_request(trip_id))


def test_build_rejects_destination_city_mismatch() -> None:
    trip_id = uuid4()
    state = complete_state(trip_id=trip_id)
    state.destination = LocationIntent.model_validate(
        resolved_intent("SHENZHEN", "深圳", "0755")
    )

    with pytest.raises(ValueError, match="destination, accommodation, and daily places"):
        TripRouteSkeletonService().build(state, complete_request(trip_id))


@pytest.mark.parametrize("date_field", ["departure_date", "return_date"])
def test_build_requires_trip_dates(date_field: str) -> None:
    trip_id = uuid4()
    state = complete_state(trip_id=trip_id)
    setattr(state, date_field, None)

    with pytest.raises(ValueError, match="departure_date and return_date"):
        TripRouteSkeletonService().build(state, complete_request(trip_id))


def test_build_rejects_day_outside_trip_date_range() -> None:
    trip_id = uuid4()
    request = complete_request(trip_id)
    request.daily_places[1] = request.daily_places[1].model_copy(
        update={"day_number": 99}
    )

    with pytest.raises(ValueError, match="date range"):
        TripRouteSkeletonService().build(complete_state(trip_id=trip_id), request)
