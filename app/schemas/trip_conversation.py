"""HTTP request and response models for one Stage 2 Trip conversation turn."""

from typing import Literal

from pydantic import BaseModel, Field, field_validator

from app.schemas.trip_state import TripState
from app.schemas.trip_state_assessment import TripStateAssessment
from app.schemas.trip_state_clarification import TripStateClarification
from app.schemas.trip import TripRead


class TripMessageCreate(BaseModel):
    """One natural-language message that updates an existing Trip."""

    message: str = Field(min_length=1, max_length=5000)

    @field_validator("message")
    @classmethod
    def message_must_not_be_blank(cls, value: str) -> str:
        normalized_value = value.strip()
        if not normalized_value:
            raise ValueError("message must not be blank")
        return normalized_value


class LocationResolutionFailureRead(BaseModel):
    """A map lookup failure retained without discarding the user's location."""

    field: Literal[
        "origin", "destination", "return_destination", "accommodation", "places"
    ]
    query: str
    error_code: str
    place_index: int | None = Field(default=None, ge=0)


class TripConversationRead(BaseModel):
    """The persisted state and only the questions required for the next turn."""

    state: TripState
    location_failures: list[LocationResolutionFailureRead]
    assessment: TripStateAssessment
    clarification: TripStateClarification


class TripConversationCreateRead(TripConversationRead):
    """The first conversation result, including its newly persisted Trip."""

    trip: TripRead
