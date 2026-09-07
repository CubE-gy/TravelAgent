"""Confirmation and persistence of one user-selected ambiguous TripState location."""

from uuid import UUID

from sqlalchemy.orm import Session

from app.repositories.trip_state import (
    TripStateRevisionConflictError,
    get_trip_state,
    save_trip_state,
)
from app.schemas.trip_state import LocationIntent, TripState, TripStateLocationField
from app.schemas.trip_state_assessment import TripStateAssessment
from app.services.location_resolution_service import (
    LocationMapService,
    confirm_location_candidate,
)
from app.services.trip_state_assessor import assess_trip_state


class TripStateLocationConfirmationService:
    """Confirm exactly one already-offered Amap candidate without re-searching."""

    def __init__(self, map_service: LocationMapService) -> None:
        self._map_service = map_service

    def confirm(
        self,
        session: Session,
        trip_id: UUID,
        *,
        field: TripStateLocationField,
        selected_poi_id: str,
        expected_revision: int,
        place_index: int | None = None,
        commit: bool = True,
    ) -> tuple[TripState, TripStateAssessment]:
        """Resolve the selected candidate and save the replacement TripState."""
        try:
            state = get_trip_state(session, trip_id)
            if state is None:
                raise LookupError("TripState not found")
            if state.revision != expected_revision:
                raise TripStateRevisionConflictError(
                    expected_revision=expected_revision,
                    current_revision=state.revision,
                )

            confirmed_state = self.apply(state, field, selected_poi_id, place_index)
            persisted_state = save_trip_state(
                session,
                confirmed_state,
                expected_revision=expected_revision,
            )
            if commit:
                session.commit()
        except Exception:
            if commit:
                session.rollback()
            raise
        return persisted_state, assess_trip_state(persisted_state)

    def apply(
        self,
        state: TripState,
        field: TripStateLocationField,
        selected_poi_id: str,
        place_index: int | None = None,
    ) -> TripState:
        """Return a new state after validating and confirming one existing candidate."""
        location = self._location_at(state, field, place_index)
        confirmed_location = confirm_location_candidate(
            location, selected_poi_id, self._map_service
        )
        return self._replace_location(state, field, confirmed_location, place_index)

    @staticmethod
    def _location_at(
        state: TripState,
        field: TripStateLocationField,
        place_index: int | None,
    ) -> LocationIntent:
        if field is TripStateLocationField.ORIGIN:
            if state.origin is None:
                raise ValueError("origin is not set")
            return state.origin
        if field is TripStateLocationField.DESTINATION:
            if state.destination is None:
                raise ValueError("destination is not set")
            return state.destination
        if field is TripStateLocationField.RETURN_DESTINATION:
            if state.return_destination is None:
                raise ValueError("return_destination is not set")
            return state.return_destination
        if field is TripStateLocationField.OUTBOUND_DEPARTURE_STATION:
            if state.outbound_departure_station is None:
                raise ValueError("outbound_departure_station is not set")
            return state.outbound_departure_station
        if field is TripStateLocationField.OUTBOUND_ARRIVAL_STATION:
            if state.outbound_arrival_station is None:
                raise ValueError("outbound_arrival_station is not set")
            return state.outbound_arrival_station
        if field is TripStateLocationField.ACCOMMODATION:
            if state.accommodation is None:
                raise ValueError("accommodation is not set")
            return state.accommodation
        assert place_index is not None
        if place_index >= len(state.places):
            raise ValueError("place_index is outside the current places")
        return state.places[place_index]

    @staticmethod
    def _replace_location(
        state: TripState,
        field: TripStateLocationField,
        confirmed_location: LocationIntent,
        place_index: int | None,
    ) -> TripState:
        if field is TripStateLocationField.ORIGIN:
            return state.model_copy(update={"origin": confirmed_location})
        if field is TripStateLocationField.DESTINATION:
            return state.model_copy(update={"destination": confirmed_location})
        if field is TripStateLocationField.RETURN_DESTINATION:
            return state.model_copy(update={"return_destination": confirmed_location})
        if field is TripStateLocationField.OUTBOUND_DEPARTURE_STATION:
            return state.model_copy(update={"outbound_departure_station": confirmed_location})
        if field is TripStateLocationField.OUTBOUND_ARRIVAL_STATION:
            return state.model_copy(update={"outbound_arrival_station": confirmed_location})
        if field is TripStateLocationField.ACCOMMODATION:
            return state.model_copy(update={"accommodation": confirmed_location})
        assert place_index is not None
        places = list(state.places)
        places[place_index] = confirmed_location
        return state.model_copy(update={"places": places})
