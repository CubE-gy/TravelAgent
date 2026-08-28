"""LLM-backed extraction of one conversational TripState update."""

import json
from enum import Enum

from pydantic import BaseModel, Field, field_validator, model_validator

from app.schemas.trip_state import TripState, TripStateLocationField, TripStatePatch
from app.schemas.trip_state_operation import (
    TripStateLocationConfirmationOperation,
    TripStateOperation,
    TripStatePatchOperation,
)
from app.services.llm_provider import LlmMessage, LlmMessageRole, LlmProvider


EXTRACTION_INSTRUCTIONS = """You extract only explicit travel-information changes.
Return data that matches the requested schema. Do not invent missing information,
routes, distances, POIs, coordinates, candidate lists, or vehicle details. For a
new location, provide only its user query so it remains unresolved until Amap
confirms it. The strict response schema requires every property in patch: use
null for a field the user did not mention. Do not use null as a request to clear
stored state. Instead, list an explicitly removed field in cleared_fields. When
changing places,
provide the complete replacement place list because the patch replaces that list.
When the user chooses a location from existing ambiguous candidates, provide only
that candidate's exact poi_id from the current TripState and its field. Do not
create a new location or candidate for a confirmation.

For Chinese travel messages, extract every explicitly stated item using these
field mappings: “从 X 出发” is origin; “去 X” is destination; “回 X” or
“最终到 X” is return_destination; “X 年 X 月 X 日出发/去” is departure_date;
“X 年 X 月 X 日回/返程” is return_date; “住 X” is accommodation; “想去 X” is
places; “城际坐高铁/火车/飞机/自驾” is intercity_travel_mode; and “当地坐公共
交通/自驾” is local_travel_mode. When one message explicitly supplies several
of these items, include every supplied item in the patch.
Resolve a reference such as “原地”, “出发地”, “那里”, or “同上” from the
current TripState or another explicit value in the same user message. Output the
actual location query, never the reference word itself. For example, if the user
says “从南京新街口出发……返回原地”, return_destination.query must be
“南京新街口”.
Use cleared_fields only for fields the user explicitly asks to remove. Include
every explicit item in the user message even though other patch properties are
null. A null patch value by itself means the user did not mention that field and
must not clear stored state.
"""

RETRY_EXTRACTION_INSTRUCTIONS = """The preceding travel message contains explicit
TripState information, but the previous extraction produced an empty patch. Re-read
the message and return every explicitly stated field using the schema. Do not return
an empty patch when the message states an origin, destination, return destination,
date, accommodation, place, intercity mode, local mode, or vehicle information.
"""

_EXPLICIT_TRIP_INFORMATION_MARKERS = (
    "出发",
    "去",
    "回",
    "返程",
    "住",
    "酒店",
    "景点",
    "想去",
    "高铁",
    "火车",
    "飞机",
    "城际",
    "当地",
    "自驾",
    "公共交通",
    "公交",
    "地铁",
)


class LocationConfirmationIntent(BaseModel):
    """One user choice among candidates already stored in the current TripState."""

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
    def place_index_must_match_field(self) -> "LocationConfirmationIntent":
        if self.field is TripStateLocationField.PLACES and self.place_index is None:
            raise ValueError("places confirmation requires place_index")
        if self.field is not TripStateLocationField.PLACES and self.place_index is not None:
            raise ValueError("only places confirmation may contain place_index")
        return self


class TripStatePatchField(str, Enum):
    """A TripState field that the user explicitly asked to clear."""

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


class TripStateMessageUnderstanding(BaseModel):
    """LLM interpretation limited to a state patch and an optional candidate choice."""

    patch: TripStatePatch = Field(default_factory=TripStatePatch)
    cleared_fields: list[TripStatePatchField] = Field(default_factory=list)
    location_confirmation: LocationConfirmationIntent | None = None

    def operations(
        self,
    ) -> tuple[TripStateOperation, ...]:
        """Translate LLM output into deterministic State mutation operations."""
        operations: list[TripStateOperation] = []
        if self.patch.model_fields_set:
            operations.append(TripStatePatchOperation(patch=self.patch))
        if self.location_confirmation is not None:
            operations.append(
                TripStateLocationConfirmationOperation(
                    field=self.location_confirmation.field,
                    selected_poi_id=self.location_confirmation.selected_poi_id,
                    place_index=self.location_confirmation.place_index,
                )
            )
        return tuple(operations)

    @model_validator(mode="after")
    def strict_schema_nulls_are_not_implicit_clears(self) -> "TripStateMessageUnderstanding":
        """Keep actual values and separately declared clears for every provider shape."""
        patch_data = self.patch.model_dump(exclude_unset=True, exclude_none=True)
        patch_data.update({field.value: None for field in self.cleared_fields})
        self.patch = TripStatePatch.model_validate(patch_data)
        return self


class TripStateExtractionService:
    """Translate one user message into a validated, non-persistent state patch."""

    def __init__(self, provider: LlmProvider) -> None:
        self._provider = provider

    def extract(
        self, current_state: TripState, user_message: str
    ) -> TripStateMessageUnderstanding:
        """Return explicit field changes and, optionally, one existing candidate choice."""
        normalized_message = user_message.strip()
        if not normalized_message:
            raise ValueError("user_message must not be blank")

        state_json = json.dumps(
            current_state.model_dump(mode="json"),
            ensure_ascii=False,
            separators=(",", ":"),
        )
        messages = [
            LlmMessage(role=LlmMessageRole.SYSTEM, content=EXTRACTION_INSTRUCTIONS),
            LlmMessage(
                role=LlmMessageRole.USER,
                content=(
                    f"Current TripState JSON:\n{state_json}\n\n"
                    f"User message:\n{normalized_message}"
                ),
            ),
        ]
        understanding = self._provider.generate_structured(
            messages, TripStateMessageUnderstanding
        )
        if (
            not understanding.patch.model_fields_set
            and any(marker in normalized_message for marker in _EXPLICIT_TRIP_INFORMATION_MARKERS)
        ):
            understanding = self._provider.generate_structured(
                [
                    LlmMessage(
                        role=LlmMessageRole.SYSTEM,
                        content=EXTRACTION_INSTRUCTIONS + "\n" + RETRY_EXTRACTION_INSTRUCTIONS,
                    ),
                    messages[1],
                ],
                TripStateMessageUnderstanding,
            )
        return understanding
