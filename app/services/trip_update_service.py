"""Atomic Trip API updates that preserve TripState date consistency."""

from sqlalchemy.orm import Session

from app.models.trip import Trip
from app.repositories.trip import update_trip
from app.repositories.trip_state import get_trip_state, save_trip_state
from app.schemas.trip import TripUpdate
from app.schemas.trip_state import TripState


class TripUpdateService:
    """Update compatibility fields while keeping planning dates in one transaction."""

    def update(self, session: Session, trip: Trip, trip_data: TripUpdate) -> Trip:
        """Persist a Trip update and mirror explicit dates to an existing TripState."""
        changed_fields = trip_data.model_fields_set
        dates_changed = bool({"start_date", "end_date"} & changed_fields)
        updated_state = self._updated_state(session, trip.id, trip_data) if dates_changed else None

        update_trip(session, trip, trip_data, commit=False)
        if updated_state is not None:
            save_trip_state(session, updated_state, commit=False)
        session.commit()
        session.refresh(trip)
        return trip

    @staticmethod
    def _updated_state(
        session: Session, trip_id: object, trip_data: TripUpdate
    ) -> TripState | None:
        state = get_trip_state(session, trip_id)
        if state is None:
            return None

        state_data = state.model_dump()
        if "start_date" in trip_data.model_fields_set:
            state_data["departure_date"] = trip_data.start_date
        if "end_date" in trip_data.model_fields_set:
            state_data["return_date"] = trip_data.end_date
        return TripState.model_validate(state_data)
