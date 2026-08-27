from uuid import uuid4

import pytest

from app.models.enums import IntercityTravelMode, RouteSegmentMode, TravelMode
from app.schemas.map import GeoPoint, ResolvedLocation, Route, RouteSegment
from app.schemas.trip_public_transport_plan import PublicTransportPlanningRequest, TripRouteFactSource
from app.schemas.trip_state import TripState
from app.services.map_errors import MapTimeoutError
from app.services.public_transport_trip_planning_service import PublicTransportTripPlanningService


def resolved_intent(poi_id: str, name: str) -> dict[str, object]:
    return {
        "query": name,
        "resolution_status": "resolved",
        "resolved_location": {
            "poi_id": poi_id,
            "name": name,
            "city_code": "0532" if poi_id != "HOME" and poi_id != "HOME_RETURN" else "010",
            "coordinate": {"latitude": 39.9, "longitude": 116.4},
        },
    }


def state(trip_id: object) -> TripState:
    return TripState(
        trip_id=trip_id,
        origin=resolved_intent("HOME", "家"),
        destination=resolved_intent("QINGDAO", "青岛"),
        return_destination=resolved_intent("HOME_RETURN", "返程终点"),
        accommodation=resolved_intent("HOTEL", "酒店"),
        places=[resolved_intent("PLACE", "景点")],
        intercity_travel_mode=IntercityTravelMode.HIGH_SPEED_RAIL,
        local_travel_mode=TravelMode.PUBLIC_TRANSPORT,
        departure_date="2026-10-01",
        return_date="2026-10-01",
    )


def request(trip_id: object) -> PublicTransportPlanningRequest:
    def intercity_leg(
        departure_poi_id: str,
        arrival_poi_id: str,
    ) -> dict[str, object]:
        return {
            "travel_mode": IntercityTravelMode.HIGH_SPEED_RAIL,
            "departure_poi_id": departure_poi_id,
            "arrival_poi_id": arrival_poi_id,
            "fact": {"service_identifier": "G123", "duration_seconds": 14400},
        }

    return PublicTransportPlanningRequest(
        trip_id=trip_id,
        outbound_intercity=intercity_leg(
            "NANJING_SOUTH", "QINGDAO_NORTH"
        ),
        return_intercity=intercity_leg("QINGDAO_NORTH", "NANJING_SOUTH"),
        daily_places=[{"day_number": 1, "place_poi_ids": ["PLACE"]}],
    )


class FakeMapService:
    def __init__(self, failure: Exception | None = None) -> None:
        self.failure = failure
        self.calls: list[tuple[str, str]] = []

    def get_local_public_transport_route(
        self, origin: ResolvedLocation, destination: ResolvedLocation
    ) -> Route:
        self.calls.append((origin.poi_id, destination.poi_id))
        if self.failure is not None:
            raise self.failure
        return Route(
            travel_mode=TravelMode.PUBLIC_TRANSPORT,
            distance_meters=100,
            segments=[RouteSegment(mode=RouteSegmentMode.WALKING, distance_meters=100)],
        )

    def resolve_location(self, poi_id: str) -> ResolvedLocation:
        city_code = "0532" if poi_id == "QINGDAO_NORTH" else "010"
        return ResolvedLocation(
            poi_id=poi_id,
            name=poi_id,
            city_code=city_code,
            coordinate=GeoPoint(latitude=39.9, longitude=116.4),
        )


def test_plan_coordinates_complete_stage_three_flow() -> None:
    trip_id = uuid4()
    map_service = FakeMapService()

    plan = PublicTransportTripPlanningService(map_service).plan(state(trip_id), request(trip_id))

    assert len(plan.legs) == 8
    assert [leg.fact_source for leg in plan.legs] == [
        TripRouteFactSource.AMAP_LOCAL_PUBLIC_TRANSPORT,
        TripRouteFactSource.USER_CONFIRMED_INTERCITY,
        TripRouteFactSource.AMAP_LOCAL_PUBLIC_TRANSPORT,
        TripRouteFactSource.AMAP_LOCAL_PUBLIC_TRANSPORT,
        TripRouteFactSource.AMAP_LOCAL_PUBLIC_TRANSPORT,
        TripRouteFactSource.AMAP_LOCAL_PUBLIC_TRANSPORT,
        TripRouteFactSource.USER_CONFIRMED_INTERCITY,
        TripRouteFactSource.AMAP_LOCAL_PUBLIC_TRANSPORT,
    ]
    assert len(map_service.calls) == 6


def test_plan_propagates_map_failure_without_returning_a_partial_plan() -> None:
    trip_id = uuid4()
    map_service = FakeMapService(failure=MapTimeoutError())

    with pytest.raises(MapTimeoutError):
        PublicTransportTripPlanningService(map_service).plan(state(trip_id), request(trip_id))

    assert len(map_service.calls) == 1


def test_plan_rejects_stage_one_node_with_missing_city_before_map_queries() -> None:
    trip_id = uuid4()
    map_service = FakeMapService()

    map_service.resolve_location = lambda poi_id: ResolvedLocation(
        poi_id=poi_id,
        name=poi_id,
        city_code=None if poi_id == "NANJING_SOUTH" else "0532",
        coordinate=GeoPoint(latitude=39.9, longitude=116.4),
    )
    with pytest.raises(ValueError, match="city_code"):
        PublicTransportTripPlanningService(map_service).plan(
            state(trip_id), request(trip_id)
        )

    assert map_service.calls == []
