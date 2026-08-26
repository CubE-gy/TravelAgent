"""Deterministic merging of structured conversational updates."""

from app.schemas.trip_state import TripState, TripStatePatch
from app.models.enums import IntercityTravelMode


def merge_trip_state(current_state: TripState, patch: TripStatePatch) -> TripState:
    """Return a validated new state without mutating the current state.

    Only fields explicitly present in ``patch`` are changed. An explicitly null
    ``places`` value clears the place list; null values for other optional fields
    clear those fields.
    """
    merged_data = current_state.model_dump()
    for field_name in patch.model_fields_set:
        value = getattr(patch, field_name)
        merged_data[field_name] = [] if field_name == "places" and value is None else value
    if (
        "intercity_travel_mode" in patch.model_fields_set
        and patch.intercity_travel_mode is not IntercityTravelMode.DRIVING
        and "vehicle" not in patch.model_fields_set
    ):
        merged_data["vehicle"] = None
    return TripState.model_validate(merged_data)
