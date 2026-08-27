from uuid import uuid4

import pytest
from pydantic import ValidationError

from app.models.enums import IntercityTravelMode
from app.schemas.trip_public_transport_plan import (
    DailyPlacePlan,
    IntercityPublicTransportLeg,
    PublicTransportPlanningRequest,
    TripRouteLegKind,
    TripRouteNode,
    TripRouteNodeKind,
    TripRouteSkeleton,
    TripRouteSkeletonLeg,
)


def resolved_location(poi_id: str, name: str) -> dict[str, object]:
    return {
        "poi_id": poi_id,
        "name": name,
        "coordinate": {"latitude": 39.9, "longitude": 116.4},
    }


def intercity_leg(departure_poi_id: str, arrival_poi_id: str) -> dict[str, object]:
    return {
        "travel_mode": IntercityTravelMode.HIGH_SPEED_RAIL,
        "departure_poi_id": departure_poi_id,
        "arrival_poi_id": arrival_poi_id,
        "fact": {"service_identifier": "G123", "duration_seconds": 14400},
    }


def test_public_transport_planning_request_accepts_poi_ids_and_daily_places() -> None:
    request = PublicTransportPlanningRequest(
        trip_id=uuid4(),
        outbound_intercity=intercity_leg("NANJING_SOUTH", "QINGDAO_NORTH"),
        return_intercity=intercity_leg("QINGDAO_NORTH", "NANJING_SOUTH"),
        daily_places=[
            {"day_number": 1, "place_poi_ids": ["PLACE_A", "PLACE_B"]},
            {"day_number": 2, "place_poi_ids": ["PLACE_C"]},
        ],
    )

    assert request.outbound_intercity.travel_mode is IntercityTravelMode.HIGH_SPEED_RAIL
    assert request.daily_places[0].place_poi_ids == ["PLACE_A", "PLACE_B"]


def test_intercity_leg_rejects_client_supplied_resolved_locations() -> None:
    with pytest.raises(ValidationError, match="departure_poi_id"):
        IntercityPublicTransportLeg(
            travel_mode=IntercityTravelMode.HIGH_SPEED_RAIL,
            departure_node=resolved_location("FORGED", "伪造车站"),
            arrival_node=resolved_location("OTHER_FORGED", "伪造到达站"),
            fact={"service_identifier": "G123", "duration_seconds": 1},
        )


@pytest.mark.parametrize(
    "daily_places",
    [
        [{"day_number": 1, "place_poi_ids": ["PLACE_A", "PLACE_A"]}],
        [
            {"day_number": 1, "place_poi_ids": ["PLACE_A"]},
            {"day_number": 1, "place_poi_ids": ["PLACE_B"]},
        ],
    ],
)
def test_public_transport_planning_request_rejects_invalid_daily_place_definitions(
    daily_places: list[dict[str, object]],
) -> None:
    with pytest.raises(ValidationError):
        PublicTransportPlanningRequest(
            trip_id=uuid4(),
            outbound_intercity=intercity_leg("NANJING_SOUTH", "QINGDAO_NORTH"),
            return_intercity=intercity_leg("QINGDAO_NORTH", "NANJING_SOUTH"),
            daily_places=daily_places,
        )


def test_intercity_public_transport_leg_rejects_driving_or_identical_nodes() -> None:
    with pytest.raises(ValidationError, match="must not use driving"):
        IntercityPublicTransportLeg(
            travel_mode=IntercityTravelMode.DRIVING,
            departure_poi_id="A",
            arrival_poi_id="B",
            fact={"service_identifier": "G123", "duration_seconds": 14400},
        )

    with pytest.raises(ValidationError, match="must be distinct"):
        IntercityPublicTransportLeg(
            travel_mode=IntercityTravelMode.TRAIN,
            departure_poi_id="A",
            arrival_poi_id="A",
            fact={"service_identifier": "K1", "duration_seconds": 14400},
        )


