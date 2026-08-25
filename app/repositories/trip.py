from sqlalchemy.orm import Session
from uuid import UUID

from app.models.trip import Trip
from app.schemas.trip import TripCreate, TripUpdate


def create_trip(session: Session, trip_data: TripCreate) -> Trip:
    """Persist and return a new Trip."""
    trip = Trip(**trip_data.model_dump())
    session.add(trip)
    session.commit()
    session.refresh(trip)
    return trip


def get_trip_by_id(session: Session, trip_id: UUID) -> Trip | None:
    """Return one Trip by its identifier, if it exists."""
    return session.get(Trip, trip_id)


def update_trip(session: Session, trip: Trip, trip_data: TripUpdate) -> Trip:
    """Apply validated changes to a Trip and persist them."""
    for field_name, value in trip_data.model_dump(exclude_unset=True).items():
        setattr(trip, field_name, value)

    if trip.start_date > trip.end_date:
        raise ValueError("start_date must not be after end_date")

    session.commit()
    session.refresh(trip)
    return trip
