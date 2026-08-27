"""Persistence operations for the current generated plan of one Trip."""

from uuid import UUID

from sqlalchemy.orm import Session

from app.models.trip import Trip
from app.models.trip_plan import TripPlanRecord
from app.schemas.trip_public_transport_plan import PublicTransportTripPlan


def get_trip_plan(session: Session, trip_id: UUID) -> PublicTransportTripPlan | None:
    """Return the current persisted public-transport plan for one Trip, if present."""
    record = session.get(TripPlanRecord, trip_id)
    if record is None:
        return None
    return PublicTransportTripPlan.model_validate(record.plan)


def save_trip_plan(
    session: Session, plan: PublicTransportTripPlan, *, commit: bool = True
) -> PublicTransportTripPlan:
    """Create or replace the current public-transport plan for an existing Trip."""
    if session.get(Trip, plan.trip_id) is None:
        raise ValueError("Trip not found")

    record = session.get(TripPlanRecord, plan.trip_id)
    serialized_plan = plan.model_dump(mode="json")
    if record is None:
        session.add(TripPlanRecord(trip_id=plan.trip_id, plan=serialized_plan))
    else:
        record.plan = serialized_plan

    if commit:
        session.commit()
    else:
        session.flush()
    return plan
