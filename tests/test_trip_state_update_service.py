from uuid import uuid4

import pytest
from pydantic import ValidationError

from app.models.enums import IntercityTravelMode, TravelMode, VehicleEnergyType
from app.schemas.trip_state import LocationResolutionStatus, TripState, TripStatePatch
from app.schemas.trip_state_assessment import RequiredTripStateField
from app.services.trip_state_location_resolution_service import (
    LocationResolutionFailure,
    TripStateLocationResolutionResult,
)
from app.services.trip_state_update_service import TripStateUpdateService
from app.services.trip_state_extraction_service import (
    LocationConfirmationIntent,
    TripStateMessageUnderstanding,
)
from app.schemas.trip_state import TripStateLocationField


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


def complete_state(trip_id: object, **changes: object) -> TripState:
    state_data: dict[str, object] = {
        "trip_id": trip_id,
        "origin": resolved_location("南京", "B000O1"),
        "destination": resolved_location("北京", "B000D1"),
        "return_destination": resolved_location("南京", "B000R1"),
        "departure_date": "2026-10-01",
        "return_date": "2026-10-03",
        "accommodation": resolved_location("王府井附近", "B000H1"),
        "places": [resolved_location("故宫", "B000P1")],
        "intercity_travel_mode": IntercityTravelMode.HIGH_SPEED_RAIL,
        "local_travel_mode": TravelMode.PUBLIC_TRANSPORT,
    }
    state_data.update(changes)
    return TripState.model_validate(state_data)


class FakeExtractor:
    def __init__(self, result: TripStateMessageUnderstanding | Exception) -> None:
        self.result = result
        self.calls: list[tuple[TripState, str]] = []

    def extract(self, current_state: TripState, user_message: str) -> TripStateMessageUnderstanding:
        self.calls.append((current_state, user_message))
        if isinstance(self.result, Exception):
            raise self.result
        return self.result


class FakeLocationConfirmer:
    def __init__(self, result: TripState) -> None:
        self.result = result
        self.calls: list[tuple[TripState, object, str, int | None]] = []

    def apply(
        self, state: TripState, field: object, selected_poi_id: str, place_index: int | None = None
    ) -> TripState:
        self.calls.append((state, field, selected_poi_id, place_index))
        return self.result


class FakeLocationResolver:
    def __init__(self, result: TripStateLocationResolutionResult) -> None:
        self.result = result
        self.calls: list[TripState] = []

    def resolve(self, state: TripState) -> TripStateLocationResolutionResult:
        self.calls.append(state)
        return self.result


class FakeSession:
    def __init__(self) -> None:
        self.commit_calls = 0

    def commit(self) -> None:
        self.commit_calls += 1


class FakeTrip:
    start_date = None
    end_date = None


@pytest.fixture(autouse=True)
def _isolate_trip_date_projection(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        "app.services.trip_state_update_service.get_trip_by_id",
        lambda session, trip_id: FakeTrip(),
    )
    monkeypatch.setattr(
        "app.services.trip_state_update_service.sync_trip_dates_from_state",
        lambda session, trip_id, **dates: None,
    )


