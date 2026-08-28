"""Assemble a complete Stage 3 public-transport plan from verified facts."""

from uuid import UUID

from app.schemas.trip_public_transport_plan import (
    LocalPublicTransportRouteFact,
    ResolvedPublicTransportPlanningRequest,
    PublicTransportTripPlan,
    PublicTransportTripPlanLeg,
    TripRouteFactSource,
    TripRouteLegKind,
    TripRouteSkeleton,
    TripRouteSkeletonLeg,
)
from app.services.intercity_public_transport_fact_validation_service import (
    IntercityPublicTransportFactValidationService,
)


class PublicTransportTripPlanAssemblyError(ValueError):
    """Raised when verified facts cannot be safely bound to one route skeleton."""


class PublicTransportTripPlanAssemblyService:
    """Combine local Amap routes and confirmed intercity facts without fabricating either."""

    _INTERCITY_LEG_KINDS = {
        TripRouteLegKind.OUTBOUND_INTERCITY,
        TripRouteLegKind.RETURN_INTERCITY,
    }

    def __init__(
        self,
        intercity_validator: IntercityPublicTransportFactValidationService | None = None,
    ) -> None:
        self._intercity_validator = (
            intercity_validator or IntercityPublicTransportFactValidationService()
        )

    def assemble(
        self,
        skeleton: TripRouteSkeleton,
        request: ResolvedPublicTransportPlanningRequest,
        local_route_facts: list[LocalPublicTransportRouteFact],
        *,
        source_state_revision: int,
    ) -> PublicTransportTripPlan:
        """Return a complete ordered plan only when every skeleton leg has its proper fact."""
        self._validate_request_matches_skeleton(skeleton, request)
        self._intercity_validator.validate(request)
        local_facts_by_leg = self._index_local_facts(skeleton, local_route_facts)

        plan_legs: list[PublicTransportTripPlanLeg] = []
        nodes_by_id = {node.node_id: node for node in skeleton.nodes}
        for skeleton_leg in skeleton.legs:
            origin = nodes_by_id[skeleton_leg.origin_node_id].location
            destination = nodes_by_id[skeleton_leg.destination_node_id].location
            origin_node_id = skeleton_leg.origin_node_id
            destination_node_id = skeleton_leg.destination_node_id
            if skeleton_leg.kind is TripRouteLegKind.OUTBOUND_INTERCITY:
                plan_legs.append(
                    PublicTransportTripPlanLeg(
                        kind=skeleton_leg.kind,
                        leg_id=skeleton_leg.leg_id,
                        origin_node_id=origin_node_id,
                        destination_node_id=destination_node_id,
                        origin=origin,
                        destination=destination,
                        fact_source=TripRouteFactSource.USER_CONFIRMED_INTERCITY,
                        intercity_fact=request.outbound_intercity.fact,
                    )
                )
            elif skeleton_leg.kind is TripRouteLegKind.RETURN_INTERCITY:
                plan_legs.append(
                    PublicTransportTripPlanLeg(
                        kind=skeleton_leg.kind,
                        leg_id=skeleton_leg.leg_id,
                        origin_node_id=origin_node_id,
                        destination_node_id=destination_node_id,
                        origin=origin,
                        destination=destination,
                        fact_source=TripRouteFactSource.USER_CONFIRMED_INTERCITY,
                        intercity_fact=request.return_intercity.fact,
                    )
                )
            else:
                local_fact = local_facts_by_leg[self._leg_key(skeleton_leg)]
                plan_legs.append(
                    PublicTransportTripPlanLeg(
                        kind=skeleton_leg.kind,
                        leg_id=skeleton_leg.leg_id,
                        origin_node_id=origin_node_id,
                        destination_node_id=destination_node_id,
                        origin=origin,
                        destination=destination,
                        fact_source=TripRouteFactSource.AMAP_LOCAL_PUBLIC_TRANSPORT,
                        local_route=local_fact.route,
                    )
                )
        return PublicTransportTripPlan(
            trip_id=skeleton.trip_id,
            source_state_revision=source_state_revision,
            nodes=skeleton.nodes,
            legs=plan_legs,
        )

    def _validate_request_matches_skeleton(
        self, skeleton: TripRouteSkeleton, request: ResolvedPublicTransportPlanningRequest
    ) -> None:
        if skeleton.trip_id != request.trip_id:
            raise PublicTransportTripPlanAssemblyError(
                "planning request trip_id must match route skeleton"
            )
        self._validate_intercity_endpoints(
            skeleton,
            TripRouteLegKind.OUTBOUND_INTERCITY,
            request.outbound_intercity.departure_node.poi_id,
            request.outbound_intercity.arrival_node.poi_id,
        )
        self._validate_intercity_endpoints(
            skeleton,
            TripRouteLegKind.RETURN_INTERCITY,
            request.return_intercity.departure_node.poi_id,
            request.return_intercity.arrival_node.poi_id,
        )

    @staticmethod
    def _validate_intercity_endpoints(
        skeleton: TripRouteSkeleton,
        leg_kind: TripRouteLegKind,
        expected_origin_poi_id: str,
        expected_destination_poi_id: str,
    ) -> None:
        matching_legs = [leg for leg in skeleton.legs if leg.kind is leg_kind]
        if len(matching_legs) != 1:
            raise PublicTransportTripPlanAssemblyError(
                f"route skeleton must contain exactly one {leg_kind.value} leg"
            )
        matching_leg = matching_legs[0]
        nodes_by_id = {node.node_id: node for node in skeleton.nodes}
        origin = nodes_by_id[matching_leg.origin_node_id].location
        destination = nodes_by_id[matching_leg.destination_node_id].location
        if (
            origin.poi_id != expected_origin_poi_id
            or destination.poi_id != expected_destination_poi_id
        ):
            raise PublicTransportTripPlanAssemblyError(
                f"{leg_kind.value} endpoints must match the planning request"
            )

    def _index_local_facts(
        self,
        skeleton: TripRouteSkeleton,
        local_route_facts: list[LocalPublicTransportRouteFact],
    ) -> dict[UUID, LocalPublicTransportRouteFact]:
        expected_keys = {
            self._leg_key(leg)
            for leg in skeleton.legs
            if leg.kind not in self._INTERCITY_LEG_KINDS
        }
        facts_by_leg: dict[UUID, LocalPublicTransportRouteFact] = {}
        for route_fact in local_route_facts:
            if route_fact.trip_id != skeleton.trip_id:
                raise PublicTransportTripPlanAssemblyError(
                    "local route fact trip_id must match route skeleton"
                )
            key = self._leg_key(route_fact.skeleton_leg)
            if key not in expected_keys:
                raise PublicTransportTripPlanAssemblyError(
                    "local route fact must reference a non-intercity skeleton leg"
                )
            if key in facts_by_leg:
                raise PublicTransportTripPlanAssemblyError(
                    "local route facts must not contain duplicate skeleton legs"
                )
            facts_by_leg[key] = route_fact
        if set(facts_by_leg) != expected_keys:
            raise PublicTransportTripPlanAssemblyError(
                "local route facts must cover every non-intercity skeleton leg exactly once"
            )
        return facts_by_leg

    @staticmethod
    def _leg_key(leg: TripRouteSkeletonLeg) -> UUID:
        return leg.leg_id
