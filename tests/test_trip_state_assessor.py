from uuid import uuid4

from app.models.enums import IntercityTravelMode, TravelMode, VehicleEnergyType
from app.schemas.trip_state import LocationResolutionStatus, TripState
from app.schemas.trip_state_assessment import RequiredTripStateField
from app.services.trip_state_assessor import assess_trip_state


def resolved_location(query: str, poi_id: str) -> dict[str, object]:
    return {
        "query": query,
        "resolution_status": "resolved",
        "resolved_location": {
            "poi_id": poi_id,
            "name": query,
            "coordinate": {"latitude": 39.9, "longitude": 116.4},
        },
    }


def complete_public_transport_state() -> TripState:
    return TripState(
        trip_id=uuid4(),
        origin=resolved_location("南京", "B000O1"),
        destination=resolved_location("北京", "B000D1"),
        return_destination=resolved_location("南京", "B000R1"),
        departure_date="2026-10-01",
        return_date="2026-10-03",
        accommodation=resolved_location("王府井附近", "B000H1"),
        places=[resolved_location("故宫博物院", "B000P1")],
        intercity_travel_mode=IntercityTravelMode.HIGH_SPEED_RAIL,
        local_travel_mode=TravelMode.PUBLIC_TRANSPORT,
    )


def test_assessment_reports_only_planning_fields_absent_from_empty_state() -> None:
    assessment = assess_trip_state(TripState(trip_id=uuid4()))

    assert assessment.missing_fields == [
        RequiredTripStateField.ORIGIN,
        RequiredTripStateField.DESTINATION,
        RequiredTripStateField.RETURN_DESTINATION,
        RequiredTripStateField.DEPARTURE_DATE,
        RequiredTripStateField.RETURN_DATE,
        RequiredTripStateField.ACCOMMODATION,
        RequiredTripStateField.PLACES,
        RequiredTripStateField.INTERCITY_TRAVEL_MODE,
        RequiredTripStateField.LOCAL_TRAVEL_MODE,
    ]
    assert assessment.pending_locations == []
    assert assessment.is_ready is False


def test_driving_state_requires_vehicle() -> None:
    state = TripState.model_validate(
        complete_public_transport_state().model_dump()
        | {"intercity_travel_mode": IntercityTravelMode.DRIVING}
    )

    assessment = assess_trip_state(state)

    assert assessment.missing_fields == [RequiredTripStateField.VEHICLE]
    assert assessment.is_ready is False


def test_public_transport_state_does_not_require_vehicle() -> None:
    assessment = assess_trip_state(complete_public_transport_state())

    assert assessment.missing_fields == []
    assert assessment.pending_locations == []
    assert assessment.is_ready is True


def test_assessment_reports_unresolved_and_ambiguous_locations_separately() -> None:
    state = TripState(
        trip_id=uuid4(),
        origin=resolved_location("南京", "B000O1"),
        destination={"query": "北京"},
        return_destination=resolved_location("南京", "B000R1"),
        departure_date="2026-10-01",
        return_date="2026-10-03",
        accommodation={
            "query": "万达广场",
            "resolution_status": LocationResolutionStatus.AMBIGUOUS,
            "candidates": [
                {
                    "poi_id": "B000H1",
                    "name": "北京万达广场",
                    "coordinate": {"latitude": 39.9, "longitude": 116.4},
                },
                {
                    "poi_id": "B000H2",
                    "name": "上海万达广场",
                    "coordinate": {"latitude": 31.2, "longitude": 121.5},
                },
            ],
        },
        places=[resolved_location("故宫博物院", "B000P1")],
        intercity_travel_mode=IntercityTravelMode.HIGH_SPEED_RAIL,
        local_travel_mode=TravelMode.PUBLIC_TRANSPORT,
    )

    assessment = assess_trip_state(state)

    assert assessment.missing_fields == []
    assert [(item.field, item.query, item.resolution_status) for item in assessment.pending_locations] == [
        (RequiredTripStateField.DESTINATION, "北京", LocationResolutionStatus.UNRESOLVED),
        (RequiredTripStateField.ACCOMMODATION, "万达广场", LocationResolutionStatus.AMBIGUOUS),
    ]
    assert assessment.is_ready is False


def test_driving_state_with_vehicle_is_ready_when_locations_are_resolved() -> None:
    state_data = complete_public_transport_state().model_dump()
    state_data.update(
        intercity_travel_mode=IntercityTravelMode.DRIVING,
        vehicle={"energy_type": VehicleEnergyType.ELECTRIC, "range_km": 500},
    )
    state = TripState.model_validate(state_data)

    assessment = assess_trip_state(state)

    assert assessment.is_ready is True
