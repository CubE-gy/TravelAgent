"""Atomic Trip API updates that preserve TripState date consistency."""

from sqlalchemy.orm import Session

from app.models.trip import Trip
from app.repositories.trip import update_trip
from app.repositories.trip_state import (
    TripStateRevisionConflictError,
    get_trip_state,
    save_trip_state,
)
from app.schemas.trip import TripUpdate
from app.schemas.trip_state import TripState


class TripUpdateService:
    """Update compatibility fields while keeping planning dates in one transaction."""

    def update(self, session: Session, trip: Trip, trip_data: TripUpdate) -> Trip:
        """Persist a Trip update and mirror explicit dates to an existing TripState."""
        changed_fields = trip_data.model_fields_set
        dates_changed = bool({"start_date", "end_date"} & changed_fields)
        state = get_trip_state(session, trip.id) if dates_changed else None
        expected_revision = trip_data.expected_revision
        current_revision = state.revision if state is not None else 0
        if dates_changed and expected_revision != current_revision:
            raise TripStateRevisionConflictError(
                expected_revision=expected_revision if expected_revision is not None else -1,
                current_revision=current_revision,
            )
        updated_state = self._updated_state(state, trip_data) if dates_changed else None

        try:
            update_trip(session, trip, trip_data, commit=False)
            if updated_state is not None:
                save_trip_state(session, updated_state, expected_revision=expected_revision)
            session.commit()
            session.refresh(trip)
            return trip
        except Exception:
            session.rollback()
            raise

    @staticmethod
    def _updated_state(state: TripState | None, trip_data: TripUpdate) -> TripState | None:
        if state is None:
            return None

        state_data = state.model_dump()
        if "start_date" in trip_data.model_fields_set:
            state_data["departure_date"] = trip_data.start_date
        if "end_date" in trip_data.model_fields_set:
            state_data["return_date"] = trip_data.end_date
        return TripState.model_validate(state_data)
