"""HTTP contracts for confirming one previously ambiguous TripState location."""

from pydantic import BaseModel, Field, field_validator, model_validator

from app.schemas.base import ApiRequest
from app.schemas.trip_state import TripState, TripStateLocationField
from app.schemas.trip_state_assessment import TripStateAssessment


class TripLocationConfirmationCreate(ApiRequest):
    """The candidate selected by the user from an existing ambiguity."""

    field: TripStateLocationField
    poi_id: str = Field(min_length=1, max_length=100)
    place_index: int | None = Field(default=None, ge=0)
    expected_revision: int = Field(ge=1)

    @field_validator("poi_id")
    @classmethod
    def poi_id_must_not_be_blank(cls, value: str) -> str:
        normalized_value = value.strip()
        if not normalized_value:
            raise ValueError("poi_id must not be blank")
        return normalized_value

    @model_validator(mode="after")
    def place_index_must_match_field(self) -> "TripLocationConfirmationCreate":
        if self.field is TripStateLocationField.PLACES and self.place_index is None:
            raise ValueError("places confirmation requires place_index")
        if self.field is not TripStateLocationField.PLACES and self.place_index is not None:
            raise ValueError("only places confirmation may contain place_index")
        return self


class TripLocationConfirmationRead(BaseModel):
    """The state after one candidate has been confirmed against Amap."""

    state: TripState
    revision: int = Field(ge=0)
    assessment: TripStateAssessment
