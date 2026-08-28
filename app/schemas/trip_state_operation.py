"""Explicit, ordered operations that mutate a TripState."""

from enum import Enum
from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from app.schemas.trip_state import TripStateLocationField, TripStatePatch


class TripStateOperationKind(str, Enum):
    """The supported State mutations, independent of their input source."""

    APPLY_PATCH = "apply_patch"
    CONFIRM_LOCATION = "confirm_location"


class TripStatePatchOperation(BaseModel):
    """Apply one explicit partial replacement to a TripState."""

    model_config = ConfigDict(extra="forbid")

    kind: Literal[TripStateOperationKind.APPLY_PATCH] = TripStateOperationKind.APPLY_PATCH
    patch: TripStatePatch


class TripStateLocationConfirmationOperation(BaseModel):
    """Resolve one previously stored ambiguous location candidate."""

    model_config = ConfigDict(extra="forbid")

    kind: Literal[TripStateOperationKind.CONFIRM_LOCATION] = (
        TripStateOperationKind.CONFIRM_LOCATION
    )
    field: TripStateLocationField
    selected_poi_id: str = Field(min_length=1, max_length=100)
    place_index: int | None = Field(default=None, ge=0)

    @field_validator("selected_poi_id")
    @classmethod
    def selected_poi_id_must_not_be_blank(cls, value: str) -> str:
        normalized_value = value.strip()
        if not normalized_value:
            raise ValueError("selected_poi_id must not be blank")
        return normalized_value

    @model_validator(mode="after")
    def place_index_must_match_field(self) -> "TripStateLocationConfirmationOperation":
        if self.field is TripStateLocationField.PLACES and self.place_index is None:
            raise ValueError("places confirmation requires place_index")
        if self.field is not TripStateLocationField.PLACES and self.place_index is not None:
            raise ValueError("only places confirmation may contain place_index")
        return self


TripStateOperation = Annotated[
    TripStatePatchOperation | TripStateLocationConfirmationOperation,
    Field(discriminator="kind"),
]
