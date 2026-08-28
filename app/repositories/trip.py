from datetime import date
from uuid import UUID

from sqlalchemy.orm import Session

from app.models.trip import Trip
from app.schemas.trip import TripCreate, TripUpdate


def create_trip(session: Session, trip_data: TripCreate) -> Trip:
    """Persist and return a new Trip."""
    trip = Trip(**trip_data.model_dump())
    session.add(trip)
    session.commit()
    session.refresh(trip)
    return trip


def create_empty_trip(session: Session) -> Trip:
    """Add an initially untitled Trip for the first natural-language turn."""
    trip = Trip()
    session.add(trip)
    session.flush()
    return trip


def get_trip_by_id(session: Session, trip_id: UUID) -> Trip | None:
    """Return one Trip by its identifier, if it exists."""
    return session.get(Trip, trip_id)


def update_trip(
    session: Session, trip: Trip, trip_data: TripUpdate, *, commit: bool = True
) -> Trip:
    """Apply validated changes to a Trip, optionally inside a caller transaction."""
    for field_name, value in trip_data.model_dump(
        exclude_unset=True, exclude={"expected_revision"}
    ).items():
        setattr(trip, field_name, value)

    if (
        trip.start_date is not None
        and trip.end_date is not None
        and trip.start_date > trip.end_date
    ):
        raise ValueError("start_date must not be after end_date")

    if commit:
        session.commit()
        session.refresh(trip)
    return trip


def sync_trip_dates_from_state(
    session: Session,
    trip_id: UUID,
    *,
    start_date: date | None,
    end_date: date | None,
) -> None:
    """Mirror the planning dates from TripState onto its parent Trip in this transaction."""
    trip = get_trip_by_id(session, trip_id)
    if trip is None:
        raise ValueError("Trip not found")
    trip.start_date = start_date
    trip.end_date = end_date
