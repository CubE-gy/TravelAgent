"""Validate user-confirmed intercity facts before complete route assembly."""

from app.schemas.map import ResolvedLocation
from app.schemas.trip_public_transport_plan import ResolvedPublicTransportPlanningRequest


class IntercityPublicTransportFactInputError(ValueError):
    """Raised when confirmed intercity facts cannot safely describe a city-to-city leg."""


class IntercityPublicTransportFactValidationService:
    """Validate city-to-city constraints without inventing or fetching schedule data."""

    def validate(self, request: ResolvedPublicTransportPlanningRequest) -> None:
        """Ensure both user-confirmed legs have complete, cross-city endpoints."""
        self._validate_cross_city_nodes(
            request.outbound_intercity.departure_node,
            request.outbound_intercity.arrival_node,
            direction="outbound",
        )
        self._validate_cross_city_nodes(
            request.return_intercity.departure_node,
            request.return_intercity.arrival_node,
            direction="return",
        )

    @staticmethod
    def _validate_cross_city_nodes(
        departure_node: ResolvedLocation,
        arrival_node: ResolvedLocation,
        *,
        direction: str,
    ) -> None:
        departure_city_code = IntercityPublicTransportFactValidationService._city_code(
            departure_node
        )
        arrival_city_code = IntercityPublicTransportFactValidationService._city_code(arrival_node)
        if departure_city_code is None or arrival_city_code is None:
            raise IntercityPublicTransportFactInputError(
                f"{direction} intercity leg requires city_code for both nodes"
            )
        if departure_city_code == arrival_city_code:
            raise IntercityPublicTransportFactInputError(
                f"{direction} intercity leg requires nodes in different cities"
            )

    @staticmethod
    def _city_code(location: ResolvedLocation) -> str | None:
        if location.city_code is None:
            return None
        return location.city_code.strip() or None
