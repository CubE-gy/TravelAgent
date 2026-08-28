from uuid import uuid4

import pytest
from pydantic import ValidationError

from app.models.enums import IntercityTravelMode, VehicleEnergyType
from app.schemas.trip_state import TripState, TripStatePatch
from app.services.trip_state_merger import merge_trip_state


def existing_state() -> TripState:
    return TripState(
        trip_id=uuid4(),
        destination={"query": "北京"},
        accommodation={"query": "王府井附近"},
        places=[{"query": "故宫博物院"}],
        intercity_travel_mode=IntercityTravelMode.DRIVING,
        vehicle={"energy_type": VehicleEnergyType.ELECTRIC, "range_km": 500},
    )


def test_merge_overwrites_explicit_field_and_preserves_others() -> None:
    current_state = existing_state()

    merged_state = merge_trip_state(
        current_state,
        TripStatePatch(accommodation={"query": "国贸附近"}),
    )

    assert merged_state.trip_id == current_state.trip_id
    assert merged_state.destination == current_state.destination
    assert merged_state.accommodation is not None
    assert merged_state.accommodation.query == "国贸附近"
    assert merged_state.places == current_state.places
    assert merged_state.intercity_travel_mode is IntercityTravelMode.DRIVING
    assert merged_state.vehicle == current_state.vehicle


def test_merge_clears_an_optional_field_only_when_explicitly_null() -> None:
    current_state = existing_state()

    merged_state = merge_trip_state(current_state, TripStatePatch(accommodation=None))

    assert "accommodation" in TripStatePatch(accommodation=None).model_fields_set
    assert merged_state.accommodation is None
    assert merged_state.destination == current_state.destination


def test_merge_replaces_places_only_when_patch_explicitly_provides_them() -> None:
    current_state = existing_state()

    merged_state = merge_trip_state(
        current_state,
        TripStatePatch(places=[{"query": "天坛公园"}, {"query": "颐和园"}]),
    )

    assert [place.query for place in merged_state.places] == ["天坛公园", "颐和园"]
    assert current_state.places[0].query == "故宫博物院"


def test_merge_clears_places_when_patch_explicitly_sets_null() -> None:
    merged_state = merge_trip_state(existing_state(), TripStatePatch(places=None))

    assert merged_state.places == []


def test_changing_intercity_transport_from_driving_clears_vehicle_without_mutating_current_state() -> None:
    current_state = existing_state()

    merged_state = merge_trip_state(
        current_state,
        TripStatePatch(intercity_travel_mode=IntercityTravelMode.HIGH_SPEED_RAIL),
    )

    assert merged_state.intercity_travel_mode is IntercityTravelMode.HIGH_SPEED_RAIL
    assert merged_state.vehicle is None
    assert current_state.intercity_travel_mode is IntercityTravelMode.DRIVING
    assert current_state.vehicle is not None
    assert current_state.vehicle.energy_type is VehicleEnergyType.ELECTRIC
