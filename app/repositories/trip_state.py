"""Persistence operations for the current state of a Trip."""

from uuid import UUID

from sqlalchemy import func, update
from sqlalchemy.orm import Session

from app.models.trip import Trip
from app.models.trip_state import TripStateRecord
from app.schemas.trip_state import TripState


class TripStateRevisionConflictError(Exception):
    """Raised when a write is based on a revision that is no longer current."""

    def __init__(self, *, expected_revision: int, current_revision: int) -> None:
        self.expected_revision = expected_revision
        self.current_revision = current_revision
        super().__init__("TripState revision does not match the current revision")


def get_trip_state(session: Session, trip_id: UUID) -> TripState | None:
    """Return the current persisted state for one Trip, if it has been saved."""
    record = session.get(TripStateRecord, trip_id)
    if record is None:
        return None
    return TripState.model_validate({**record.state, "revision": record.revision})


def save_trip_state(
    session: Session,
    state: TripState,
    *,
    expected_revision: int,
) -> TripState:
    """Stage state for persistence and return it with its next revision."""
    if session.get(Trip, state.trip_id) is None:
        raise ValueError("Trip not found")

    record = session.get(TripStateRecord, state.trip_id)
    if record is None:
        if expected_revision != 0:
            raise TripStateRevisionConflictError(
                expected_revision=expected_revision,
                current_revision=0,
            )
        persisted_state = state.model_copy(update={"revision": 1})
        record = TripStateRecord(
            trip_id=state.trip_id,
            state=persisted_state.model_dump(mode="json", exclude={"revision"}),
            revision=persisted_state.revision,
        )
        session.add(record)
    else:
        persisted_state = state.model_copy(update={"revision": expected_revision + 1})
        update_result = session.execute(
            update(TripStateRecord)
            .where(
                TripStateRecord.trip_id == state.trip_id,
                TripStateRecord.revision == expected_revision,
            )
            .values(
                state=persisted_state.model_dump(mode="json", exclude={"revision"}),
                revision=persisted_state.revision,
                updated_at=func.now(),
            )
        )
        if update_result.rowcount != 1:
            raise TripStateRevisionConflictError(
                expected_revision=expected_revision,
                current_revision=record.revision,
            )

    session.flush()
    return persisted_state
