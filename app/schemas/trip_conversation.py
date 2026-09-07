"""HTTP request and response models for one Stage 2 Trip conversation turn."""

from typing import Literal
from uuid import UUID

from pydantic import BaseModel, Field, field_validator, model_validator

from app.schemas.base import ApiRequest
from app.schemas.trip_state import TripState
from app.schemas.trip_state_assessment import TripStateAssessment
from app.schemas.trip_state_clarification import TripStateClarification
from app.schemas.trip import TripRead
from app.schemas.trip_recommendation import TripRecommendationContext, TripRecommendationRead


class _TripMessage(ApiRequest):
    """Common natural-language content for conversation endpoints."""

    message: str = Field(min_length=1, max_length=5000)
    conversation_context: list["ConversationContextMessage"] = Field(default_factory=list, max_length=10)
    recommendation_context: TripRecommendationContext | None = None

    @field_validator("message")
    @classmethod
    def message_must_not_be_blank(cls, value: str) -> str:
        normalized_value = value.strip()
        if not normalized_value:
            raise ValueError("message must not be blank")
        return normalized_value

    @model_validator(mode="after")
    def retain_the_latest_context_within_total_limit(self) -> "_TripMessage":
        """Browser context is transient and bounded even when a client bypasses the UI."""
        retained: list[ConversationContextMessage] = []
        total = 0
        for item in reversed(self.conversation_context):
            if total + len(item.content) > 8000:
                continue
            retained.append(item)
            total += len(item.content)
        self.conversation_context = list(reversed(retained))
        return self


class TripConversationCreate(_TripMessage):
    """The first natural-language message that creates a TripState."""


class TripMessageCreate(_TripMessage):
    """One natural-language message that updates an existing TripState."""

    expected_revision: int = Field(ge=0)


class ConversationContextMessage(BaseModel):
    """A transient browser turn supplied only to understand references."""

    role: Literal["user", "assistant"]
    content: str = Field(min_length=1, max_length=1000)


class LocationResolutionFailureRead(BaseModel):
    """A map lookup failure retained without discarding the user's location."""

    field: Literal[
        "origin", "destination", "return_destination", "outbound_departure_station",
        "outbound_arrival_station", "accommodation", "places"
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
    assistant_message: str | None = None
    recommendations: list[TripRecommendationRead] = Field(default_factory=list, max_length=4)
    recommendation_session_id: UUID | None = None
    recommendation_session_id: UUID | None = None


class TripConversationCreateRead(TripConversationRead):
    """The first conversation result, including its newly persisted Trip."""

    trip: TripRead
