from typing import Callable
from uuid import uuid4

import pytest

from app.models.enums import RouteSegmentMode, TravelMode
from app.schemas.map import GeoPoint, Polyline, ResolvedLocation, Route, RouteSegment
from app.schemas.trip_public_transport_plan import (
    TripRouteLegKind,
    TripRouteNode,
    TripRouteNodeKind,
    TripRouteSkeleton,
    TripRouteSkeletonLeg,
)
from app.services.local_public_transport_route_service import (
    LocalPublicTransportRouteInputError,
    LocalPublicTransportRouteService,
)
from app.services.map_errors import (
    MapNoResultsError,
    MapQuotaExceededError,
    MapTimeoutError,
    MapUpstreamError,
)


def location(poi_id: str, city_code: str | None) -> ResolvedLocation:
    return ResolvedLocation(
        poi_id=poi_id,
        name=poi_id,
        city_code=city_code,
        coordinate=GeoPoint(latitude=39.9, longitude=116.4),
    )


def route() -> Route:
    return Route(
        travel_mode=TravelMode.PUBLIC_TRANSPORT,
        distance_meters=800,
        duration_seconds=300,
        segments=[
            RouteSegment(
                mode=RouteSegmentMode.WALKING,
                distance_meters=120,
                polyline=Polyline(
                    points=[
                        GeoPoint(latitude=39.9, longitude=116.4),
                        GeoPoint(latitude=39.91, longitude=116.41),
                    ]
                ),
            ),
            RouteSegment(mode=RouteSegmentMode.SUBWAY, distance_meters=680),
        ],
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
        return route()


def skeleton() -> TripRouteSkeleton:
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
    legs = [
        TripRouteSkeletonLeg(
                kind=kind,
                origin_node_id=nodes[index].node_id,
                destination_node_id=nodes[index + 1].node_id,
        )
        for index, kind in enumerate(kinds)
    ]
    return TripRouteSkeleton(trip_id=uuid4(), nodes=nodes, legs=legs)


def test_resolve_queries_only_local_legs_in_skeleton_order_and_keeps_route_facts() -> None:
    map_service = FakeMapService()

    facts = LocalPublicTransportRouteService(map_service).resolve(skeleton())

    assert map_service.calls == [
        ("HOME", "OUTBOUND_DEPARTURE"),
        ("OUTBOUND_ARRIVAL", "HOTEL"),
        ("HOTEL", "PLACE"),
        ("PLACE", "HOTEL_RETURN"),
        ("HOTEL_RETURN", "RETURN_DEPARTURE"),
        ("RETURN_ARRIVAL", "RETURN_HOME"),
    ]
    assert [fact.skeleton_leg.kind for fact in facts] == [
        TripRouteLegKind.TO_OUTBOUND_DEPARTURE_NODE,
        TripRouteLegKind.FROM_OUTBOUND_ARRIVAL_NODE,
        TripRouteLegKind.DAY_START,
        TripRouteLegKind.DAY_RETURN,
        TripRouteLegKind.TO_RETURN_DEPARTURE_NODE,
        TripRouteLegKind.FROM_RETURN_ARRIVAL_NODE,
    ]
    assert facts[0].route.segments[0].mode is RouteSegmentMode.WALKING
    assert facts[0].route.segments[0].polyline is not None


@pytest.mark.parametrize(
    "map_error_factory",
    [MapNoResultsError, MapTimeoutError, MapQuotaExceededError, MapUpstreamError],
)
def test_resolve_propagates_predictable_map_failures_without_creating_facts(
    map_error_factory: Callable[[], Exception],
) -> None:
    map_service = FakeMapService(failure=map_error_factory())

    with pytest.raises(type(map_service.failure)):
        LocalPublicTransportRouteService(map_service).resolve(skeleton())

    assert len(map_service.calls) == 1


@pytest.mark.parametrize(
    ("city_code", "error_message"),
    [(None, "city_code"), ("0532", "same city")],
)
def test_resolve_rejects_missing_or_cross_city_local_leg_inputs(
    city_code: str | None, error_message: str
) -> None:
    route_skeleton = skeleton()
    route_skeleton.nodes[1] = TripRouteNode(
        node_id=route_skeleton.nodes[1].node_id,
        kind=TripRouteNodeKind.OUTBOUND_DEPARTURE_NODE,
        location=location("OUTBOUND_DEPARTURE", city_code),
    )
    map_service = FakeMapService()

    with pytest.raises(LocalPublicTransportRouteInputError, match=error_message):
        LocalPublicTransportRouteService(map_service).resolve(route_skeleton)

    assert map_service.calls == []
