from uuid import uuid4

import pytest
from pydantic import ValidationError

from app.models.enums import RouteSegmentMode, TravelMode
from app.schemas.map import GeoPoint, ResolvedLocation, Route, RouteSegment
from app.schemas.trip_public_transport_plan import (
    PublicTransportTripPlan,
    PublicTransportTripPlanLeg,
    TripRouteFactSource,
    TripRouteLegKind,
    TripRouteNode,
    TripRouteNodeKind,
)


def _location(poi_id: str) -> ResolvedLocation:
    return ResolvedLocation(
        poi_id=poi_id,
        name=poi_id,
        coordinate=GeoPoint(latitude=39.9, longitude=116.4),
    )


def _local_route() -> Route:
    return Route(
        travel_mode=TravelMode.PUBLIC_TRANSPORT,
        distance_meters=100,
        segments=[RouteSegment(mode=RouteSegmentMode.WALKING, distance_meters=100)],
    )


def _leg(
    kind: TripRouteLegKind,
    origin: TripRouteNode,
    destination: TripRouteNode,
) -> PublicTransportTripPlanLeg:
    return PublicTransportTripPlanLeg(
        kind=kind,
        origin_node_id=origin.node_id,
        destination_node_id=destination.node_id,
        origin=origin.location,
        destination=destination.location,
        fact_source=TripRouteFactSource.AMAP_LOCAL_PUBLIC_TRANSPORT,
        local_route=_local_route(),
    )


def _valid_plan() -> PublicTransportTripPlan:
    origin = TripRouteNode(kind=TripRouteNodeKind.ORIGIN, location=_location("HOME"))
    place = TripRouteNode(
        kind=TripRouteNodeKind.PLACE,
        location=_location("PLACE"),
        day_number=1,
    )
    destination = TripRouteNode(
        kind=TripRouteNodeKind.RETURN_DESTINATION,
        location=_location("RETURN_HOME"),
    )
    return PublicTransportTripPlan(
        trip_id=uuid4(),
        source_state_revision=1,
        nodes=[origin, place, destination],
        legs=[
            _leg(TripRouteLegKind.DAY_START, origin, place),
            _leg(TripRouteLegKind.DAY_RETURN, place, destination),
        ],
    )


def _rebuild(
    plan: PublicTransportTripPlan,
    *,
    nodes: list[TripRouteNode] | None = None,
    legs: list[PublicTransportTripPlanLeg] | None = None,
) -> PublicTransportTripPlan:
    return PublicTransportTripPlan(
        trip_id=plan.trip_id,
        source_state_revision=plan.source_state_revision,
        nodes=nodes if nodes is not None else plan.nodes,
        legs=legs if legs is not None else plan.legs,
    )


def test_complete_plan_accepts_one_ordered_path_with_matching_node_payloads() -> None:
    plan = _valid_plan()

    assert plan.legs[0].origin_node_id == plan.nodes[0].node_id
    assert plan.legs[-1].destination_node_id == plan.nodes[-1].node_id


def test_complete_plan_requires_exactly_one_origin_and_return_destination() -> None:
    plan = _valid_plan()
    nodes_without_return = [
        *plan.nodes[:-1],
        plan.nodes[-1].model_copy(update={"kind": TripRouteNodeKind.ACCOMMODATION}),
    ]

    with pytest.raises(ValidationError, match="exactly one origin and return destination"):
        _rebuild(plan, nodes=nodes_without_return)


def test_complete_plan_rejects_duplicate_node_and_leg_ids() -> None:
    plan = _valid_plan()
    duplicate_node = plan.nodes[1].model_copy(update={"node_id": plan.nodes[0].node_id})
    with pytest.raises(ValidationError, match="node_id values must be unique"):
        _rebuild(plan, nodes=[plan.nodes[0], duplicate_node, plan.nodes[2]])

    duplicate_leg = plan.legs[1].model_copy(update={"leg_id": plan.legs[0].leg_id})
    with pytest.raises(ValidationError, match="leg_id values must be unique"):
        _rebuild(plan, legs=[plan.legs[0], duplicate_leg])


def test_complete_plan_rejects_a_leg_with_a_foreign_node_reference() -> None:
    plan = _valid_plan()
    foreign_leg = plan.legs[0].model_copy(update={"origin_node_id": uuid4()})

    with pytest.raises(ValidationError, match="reference an existing node"):
        _rebuild(plan, legs=[foreign_leg, plan.legs[1]])


def test_complete_plan_rejects_legs_that_are_not_stored_in_route_order() -> None:
    plan = _valid_plan()

    with pytest.raises(ValidationError, match="ordered|continuous order"):
        _rebuild(plan, legs=list(reversed(plan.legs)))


def test_complete_plan_rejects_payload_that_disagrees_with_its_node_reference() -> None:
    plan = _valid_plan()
    mismatched_leg = plan.legs[0].model_copy(
        update={"origin": plan.nodes[1].location}
    )

    with pytest.raises(ValidationError, match="origin must match"):
        _rebuild(plan, legs=[mismatched_leg, plan.legs[1]])
