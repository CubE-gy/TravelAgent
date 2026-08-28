"""HTTP request and response models for one Stage 2 Trip conversation turn."""

from typing import Literal

from pydantic import BaseModel, Field, field_validator

from app.schemas.base import ApiRequest
from app.schemas.trip_state import TripState
from app.schemas.trip_state_assessment import TripStateAssessment
from app.schemas.trip_state_clarification import TripStateClarification
from app.schemas.trip import TripRead


class _TripMessage(ApiRequest):
    """Common natural-language content for conversation endpoints."""

    message: str = Field(min_length=1, max_length=5000)

    @field_validator("message")
    @classmethod
    def message_must_not_be_blank(cls, value: str) -> str:
        normalized_value = value.strip()
        if not normalized_value:
            raise ValueError("message must not be blank")
        return normalized_value


class TripConversationCreate(_TripMessage):
    """The first natural-language message that creates a TripState."""


class TripMessageCreate(_TripMessage):
    """One natural-language message that updates an existing TripState."""

    expected_revision: int = Field(ge=0)


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
    revision: int = Field(ge=0)
    location_failures: list[LocationResolutionFailureRead]
    assessment: TripStateAssessment
    clarification: TripStateClarification


class TripConversationCreateRead(TripConversationRead):
    """The first conversation result, including its newly persisted Trip."""

    trip: TripRead
