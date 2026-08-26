"""Deterministic completeness assessment for conversational trip state."""

from app.models.enums import IntercityTravelMode
from app.schemas.trip_state import LocationIntent, LocationResolutionStatus, TripState
from app.schemas.trip_state_assessment import (
    PendingLocation,
    RequiredTripStateField,
    TripStateAssessment,
)


def assess_trip_state(state: TripState) -> TripStateAssessment:
    """Return missing planning inputs and locations that await map confirmation."""
    missing_fields = _missing_fields(state)
    pending_locations = _pending_locations(state)
    return TripStateAssessment(
        missing_fields=missing_fields,
        pending_locations=pending_locations,
        is_ready=not missing_fields and not pending_locations,
    )


def _missing_fields(state: TripState) -> list[RequiredTripStateField]:
    missing_fields: list[RequiredTripStateField] = []
    if state.origin is None:
        missing_fields.append(RequiredTripStateField.ORIGIN)
    if state.destination is None:
        missing_fields.append(RequiredTripStateField.DESTINATION)
    if state.return_destination is None:
        missing_fields.append(RequiredTripStateField.RETURN_DESTINATION)
    if state.departure_date is None:
        missing_fields.append(RequiredTripStateField.DEPARTURE_DATE)
    if state.return_date is None:
        missing_fields.append(RequiredTripStateField.RETURN_DATE)
    if state.accommodation is None:
        missing_fields.append(RequiredTripStateField.ACCOMMODATION)
    if not state.places:
        missing_fields.append(RequiredTripStateField.PLACES)
    if state.intercity_travel_mode is None:
        missing_fields.append(RequiredTripStateField.INTERCITY_TRAVEL_MODE)
    if state.local_travel_mode is None:
        missing_fields.append(RequiredTripStateField.LOCAL_TRAVEL_MODE)
    if state.intercity_travel_mode is IntercityTravelMode.DRIVING and state.vehicle is None:
        missing_fields.append(RequiredTripStateField.VEHICLE)
    return missing_fields


def _pending_locations(state: TripState) -> list[PendingLocation]:
    pending_locations: list[PendingLocation] = []
    _add_pending_location(
        pending_locations,
        field=RequiredTripStateField.ORIGIN,
        location=state.origin,
    )
    _add_pending_location(
        pending_locations,
        field=RequiredTripStateField.DESTINATION,
        location=state.destination,
    )
    _add_pending_location(
        pending_locations,
        field=RequiredTripStateField.RETURN_DESTINATION,
        location=state.return_destination,
    )
    _add_pending_location(
        pending_locations,
        field=RequiredTripStateField.ACCOMMODATION,
        location=state.accommodation,
    )
    for index, location in enumerate(state.places):
        _add_pending_location(
            pending_locations,
            field=RequiredTripStateField.PLACES,
            location=location,
            place_index=index,
        )
    return pending_locations


def _add_pending_location(
    pending_locations: list[PendingLocation],
    *,
    field: RequiredTripStateField,
    location: LocationIntent | None,
    place_index: int | None = None,
) -> None:
    if location is None or location.resolution_status is LocationResolutionStatus.RESOLVED:
        return
    pending_locations.append(
        PendingLocation(
            field=field,
            query=location.query,
            resolution_status=location.resolution_status,
            place_index=place_index,
        )
    )
