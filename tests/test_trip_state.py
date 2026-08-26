from uuid import uuid4

import pytest
from pydantic import ValidationError

from app.models.enums import IntercityTravelMode, TravelMode, VehicleEnergyType
from app.schemas.map import PoiCandidate, ResolvedLocation
from app.schemas.trip_state import LocationIntent, LocationResolutionStatus, TripState


def candidate(poi_id: str, name: str) -> PoiCandidate:
    return PoiCandidate(
        poi_id=poi_id,
        name=name,
        coordinate={"latitude": 39.9, "longitude": 116.4},
    )


def resolved_location() -> ResolvedLocation:
    return ResolvedLocation(
        poi_id="B000A1",
        name="故宫博物院",
        address="北京市东城区景山前街4号",
        coordinate={"latitude": 39.9163, "longitude": 116.3972},
    )


def test_trip_state_accepts_partial_conversation_state() -> None:
    trip_id = uuid4()

    state = TripState(
        trip_id=trip_id,
        destination={"query": "  北京  "},
        places=[{"query": "故宫博物院"}],
    )

    assert state.trip_id == trip_id
    assert state.destination is not None
    assert state.destination.query == "北京"
    assert state.destination.resolution_status is LocationResolutionStatus.UNRESOLVED
    assert state.accommodation is None
    assert state.intercity_travel_mode is None
    assert state.local_travel_mode is None


def test_location_intent_accepts_ambiguous_map_candidates() -> None:
    location = LocationIntent(
        query="万达广场",
        resolution_status=LocationResolutionStatus.AMBIGUOUS,
        candidates=[candidate("B000A1", "北京万达广场"), candidate("B000A2", "上海万达广场")],
    )

    assert [item.name for item in location.candidates] == ["北京万达广场", "上海万达广场"]
    assert location.resolved_location is None


def test_location_intent_accepts_one_confirmed_amap_location() -> None:
    location = LocationIntent(
        query="故宫",
        resolution_status=LocationResolutionStatus.RESOLVED,
        resolved_location=resolved_location(),
    )

    assert location.resolved_location is not None
    assert location.resolved_location.name == "故宫博物院"
    assert location.candidates == []


@pytest.mark.parametrize(
    "location_data",
    [
        {
            "query": "故宫",
            "resolution_status": LocationResolutionStatus.UNRESOLVED,
            "candidates": [candidate("B000A1", "故宫博物院")],
        },
        {
            "query": "万达广场",
            "resolution_status": LocationResolutionStatus.AMBIGUOUS,
            "candidates": [candidate("B000A1", "北京万达广场")],
        },
        {
            "query": "故宫",
            "resolution_status": LocationResolutionStatus.RESOLVED,
        },
    ],
)
def test_location_intent_rejects_confirmation_data_incompatible_with_status(
    location_data: dict[str, object],
) -> None:
    with pytest.raises(ValidationError):
        LocationIntent(**location_data)


def test_trip_state_accepts_vehicle_only_for_driving() -> None:
    state = TripState(
        trip_id=uuid4(),
        intercity_travel_mode=IntercityTravelMode.DRIVING,
        vehicle={"energy_type": VehicleEnergyType.ELECTRIC, "range_km": 500},
    )

    assert state.vehicle is not None
    assert state.vehicle.range_km == 500


def test_trip_state_rejects_vehicle_with_non_driving_mode() -> None:
    with pytest.raises(ValidationError):
        TripState(
            trip_id=uuid4(),
            intercity_travel_mode=IntercityTravelMode.HIGH_SPEED_RAIL,
            vehicle={"energy_type": VehicleEnergyType.GASOLINE, "range_km": 650},
        )


def test_trip_state_rejects_return_before_departure() -> None:
    with pytest.raises(ValidationError, match="return_date"):
        TripState(
            trip_id=uuid4(),
            departure_date="2026-10-03",
            return_date="2026-10-01",
        )