def test_update_extracts_merges_normalizes_and_saves_existing_state(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    trip_id = uuid4()
    existing_state = TripState(
        trip_id=trip_id,
        destination={"query": "北京"},
        accommodation={"query": "王府井附近"},
    )
    normalized_state = TripState(
        trip_id=trip_id,
        destination={
            "query": "北京",
            "resolution_status": "resolved",
            "resolved_location": {
                "poi_id": "B000D1",
                "name": "北京市",
                "coordinate": {"latitude": 39.9, "longitude": 116.4},
            },
        },
        accommodation={"query": "国贸附近"},
    )
    extractor = FakeExtractor(TripStateMessageUnderstanding(patch=TripStatePatch(accommodation={"query": "国贸附近"})))
    resolver = FakeLocationResolver(
        TripStateLocationResolutionResult(state=normalized_state, failures=[])
    )
    saved_states: list[TripState] = []
    monkeypatch.setattr(
        "app.services.trip_state_update_service.get_trip_state",
        lambda session, requested_trip_id: existing_state,
    )
    monkeypatch.setattr(
        "app.services.trip_state_update_service.save_trip_state",
        lambda session, state, **kwargs: saved_states.append(state) or state,
    )

    result = TripStateUpdateService(extractor, resolver).update(
        FakeSession(), trip_id, "酒店改到国贸附近"
    )

    assert extractor.calls == [(existing_state, "酒店改到国贸附近")]
    assert resolver.calls[0].accommodation is not None
    assert resolver.calls[0].accommodation.query == "国贸附近"
    assert result.state == normalized_state
    assert result.state.destination is not None
    assert result.state.destination.resolution_status is LocationResolutionStatus.RESOLVED
    assert result.assessment.missing_fields == [
        RequiredTripStateField.ORIGIN,
        RequiredTripStateField.RETURN_DESTINATION,
        RequiredTripStateField.DEPARTURE_DATE,
        RequiredTripStateField.RETURN_DATE,
        RequiredTripStateField.PLACES,
        RequiredTripStateField.INTERCITY_TRAVEL_MODE,
        RequiredTripStateField.LOCAL_TRAVEL_MODE,
    ]
    assert [item.query for item in result.assessment.pending_locations] == ["国贸附近"]
    assert saved_states == [normalized_state]


def test_first_update_saves_location_failures_with_the_original_unresolved_location(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    trip_id = uuid4()
    unresolved_state = TripState(trip_id=trip_id, destination={"query": "不存在的城市"})
    failure = LocationResolutionFailure(
        field="destination",
        query="不存在的城市",
        error_code="map_no_results",
    )
    extractor = FakeExtractor(TripStateMessageUnderstanding(patch=TripStatePatch(destination={"query": "不存在的城市"})))
    resolver = FakeLocationResolver(
        TripStateLocationResolutionResult(state=unresolved_state, failures=[failure])
    )
    saved_states: list[TripState] = []
    monkeypatch.setattr(
        "app.services.trip_state_update_service.get_trip_state",
        lambda session, requested_trip_id: None,
    )
    monkeypatch.setattr(
        "app.services.trip_state_update_service.save_trip_state",
        lambda session, state, **kwargs: saved_states.append(state) or state,
    )

    result = TripStateUpdateService(extractor, resolver).update(
        FakeSession(), trip_id, "去不存在的城市"
    )

    assert resolver.calls == [unresolved_state]
    assert result.state == unresolved_state
    assert result.location_failures == [failure]
    assert result.assessment.missing_fields == [
        RequiredTripStateField.ORIGIN,
        RequiredTripStateField.RETURN_DESTINATION,
        RequiredTripStateField.DEPARTURE_DATE,
        RequiredTripStateField.RETURN_DATE,
        RequiredTripStateField.ACCOMMODATION,
        RequiredTripStateField.PLACES,
        RequiredTripStateField.INTERCITY_TRAVEL_MODE,
        RequiredTripStateField.LOCAL_TRAVEL_MODE,
    ]
    assert [item.query for item in result.assessment.pending_locations] == ["不存在的城市"]
    assert saved_states == [unresolved_state]


def test_update_marks_a_complete_confirmed_state_ready(monkeypatch: pytest.MonkeyPatch) -> None:
    trip_id = uuid4()
    fully_populated_state = complete_state(trip_id)
    extractor = FakeExtractor(TripStateMessageUnderstanding())
    resolver = FakeLocationResolver(TripStateLocationResolutionResult(fully_populated_state, []))
    monkeypatch.setattr(
        "app.services.trip_state_update_service.get_trip_state",
        lambda session, requested_trip_id: fully_populated_state,
    )
    monkeypatch.setattr(
        "app.services.trip_state_update_service.save_trip_state",
        lambda session, state, **kwargs: state,
    )

    result = TripStateUpdateService(extractor, resolver).update(FakeSession(), trip_id, "继续")

    assert result.assessment.is_ready is True
    assert result.assessment.missing_fields == []
    assert result.assessment.pending_locations == []


def test_transport_change_clears_vehicle_then_resolves_and_saves_existing_state(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    trip_id = uuid4()
    existing_state = TripState(
        trip_id=trip_id,
        intercity_travel_mode=IntercityTravelMode.DRIVING,
        vehicle={"energy_type": VehicleEnergyType.ELECTRIC, "range_km": 500},
    )
    changed_state = TripState(
        trip_id=trip_id,
        intercity_travel_mode=IntercityTravelMode.HIGH_SPEED_RAIL,
    )
    extractor = FakeExtractor(
        TripStateMessageUnderstanding(
            patch=TripStatePatch(intercity_travel_mode=IntercityTravelMode.HIGH_SPEED_RAIL)
        )
    )
    resolver = FakeLocationResolver(TripStateLocationResolutionResult(changed_state, []))
    saved_states: list[TripState] = []
    monkeypatch.setattr(
        "app.services.trip_state_update_service.get_trip_state",
        lambda session, requested_trip_id: existing_state,
    )
    monkeypatch.setattr(
        "app.services.trip_state_update_service.save_trip_state",
        lambda session, state, **kwargs: saved_states.append(state) or state,
    )

    result = TripStateUpdateService(extractor, resolver).update(FakeSession(), trip_id, "改坐高铁")

    assert resolver.calls[0].intercity_travel_mode is IntercityTravelMode.HIGH_SPEED_RAIL
    assert resolver.calls[0].vehicle is None
    assert saved_states == [changed_state]
    assert result.state == changed_state
    assert existing_state.intercity_travel_mode is IntercityTravelMode.DRIVING
    assert existing_state.vehicle is not None


def test_update_confirms_an_existing_candidate_then_merges_other_explicit_changes(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    trip_id = uuid4()
    ambiguous_state = TripState(
        trip_id=trip_id,
        destination={
            "query": "万达广场",
            "resolution_status": "ambiguous",
            "candidates": [
                {"poi_id": "B1", "name": "北京万达", "coordinate": {"latitude": 39.9, "longitude": 116.4}},
                {"poi_id": "B2", "name": "上海万达", "coordinate": {"latitude": 31.2, "longitude": 121.5}},
            ],
        },
    )
    confirmed_state = TripState(
        trip_id=trip_id,
        destination={
            "query": "万达广场",
            "resolution_status": "resolved",
            "resolved_location": {"poi_id": "B1", "name": "北京万达", "coordinate": {"latitude": 39.9, "longitude": 116.4}},
        },
        intercity_travel_mode=IntercityTravelMode.HIGH_SPEED_RAIL,
    )
    extractor = FakeExtractor(
        TripStateMessageUnderstanding(
            patch=TripStatePatch(intercity_travel_mode=IntercityTravelMode.HIGH_SPEED_RAIL),
            location_confirmation=LocationConfirmationIntent(
                field=TripStateLocationField.DESTINATION, selected_poi_id="B1"
            ),
        )
    )
    confirmer = FakeLocationConfirmer(confirmed_state)
    resolver = FakeLocationResolver(TripStateLocationResolutionResult(confirmed_state, []))
    monkeypatch.setattr("app.services.trip_state_update_service.get_trip_state", lambda session, requested_trip_id: ambiguous_state)
    monkeypatch.setattr("app.services.trip_state_update_service.save_trip_state", lambda session, state, **kwargs: state)

    result = TripStateUpdateService(extractor, resolver, confirmer).update(FakeSession(), trip_id, "选北京那个，坐公交")

    assert confirmer.calls[0][1:] == (TripStateLocationField.DESTINATION, "B1", None)
    assert resolver.calls == [confirmed_state]
    assert result.state == confirmed_state


def test_extraction_error_does_not_resolve_or_save_state(monkeypatch: pytest.MonkeyPatch) -> None:
    trip_id = uuid4()
    extractor = FakeExtractor(RuntimeError("provider failed"))
    empty_state = TripState(trip_id=trip_id)
    resolver = FakeLocationResolver(TripStateLocationResolutionResult(empty_state, []))
    saved_states: list[TripState] = []
    monkeypatch.setattr(
        "app.services.trip_state_update_service.get_trip_state",
        lambda session, requested_trip_id: None,
    )
    monkeypatch.setattr(
        "app.services.trip_state_update_service.save_trip_state",
        lambda session, state, **kwargs: saved_states.append(state) or state,
    )

    with pytest.raises(RuntimeError, match="provider failed"):
        TripStateUpdateService(extractor, resolver).update(FakeSession(), trip_id, "去北京")

    assert resolver.calls == []
    assert saved_states == []
