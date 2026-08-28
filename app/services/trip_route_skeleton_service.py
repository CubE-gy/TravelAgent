"""Build the Stage 3 public-transport route skeleton from one TripState."""

from app.models.enums import IntercityTravelMode, TravelMode
from app.schemas.map import ResolvedLocation
from app.schemas.trip_public_transport_plan import (
    ResolvedPublicTransportPlanningRequest,
    TripRouteLegKind,
    TripRouteNode,
    TripRouteNodeKind,
    TripRouteSkeleton,
    TripRouteSkeletonLeg,
)
from app.schemas.trip_state import LocationIntent, LocationResolutionStatus, TripState


class TripRouteSkeletonService:
    """Create ordered route nodes without querying or inventing map route facts."""

    def build(
        self, state: TripState, request: ResolvedPublicTransportPlanningRequest
    ) -> TripRouteSkeleton:
        """Return the complete public-transport node and leg sequence for one Trip."""
        self._validate_trip_state_and_request(state, request)

        origin = self._require_resolved_location(state.origin, field_name="origin")
        destination = self._require_resolved_location(state.destination, field_name="destination")
        accommodation = self._require_resolved_location(
            state.accommodation, field_name="accommodation"
        )
        return_destination = self._require_resolved_location(
            state.return_destination, field_name="return_destination"
        )
        places_by_poi_id = self._resolved_places_by_poi_id(state)
        self._validate_daily_places(state, request, places_by_poi_id)
        self._validate_city_consistency(
            origin=origin,
            destination=destination,
            return_destination=return_destination,
            accommodation=accommodation,
            places=places_by_poi_id.values(),
            request=request,
        )

        nodes: list[TripRouteNode] = []
        legs: list[TripRouteSkeletonLeg] = []

        origin_index = self._append_node(nodes, TripRouteNodeKind.ORIGIN, origin)
        outbound_departure_index = self._append_node(
            nodes,
            TripRouteNodeKind.OUTBOUND_DEPARTURE_NODE,
            request.outbound_intercity.departure_node,
        )
        self._append_leg(
            legs,
            TripRouteLegKind.TO_OUTBOUND_DEPARTURE_NODE,
            origin_index,
            outbound_departure_index,
        )
        outbound_arrival_index = self._append_node(
            nodes,
            TripRouteNodeKind.OUTBOUND_ARRIVAL_NODE,
            request.outbound_intercity.arrival_node,
        )
        self._append_leg(
            legs,
            TripRouteLegKind.OUTBOUND_INTERCITY,
            outbound_departure_index,
            outbound_arrival_index,
        )
        current_location_index = self._append_node(
            nodes, TripRouteNodeKind.ACCOMMODATION, accommodation
        )
        self._append_leg(
            legs,
            TripRouteLegKind.FROM_OUTBOUND_ARRIVAL_NODE,
            outbound_arrival_index,
            current_location_index,
        )

        for daily_plan in sorted(request.daily_places, key=lambda item: item.day_number):
            for place_position, poi_id in enumerate(daily_plan.place_poi_ids):
                next_location_index = self._append_node(
                    nodes,
                    TripRouteNodeKind.PLACE,
                    places_by_poi_id[poi_id],
                    day_number=daily_plan.day_number,
                )
                self._append_leg(
                    legs,
                    (
                        TripRouteLegKind.DAY_START
                        if place_position == 0
                        else TripRouteLegKind.DAY_BETWEEN_PLACES
                    ),
                    current_location_index,
                    next_location_index,
                )
                current_location_index = next_location_index

            next_location_index = self._append_node(
                nodes, TripRouteNodeKind.ACCOMMODATION, accommodation
            )
            self._append_leg(
                legs,
                TripRouteLegKind.DAY_RETURN,
                current_location_index,
                next_location_index,
            )
            current_location_index = next_location_index

        return_departure_index = self._append_node(
            nodes,
            TripRouteNodeKind.RETURN_DEPARTURE_NODE,
            request.return_intercity.departure_node,
        )
        self._append_leg(
            legs,
            TripRouteLegKind.TO_RETURN_DEPARTURE_NODE,
            current_location_index,
            return_departure_index,
        )
        return_arrival_index = self._append_node(
            nodes,
            TripRouteNodeKind.RETURN_ARRIVAL_NODE,
            request.return_intercity.arrival_node,
        )
        self._append_leg(
            legs,
            TripRouteLegKind.RETURN_INTERCITY,
            return_departure_index,
            return_arrival_index,
        )
        return_destination_index = self._append_node(
            nodes, TripRouteNodeKind.RETURN_DESTINATION, return_destination
        )
        self._append_leg(
            legs,
            TripRouteLegKind.FROM_RETURN_ARRIVAL_NODE,
            return_arrival_index,
            return_destination_index,
        )
        return TripRouteSkeleton(trip_id=state.trip_id, nodes=nodes, legs=legs)

    @staticmethod
    def _validate_trip_state_and_request(
        state: TripState, request: ResolvedPublicTransportPlanningRequest
    ) -> None:
        if state.trip_id != request.trip_id:
            raise ValueError("planning request trip_id must match TripState")
        if state.intercity_travel_mode is None:
            raise ValueError("TripState intercity_travel_mode is required")
        if state.intercity_travel_mode is IntercityTravelMode.DRIVING:
            raise ValueError("TripState intercity_travel_mode must be public transport")
        if (
            request.outbound_intercity.travel_mode is not state.intercity_travel_mode
            or request.return_intercity.travel_mode is not state.intercity_travel_mode
        ):
            raise ValueError("intercity legs must match TripState intercity_travel_mode")
        if state.local_travel_mode is not TravelMode.PUBLIC_TRANSPORT:
            raise ValueError("TripState local_travel_mode must be public_transport")
        if state.departure_date is None or state.return_date is None:
            raise ValueError("TripState departure_date and return_date are required")

    @staticmethod
    def _require_resolved_location(
        location_intent: LocationIntent | None, *, field_name: str
    ) -> ResolvedLocation:
        if (
            location_intent is None
            or location_intent.resolution_status is not LocationResolutionStatus.RESOLVED
            or location_intent.resolved_location is None
        ):
            raise ValueError(f"TripState {field_name} must be resolved")
        return location_intent.resolved_location

    def _resolved_places_by_poi_id(self, state: TripState) -> dict[str, ResolvedLocation]:
        places_by_poi_id: dict[str, ResolvedLocation] = {}
        for place in state.places:
            location = self._require_resolved_location(place, field_name="places")
            if location.poi_id in places_by_poi_id:
                raise ValueError("TripState places must not contain duplicate resolved POI IDs")
            places_by_poi_id[location.poi_id] = location
        return places_by_poi_id

    @staticmethod
    def _validate_daily_places(
        state: TripState,
        request: ResolvedPublicTransportPlanningRequest,
        places_by_poi_id: dict[str, ResolvedLocation],
    ) -> None:
        assert state.departure_date is not None
        assert state.return_date is not None
        maximum_day_number = (state.return_date - state.departure_date).days + 1
        if any(
            daily_plan.day_number > maximum_day_number
            for daily_plan in request.daily_places
        ):
            raise ValueError("daily_places day_number must be within the TripState date range")
        requested_poi_ids = [
            poi_id
            for daily_plan in request.daily_places
            for poi_id in daily_plan.place_poi_ids
        ]
        if len(requested_poi_ids) != len(set(requested_poi_ids)):
            raise ValueError("daily_places must not repeat a TripState place across days")
        if set(requested_poi_ids) != set(places_by_poi_id):
            raise ValueError("daily_places must reference every TripState place exactly once")

    @staticmethod
    def _validate_city_consistency(
        *,
        origin: ResolvedLocation,
        destination: ResolvedLocation,
        return_destination: ResolvedLocation,
        accommodation: ResolvedLocation,
        places: object,
        request: ResolvedPublicTransportPlanningRequest,
    ) -> None:
        TripRouteSkeletonService._require_same_city(
            origin, request.outbound_intercity.departure_node, "origin and outbound departure node"
        )
        target_locations = [
            request.outbound_intercity.arrival_node,
            accommodation,
            *places,
        ]
        for location in target_locations:
            TripRouteSkeletonService._require_same_city(
                destination, location, "destination, accommodation, and daily places"
            )
        TripRouteSkeletonService._require_same_city(
            accommodation, request.return_intercity.departure_node, "accommodation and return departure node"
        )
        TripRouteSkeletonService._require_same_city(
            return_destination, request.return_intercity.arrival_node, "return destination and return arrival node"
        )

    @staticmethod
    def _require_same_city(
        first: ResolvedLocation, second: ResolvedLocation, relationship: str
    ) -> None:
        first_city_code = first.city_code
        second_city_code = second.city_code
        if not first_city_code or not second_city_code:
            raise ValueError(f"{relationship} require city_code")
        if first_city_code != second_city_code:
            raise ValueError(f"{relationship} must be in the same city")

    @staticmethod
    def _append_node(
        nodes: list[TripRouteNode],
        kind: TripRouteNodeKind,
        location: ResolvedLocation,
        *,
        day_number: int | None = None,
    ) -> object:
        node = TripRouteNode(kind=kind, location=location, day_number=day_number)
        nodes.append(node)
        return node.node_id

    @staticmethod
    def _append_leg(
        legs: list[TripRouteSkeletonLeg],
        kind: TripRouteLegKind,
        origin_node_id: object,
        destination_node_id: object,
    ) -> None:
        legs.append(
            TripRouteSkeletonLeg(
                kind=kind,
                origin_node_id=origin_node_id,
                destination_node_id=destination_node_id,
            )
        )
