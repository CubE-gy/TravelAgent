from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from app.db.session import get_db
from app.repositories.trip import create_trip, get_trip_by_id, update_trip
from app.schemas.trip import TripCreate, TripRead, TripUpdate


router = APIRouter(prefix="/trips", tags=["trips"])


@router.post("", response_model=TripRead, status_code=status.HTTP_201_CREATED)
def create_trip_endpoint(
    trip_data: TripCreate,
    session: Session = Depends(get_db),
) -> TripRead:
    """Create a new independent travel plan."""
    return create_trip(session, trip_data)


@router.get("/{trip_id}", response_model=TripRead)
def get_trip_endpoint(trip_id: UUID, session: Session = Depends(get_db)) -> TripRead:
    """Return one persisted travel plan."""
    trip = get_trip_by_id(session, trip_id)
    if trip is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Trip not found")
    return trip


@router.patch("/{trip_id}", response_model=TripRead)
def update_trip_endpoint(
    trip_id: UUID,
    trip_data: TripUpdate,
    session: Session = Depends(get_db),
) -> TripRead:
    """Partially update one persisted travel plan."""
    trip = get_trip_by_id(session, trip_id)
    if trip is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Trip not found")

    try:
        return update_trip(session, trip, trip_data)
    except ValueError as error:
        session.rollback()
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail=str(error),
        ) from error
