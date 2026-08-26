"""Persistence operations for the current state of a Trip."""

from uuid import UUID

from sqlalchemy.orm import Session

from app.models.trip import Trip
from app.models.trip_state import TripStateRecord
from app.schemas.trip_state import TripState


def get_trip_state(session: Session, trip_id: UUID) -> TripState | None:
    """Return the current persisted state for one Trip, if it has been saved."""
    record = session.get(TripStateRecord, trip_id)
    if record is None:
        return None
    return TripState.model_validate(record.state)


def save_trip_state(session: Session, state: TripState, *, commit: bool = True) -> TripState:
    """Create or replace the current state associated with an existing Trip."""
    if session.get(Trip, state.trip_id) is None:
        raise ValueError("Trip not found")

    record = session.get(TripStateRecord, state.trip_id)
    serialized_state = state.model_dump(mode="json")
    if record is None:
        session.add(TripStateRecord(trip_id=state.trip_id, state=serialized_state))
    else:
        record.state = serialized_state

    if commit:
        session.commit()
    else:
        session.flush()
    return state
