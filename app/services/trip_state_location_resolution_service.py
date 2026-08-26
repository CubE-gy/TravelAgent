"""Batch Amap confirmation for the locations contained in one TripState."""

from dataclasses import dataclass
from typing import Literal

from app.schemas.trip_state import LocationIntent, LocationResolutionStatus, TripState
from app.services.location_resolution_service import LocationMapService, resolve_location_intent
from app.services.map_errors import MapServiceError


LocationField = Literal["origin", "destination", "return_destination", "accommodation", "places"]


@dataclass(frozen=True)
class LocationResolutionFailure:
    """A non-destructive map failure for one user-supplied location."""

    field: LocationField
    query: str
    error_code: str
    place_index: int | None = None


@dataclass(frozen=True)
class TripStateLocationResolutionResult:
    """The resolved state plus any locations that could not be queried."""

    state: TripState
    failures: list[LocationResolutionFailure]


class TripStateLocationResolutionService:
    """Resolve each unresolved TripState location without mutating the input state."""

    def __init__(self, map_service: LocationMapService) -> None:
        self._map_service = map_service

    def resolve(self, state: TripState) -> TripStateLocationResolutionResult:
        """Return a new state with Amap facts where available for each location."""
        failures: list[LocationResolutionFailure] = []
        origin = self._resolve_location(
            state.origin,
            field="origin",
            failures=failures,
        )
        destination = self._resolve_location(
            state.destination,
            field="destination",
            failures=failures,
        )
        return_destination = self._resolve_location(
            state.return_destination,
            field="return_destination",
            failures=failures,
        )
        accommodation = self._resolve_location(
            state.accommodation,
            field="accommodation",
            failures=failures,
        )
        places = [
            self._resolve_location(
                location,
                field="places",
                place_index=index,
                failures=failures,
            )
            for index, location in enumerate(state.places)
        ]
        return TripStateLocationResolutionResult(
            state=state.model_copy(
                update={
                    "origin": origin,
                    "destination": destination,
                    "return_destination": return_destination,
                    "accommodation": accommodation,
                    "places": places,
                }
            ),
            failures=failures,
        )

    def _resolve_location(
        self,
        location: LocationIntent | None,
        *,
        field: LocationField,
        failures: list[LocationResolutionFailure],
        place_index: int | None = None,
    ) -> LocationIntent | None:
        if location is None or location.resolution_status is not LocationResolutionStatus.UNRESOLVED:
            return location
        try:
            return resolve_location_intent(location, self._map_service)
        except MapServiceError as error:
            failures.append(
                LocationResolutionFailure(
                    field=field,
                    query=location.query,
                    error_code=error.code,
                    place_index=place_index,
                )
            )
            return location
