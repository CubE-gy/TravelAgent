"""Read model for the Stage 4 map workspace."""

from pydantic import BaseModel

from app.schemas.trip import TripRead
from app.schemas.trip_public_transport_plan import PublicTransportTripPlanRead
from app.schemas.trip_state import TripState


class TripWorkspaceRead(BaseModel):
    """All persisted facts required to restore one map workspace."""

    trip: TripRead
    state: TripState | None = None
    public_transport_plan: PublicTransportTripPlanRead | None = None
