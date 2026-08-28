"""One Stage 3 entry point for planning a complete public-transport Trip."""

from typing import Protocol, runtime_checkable

from app.schemas.trip_public_transport_plan import (
    IntercityPublicTransportLeg,
    PublicTransportPlanningRequest,
    PublicTransportTripPlan,
    ResolvedIntercityPublicTransportLeg,
    ResolvedPublicTransportPlanningRequest,
)
from app.schemas.map import ResolvedLocation
from app.schemas.trip_state import TripState
from app.services.intercity_public_transport_fact_validation_service import (
    IntercityPublicTransportFactValidationService,
)
from app.services.local_public_transport_route_service import (
    LocalPublicTransportRouteProvider,
    LocalPublicTransportRouteService,
)
from app.services.public_transport_trip_plan_assembly_service import (
    PublicTransportTripPlanAssemblyService,
)
from app.services.trip_route_skeleton_service import TripRouteSkeletonService


@runtime_checkable
class PublicTransportTripPlanningMapProvider(LocalPublicTransportRouteProvider, Protocol):
    """Stage 1 map capabilities required to confirm nodes and route local legs."""

    def resolve_location(self, poi_id: str) -> ResolvedLocation:
        """Return a provider-confirmed location for one POI ID."""


class PublicTransportTripPlanningService:
    """Coordinate existing Stage 3 services without creating map or ticket facts."""

    def __init__(self, map_service: PublicTransportTripPlanningMapProvider) -> None:
        self._map_service = map_service
        self._skeleton_service = TripRouteSkeletonService()
        self._intercity_validator = IntercityPublicTransportFactValidationService()
        self._local_route_service = LocalPublicTransportRouteService(map_service)
        self._assembly_service = PublicTransportTripPlanAssemblyService(
            self._intercity_validator
        )

    def plan(
        self, state: TripState, request: PublicTransportPlanningRequest
    ) -> PublicTransportTripPlan:
        """Create one complete plan, propagating predictable input and map failures."""
        resolved_request = self._resolve_intercity_nodes(request)
        skeleton = self._skeleton_service.build(state, resolved_request)
        self._intercity_validator.validate(resolved_request)
        local_route_facts = self._local_route_service.resolve(skeleton)
        return self._assembly_service.assemble(
            skeleton,
            resolved_request,
            local_route_facts,
            source_state_revision=state.revision,
        )

    def _resolve_intercity_nodes(
        self, request: PublicTransportPlanningRequest
    ) -> ResolvedPublicTransportPlanningRequest:
        return ResolvedPublicTransportPlanningRequest(
            trip_id=request.trip_id,
            outbound_intercity=self._resolve_intercity_leg(request.outbound_intercity),
            return_intercity=self._resolve_intercity_leg(request.return_intercity),
            daily_places=request.daily_places,
        )

    def _resolve_intercity_leg(
        self, request_leg: IntercityPublicTransportLeg
    ) -> ResolvedIntercityPublicTransportLeg:
        return ResolvedIntercityPublicTransportLeg(
            travel_mode=request_leg.travel_mode,
            departure_node=self._map_service.resolve_location(request_leg.departure_poi_id),
            arrival_node=self._map_service.resolve_location(request_leg.arrival_poi_id),
            fact=request_leg.fact,
        )
