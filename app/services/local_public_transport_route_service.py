"""Resolve city-local public-transport facts for an ordered route skeleton."""

from typing import Protocol

from app.schemas.map import ResolvedLocation, Route
from app.schemas.trip_public_transport_plan import (
    LocalPublicTransportRouteFact,
    TripRouteLegKind,
    TripRouteSkeleton,
)


class LocalPublicTransportRouteProvider(Protocol):
    """The Stage 1 map capability needed for one city-local route query."""

    def get_local_public_transport_route(
        self, origin: ResolvedLocation, destination: ResolvedLocation
    ) -> Route:
        """Return one provider-normalized route between two same-city locations."""


class LocalPublicTransportRouteInputError(ValueError):
    """Raised when a skeleton leg cannot be queried as city-local transport."""


class LocalPublicTransportRouteService:
    """Bind real Amap facts to every non-intercity leg without changing their order."""

    _INTERCITY_LEG_KINDS = {
        TripRouteLegKind.OUTBOUND_INTERCITY,
        TripRouteLegKind.RETURN_INTERCITY,
    }

    def __init__(self, map_service: LocalPublicTransportRouteProvider) -> None:
        self._map_service = map_service

    def resolve(self, skeleton: TripRouteSkeleton) -> list[LocalPublicTransportRouteFact]:
        """Query each local leg in skeleton order and propagate map-service failures."""
        route_facts: list[LocalPublicTransportRouteFact] = []
        for leg in skeleton.legs:
            if leg.kind in self._INTERCITY_LEG_KINDS:
                continue
            origin = skeleton.nodes[leg.origin_node_index].location
            destination = skeleton.nodes[leg.destination_node_index].location
            self._validate_same_city(origin, destination, leg_kind=leg.kind)
            route_facts.append(
                LocalPublicTransportRouteFact(
                    trip_id=skeleton.trip_id,
                    skeleton_leg=leg,
                    route=self._map_service.get_local_public_transport_route(origin, destination),
                )
            )
        return route_facts

    @staticmethod
    def _validate_same_city(
        origin: ResolvedLocation,
        destination: ResolvedLocation,
        *,
        leg_kind: TripRouteLegKind,
    ) -> None:
        origin_city_code = LocalPublicTransportRouteService._city_code(origin)
        destination_city_code = LocalPublicTransportRouteService._city_code(destination)
        if origin_city_code is None or destination_city_code is None:
            raise LocalPublicTransportRouteInputError(
                f"{leg_kind.value} requires city_code for both locations"
            )
        if origin_city_code != destination_city_code:
            raise LocalPublicTransportRouteInputError(
                f"{leg_kind.value} requires locations in the same city"
            )

    @staticmethod
    def _city_code(location: ResolvedLocation) -> str | None:
        if location.city_code is None:
            return None
        return location.city_code.strip() or None
