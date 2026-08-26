"""Machine-readable completeness results for a TripState."""

from enum import Enum

from pydantic import BaseModel, Field, model_validator

from app.schemas.trip_state import LocationResolutionStatus


class RequiredTripStateField(str, Enum):
    """Information that must be known before later planning can begin."""

    ORIGIN = "origin"
    DESTINATION = "destination"
    RETURN_DESTINATION = "return_destination"
    DEPARTURE_DATE = "departure_date"
    RETURN_DATE = "return_date"
    ACCOMMODATION = "accommodation"
    PLACES = "places"
    INTERCITY_TRAVEL_MODE = "intercity_travel_mode"
    LOCAL_TRAVEL_MODE = "local_travel_mode"
    VEHICLE = "vehicle"


class PendingLocation(BaseModel):
    """A supplied location that needs map confirmation before planning."""

    field: RequiredTripStateField
    query: str = Field(min_length=1)
    resolution_status: LocationResolutionStatus
    place_index: int | None = Field(default=None, ge=0)

    @model_validator(mode="after")
    def place_index_must_match_field(self) -> "PendingLocation":
        if self.resolution_status is LocationResolutionStatus.RESOLVED:
            raise ValueError("pending location must not be resolved")
        if self.field is RequiredTripStateField.PLACES:
            if self.place_index is None:
                raise ValueError("places pending location requires place_index")
        elif self.place_index is not None:
            raise ValueError("only places pending location may contain place_index")
        return self


class TripStateAssessment(BaseModel):
    """Whether a TripState contains all required and confirmed planning input."""

    missing_fields: list[RequiredTripStateField] = Field(default_factory=list)
    pending_locations: list[PendingLocation] = Field(default_factory=list)
    is_ready: bool

    @model_validator(mode="after")
    def readiness_must_match_blockers(self) -> "TripStateAssessment":
        if self.is_ready != (not self.missing_fields and not self.pending_locations):
            raise ValueError("is_ready must match missing fields and pending locations")
        return self