@pytest.mark.parametrize(
    "travel_mode",
    [
        IntercityTravelMode.HIGH_SPEED_RAIL,
        IntercityTravelMode.TRAIN,
        IntercityTravelMode.FLIGHT,
    ],
)
def test_intercity_public_transport_leg_accepts_each_supported_mode(
    travel_mode: IntercityTravelMode,
) -> None:
    leg = IntercityPublicTransportLeg(
        travel_mode=travel_mode,
        departure_poi_id="A",
        arrival_poi_id="B",
        fact={"service_identifier": "SERVICE-1", "duration_seconds": 1},
    )

    assert leg.travel_mode is travel_mode
    assert leg.fact.source.value == "user_confirmed"


@pytest.mark.parametrize(
    "fact",
    [
        {"service_identifier": "   ", "duration_seconds": 1},
        {"service_identifier": "G123", "duration_seconds": 0},
        {
            "service_identifier": "G123",
            "duration_seconds": 1,
            "departure_time": "2026-10-01T09:00:00",
        },
        {
            "service_identifier": "G123",
            "duration_seconds": 1,
            "departure_time": "2026-10-01T10:00:00",
            "arrival_time": "2026-10-01T09:00:00",
        },
    ],
)
def test_intercity_public_transport_leg_rejects_incomplete_confirmed_facts(
    fact: dict[str, object],
) -> None:
    with pytest.raises(ValidationError):
        IntercityPublicTransportLeg(
            travel_mode=IntercityTravelMode.HIGH_SPEED_RAIL,
            departure_poi_id="A",
            arrival_poi_id="B",
            fact=fact,
        )


def test_intercity_public_transport_leg_requires_a_confirmed_fact() -> None:
    with pytest.raises(ValidationError, match="fact"):
        IntercityPublicTransportLeg(
            travel_mode=IntercityTravelMode.HIGH_SPEED_RAIL,
            departure_poi_id="A",
            arrival_poi_id="B",
        )


def test_trip_route_skeleton_keeps_node_and_leg_order_without_route_facts() -> None:
    skeleton = TripRouteSkeleton(
        trip_id=uuid4(),
        nodes=[
            TripRouteNode(
                kind=TripRouteNodeKind.ORIGIN,
                location=resolved_location("HOME", "家"),
            ),
            TripRouteNode(
                kind=TripRouteNodeKind.PLACE,
                location=resolved_location("PLACE_A", "景点 A"),
                day_number=1,
            ),
        ],
        legs=[
            TripRouteSkeletonLeg(
                kind=TripRouteLegKind.DAY_START,
                origin_node_index=0,
                destination_node_index=1,
            )
        ],
    )

    assert [node.kind for node in skeleton.nodes] == [
        TripRouteNodeKind.ORIGIN,
        TripRouteNodeKind.PLACE,
    ]
    assert skeleton.legs[0].kind is TripRouteLegKind.DAY_START


def test_trip_route_nodes_and_legs_reject_invalid_linkage() -> None:
    with pytest.raises(ValidationError, match="require day_number"):
        TripRouteNode(
            kind=TripRouteNodeKind.PLACE,
            location=resolved_location("PLACE_A", "景点 A"),
        )

    with pytest.raises(ValidationError, match="endpoints must be distinct"):
        TripRouteSkeletonLeg(
            kind=TripRouteLegKind.DAY_START,
            origin_node_index=1,
            destination_node_index=1,
        )

    with pytest.raises(ValidationError, match="existing node"):
        TripRouteSkeleton(
            trip_id=uuid4(),
            nodes=[
                TripRouteNode(
                    kind=TripRouteNodeKind.ORIGIN,
                    location=resolved_location("HOME", "家"),
                ),
                TripRouteNode(
                    kind=TripRouteNodeKind.ACCOMMODATION,
                    location=resolved_location("HOTEL", "酒店"),
                ),
            ],
            legs=[
                TripRouteSkeletonLeg(
                    kind=TripRouteLegKind.DAY_START,
                    origin_node_index=0,
                    destination_node_index=2,
                )
            ],
        )
