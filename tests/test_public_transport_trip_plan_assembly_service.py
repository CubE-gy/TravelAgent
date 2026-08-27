from uuid import uuid4

import pytest

from app.models.enums import IntercityTravelMode, RouteSegmentMode, TravelMode
from app.schemas.map import GeoPoint, ResolvedLocation, Route, RouteSegment
from app.schemas.trip_public_transport_plan import (
    LocalPublicTransportRouteFact,
    ResolvedPublicTransportPlanningRequest,
    TripRouteFactSource,
    TripRouteLegKind,
    TripRouteNode,
    TripRouteNodeKind,
    TripRouteSkeleton,
    TripRouteSkeletonLeg,
)
from app.services.public_transport_trip_plan_assembly_service import (
    PublicTransportTripPlanAssemblyError,
    PublicTransportTripPlanAssemblyService,
)


def location(poi_id: str, city_code: str) -> ResolvedLocation:
    return ResolvedLocation(
        poi_id=poi_id,
        name=poi_id,
        city_code=city_code,
        coordinate=GeoPoint(latitude=39.9, longitude=116.4),
    )


def skeleton(trip_id: object) -> TripRouteSkeleton:
    nodes = [
        TripRouteNode(kind=TripRouteNodeKind.ORIGIN, location=location("HOME", "010")),
        TripRouteNode(
            kind=TripRouteNodeKind.OUTBOUND_DEPARTURE_NODE,
            location=location("OUTBOUND_DEPARTURE", "010"),
        ),
        TripRouteNode(
            kind=TripRouteNodeKind.OUTBOUND_ARRIVAL_NODE,
            location=location("OUTBOUND_ARRIVAL", "0532"),
        ),
        TripRouteNode(kind=TripRouteNodeKind.ACCOMMODATION, location=location("HOTEL", "0532")),
        TripRouteNode(
            kind=TripRouteNodeKind.PLACE,
            location=location("PLACE", "0532"),
            day_number=1,
        ),
        TripRouteNode(
            kind=TripRouteNodeKind.ACCOMMODATION,
            location=location("HOTEL_RETURN", "0532"),
        ),
        TripRouteNode(
            kind=TripRouteNodeKind.RETURN_DEPARTURE_NODE,
            location=location("RETURN_DEPARTURE", "0532"),
        ),
        TripRouteNode(
            kind=TripRouteNodeKind.RETURN_ARRIVAL_NODE,
            location=location("RETURN_ARRIVAL", "010"),
        ),
        TripRouteNode(
            kind=TripRouteNodeKind.RETURN_DESTINATION,
            location=location("RETURN_HOME", "010"),
        ),
    ]
    kinds = [
        TripRouteLegKind.TO_OUTBOUND_DEPARTURE_NODE,
        TripRouteLegKind.OUTBOUND_INTERCITY,
        TripRouteLegKind.FROM_OUTBOUND_ARRIVAL_NODE,
        TripRouteLegKind.DAY_START,
        TripRouteLegKind.DAY_RETURN,
        TripRouteLegKind.TO_RETURN_DEPARTURE_NODE,
        TripRouteLegKind.RETURN_INTERCITY,
        TripRouteLegKind.FROM_RETURN_ARRIVAL_NODE,
    ]
    return TripRouteSkeleton(
        trip_id=trip_id,
        nodes=nodes,
        legs=[
            TripRouteSkeletonLeg(
                kind=kind, origin_node_index=index, destination_node_index=index + 1
            )
            for index, kind in enumerate(kinds)
        ],
    )


def request(trip_id: object) -> ResolvedPublicTransportPlanningRequest:
    def intercity_leg(
        departure_poi_id: str, departure_city_code: str, arrival_poi_id: str, arrival_city_code: str
    ) -> dict[str, object]:
        return {
            "travel_mode": IntercityTravelMode.HIGH_SPEED_RAIL,
            "departure_node": location(departure_poi_id, departure_city_code),
            "arrival_node": location(arrival_poi_id, arrival_city_code),
            "fact": {"service_identifier": "G123", "duration_seconds": 14400},
        }

    return ResolvedPublicTransportPlanningRequest(
        trip_id=trip_id,
        outbound_intercity=intercity_leg(
            "OUTBOUND_DEPARTURE", "010", "OUTBOUND_ARRIVAL", "0532"
        ),
        return_intercity=intercity_leg("RETURN_DEPARTURE", "0532", "RETURN_ARRIVAL", "010"),
        daily_places=[{"day_number": 1, "place_poi_ids": ["PLACE"]}],
    )


def route() -> Route:
    return Route(
        travel_mode=TravelMode.PUBLIC_TRANSPORT,
        distance_meters=100,
        segments=[RouteSegment(mode=RouteSegmentMode.WALKING, distance_meters=100)],
    )


def local_facts(route_skeleton: TripRouteSkeleton) -> list[LocalPublicTransportRouteFact]:
    return [
        LocalPublicTransportRouteFact(
            trip_id=route_skeleton.trip_id,
            skeleton_leg=leg,
            route=route(),
        )
        for leg in route_skeleton.legs
        if leg.kind
        not in {TripRouteLegKind.OUTBOUND_INTERCITY, TripRouteLegKind.RETURN_INTERCITY}
    ]


def test_assemble_keeps_complete_skeleton_order_and_fact_sources() -> None:
    trip_id = uuid4()
    route_skeleton = skeleton(trip_id)

    plan = PublicTransportTripPlanAssemblyService().assemble(
        route_skeleton, request(trip_id), local_facts(route_skeleton)
    )

    assert [leg.kind for leg in plan.legs] == [leg.kind for leg in route_skeleton.legs]
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
    assert plan.legs[1].intercity_fact is not None
    assert plan.legs[1].local_route is None
    assert plan.legs[0].local_route is not None
    assert plan.legs[0].intercity_fact is None


def test_assemble_rejects_missing_duplicate_or_foreign_local_route_facts() -> None:
    trip_id = uuid4()
    route_skeleton = skeleton(trip_id)
    facts = local_facts(route_skeleton)
    service = PublicTransportTripPlanAssemblyService()

    with pytest.raises(PublicTransportTripPlanAssemblyError, match="cover every"):
        service.assemble(route_skeleton, request(trip_id), facts[:-1])

    with pytest.raises(PublicTransportTripPlanAssemblyError, match="duplicate"):
        service.assemble(route_skeleton, request(trip_id), [*facts, facts[0]])

    foreign_fact = facts[0].model_copy(update={"trip_id": uuid4()})
    with pytest.raises(PublicTransportTripPlanAssemblyError, match="trip_id"):
        service.assemble(route_skeleton, request(trip_id), [foreign_fact, *facts[1:]])


def test_assemble_rejects_request_with_wrong_intercity_endpoints() -> None:
    trip_id = uuid4()
    route_skeleton = skeleton(trip_id)
    plan_request = request(trip_id)
    plan_request.outbound_intercity = plan_request.outbound_intercity.model_copy(
        update={"departure_node": location("OTHER_STATION", "010")}
    )

    with pytest.raises(PublicTransportTripPlanAssemblyError, match="endpoints"):
        PublicTransportTripPlanAssemblyService().assemble(
            route_skeleton, plan_request, local_facts(route_skeleton)
        )
