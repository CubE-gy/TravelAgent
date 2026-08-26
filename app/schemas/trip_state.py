"""Persistent conversational state contracts for one Trip."""

from enum import Enum
from datetime import date
from uuid import UUID

from pydantic import BaseModel, Field, field_validator, model_validator

from app.models.enums import IntercityTravelMode, TravelMode
from app.schemas.map import PoiCandidate, ResolvedLocation
from app.schemas.vehicle import Vehicle


class LocationResolutionStatus(str, Enum):
    """How far a user-entered place has progressed through map confirmation."""

    UNRESOLVED = "unresolved"
    AMBIGUOUS = "ambiguous"
    RESOLVED = "resolved"


class TripStateLocationField(str, Enum):
    """A location-bearing TripState field that may need Amap confirmation."""

    ORIGIN = "origin"
    DESTINATION = "destination"
    RETURN_DESTINATION = "return_destination"
    ACCOMMODATION = "accommodation"
    PLACES = "places"


class LocationIntent(BaseModel):
    """One user-entered place and its optional Amap confirmation result."""

    query: str = Field(min_length=1, max_length=200)
    resolution_status: LocationResolutionStatus = LocationResolutionStatus.UNRESOLVED
    candidates: list[PoiCandidate] = Field(default_factory=list)
    resolved_location: ResolvedLocation | None = None

    @field_validator("query")
    @classmethod
    def query_must_not_be_blank(cls, value: str) -> str:
        normalized_value = value.strip()
        if not normalized_value:
            raise ValueError("query must not be blank")
        return normalized_value

    @model_validator(mode="after")
    def map_confirmation_data_must_match_status(self) -> "LocationIntent":
        if self.resolution_status is LocationResolutionStatus.UNRESOLVED:
            if self.candidates or self.resolved_location is not None:
                raise ValueError("unresolved location must not contain map confirmation data")
        elif self.resolution_status is LocationResolutionStatus.AMBIGUOUS:
            if len(self.candidates) < 2 or self.resolved_location is not None:
                raise ValueError(
                    "ambiguous location must contain at least two candidates and no resolved location"
                )
        elif self.candidates or self.resolved_location is None:
            raise ValueError("resolved location must contain no candidates and one resolved location")
        return self


class TripState(BaseModel):
    """The current structured planning state associated with one persisted Trip."""

    trip_id: UUID
    origin: LocationIntent | None = None
    destination: LocationIntent | None = None
    return_destination: LocationIntent | None = None
    departure_date: date | None = None
    return_date: date | None = None
    accommodation: LocationIntent | None = None
    places: list[LocationIntent] = Field(default_factory=list)
    intercity_travel_mode: IntercityTravelMode | None = None
    local_travel_mode: TravelMode | None = None
    vehicle: Vehicle | None = None

    @model_validator(mode="after")
    def dates_and_vehicle_must_match_trip(self) -> "TripState":
        if (
            self.departure_date is not None
            and self.return_date is not None
            and self.return_date < self.departure_date
        ):
            raise ValueError("return_date must not be before departure_date")
        if self.vehicle is not None and self.intercity_travel_mode is not IntercityTravelMode.DRIVING:
            raise ValueError("vehicle requires driving intercity_travel_mode")
        return self


class TripStatePatch(BaseModel):
    """A partial, explicit set of changes to apply to a TripState."""

    origin: LocationIntent | None = None
    destination: LocationIntent | None = None
    return_destination: LocationIntent | None = None
    departure_date: date | None = None
    return_date: date | None = None
    accommodation: LocationIntent | None = None
    places: list[LocationIntent] | None = None
    intercity_travel_mode: IntercityTravelMode | None = None
    local_travel_mode: TravelMode | None = None
    vehicle: Vehicle | None = None
