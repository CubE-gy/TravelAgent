from uuid import uuid4

import pytest

from app.schemas.map import PoiCandidate, ResolvedLocation
from app.schemas.trip_state import (
    LocationIntent,
    LocationResolutionStatus,
    TripState,
    TripStateLocationField,
)
from app.services.trip_state_location_confirmation_service import (
    TripStateLocationConfirmationService,
)


class FakeMapService:
    def __init__(self, resolved_location: ResolvedLocation) -> None:
        self.resolved_location = resolved_location
        self.resolve_calls: list[str] = []

    def search_pois(self, keyword: str, *, region: str | None = None) -> list[PoiCandidate]:
        raise AssertionError("confirmation must not search again")

    def resolve_location(self, poi_id: str) -> ResolvedLocation:
        self.resolve_calls.append(poi_id)
        return self.resolved_location


class FakeSession:
    def __init__(self) -> None:
        self.commit_calls = 0
        self.rollback_calls = 0

    def commit(self) -> None:
        self.commit_calls += 1

    def rollback(self) -> None:
        self.rollback_calls += 1


def _candidate(poi_id: str, name: str) -> PoiCandidate:
    return PoiCandidate(
        poi_id=poi_id,
        name=name,
        coordinate={"latitude": 39.9, "longitude": 116.4},
    )


def _ambiguous_state() -> TripState:
    return TripState(
        trip_id=uuid4(),
        destination=LocationIntent(
            query="万达广场",
            resolution_status=LocationResolutionStatus.AMBIGUOUS,
            candidates=[_candidate("B000A1", "北京万达广场"), _candidate("B000A2", "上海万达广场")],
        ),
    )


def test_confirmation_resolves_and_persists_only_selected_existing_candidate(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    state = _ambiguous_state()
    map_service = FakeMapService(
        ResolvedLocation(
            poi_id="B000A2",
            name="上海万达广场",
            address="上海市杨浦区",
            coordinate={"latitude": 31.2, "longitude": 121.5},
        )
    )
    saved_states: list[TripState] = []
    monkeypatch.setattr(
        "app.services.trip_state_location_confirmation_service.get_trip_state",
        lambda session, trip_id: state,
    )
    monkeypatch.setattr(
        "app.services.trip_state_location_confirmation_service.save_trip_state",
        lambda session, saved_state, **kwargs: saved_states.append(saved_state) or saved_state,
    )

    session = FakeSession()
    persisted, assessment = TripStateLocationConfirmationService(map_service).confirm(
        session,
        state.trip_id,
        field=TripStateLocationField.DESTINATION,
        selected_poi_id="B000A2",
        expected_revision=0,
    )

    assert persisted.destination is not None
    assert persisted.destination.resolution_status is LocationResolutionStatus.RESOLVED
    assert persisted.destination.resolved_location is not None
    assert persisted.destination.resolved_location.poi_id == "B000A2"
    assert assessment.pending_locations == []
    assert map_service.resolve_calls == ["B000A2"]
    assert saved_states == [persisted]
    assert session.commit_calls == 1
    assert state.destination is not None
    assert state.destination.resolution_status is LocationResolutionStatus.AMBIGUOUS


def test_confirmation_returns_the_incremented_persisted_revision(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    state = _ambiguous_state().model_copy(update={"revision": 1})
    map_service = FakeMapService(
        ResolvedLocation(
            poi_id="B000A2",
            name="上海万达广场",
            coordinate={"latitude": 31.2, "longitude": 121.5},
        )
    )
    monkeypatch.setattr(
        "app.services.trip_state_location_confirmation_service.get_trip_state",
        lambda session, trip_id: state,
    )
    monkeypatch.setattr(
        "app.services.trip_state_location_confirmation_service.save_trip_state",
        lambda session, saved_state, **kwargs: saved_state.model_copy(update={"revision": 2}),
    )

    persisted, _ = TripStateLocationConfirmationService(map_service).confirm(
        FakeSession(),
        state.trip_id,
        field=TripStateLocationField.DESTINATION,
        selected_poi_id="B000A2",
        expected_revision=1,
    )

    assert persisted.revision == 2


def test_confirmation_rejects_candidate_outside_existing_candidates_without_saving(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    state = _ambiguous_state()
    map_service = FakeMapService(
        ResolvedLocation(
            poi_id="B000A2",
            name="上海万达广场",
            coordinate={"latitude": 31.2, "longitude": 121.5},
        )
    )
    monkeypatch.setattr(
        "app.services.trip_state_location_confirmation_service.get_trip_state",
        lambda session, trip_id: state,
    )
    monkeypatch.setattr(
        "app.services.trip_state_location_confirmation_service.save_trip_state",
        lambda session, saved_state: pytest.fail("must not save an invalid selection"),
    )

    session = FakeSession()
    with pytest.raises(ValueError, match="must belong"):
        TripStateLocationConfirmationService(map_service).confirm(
            session,
            state.trip_id,
            field=TripStateLocationField.DESTINATION,
            selected_poi_id="B000MISSING",
            expected_revision=0,
        )

    assert map_service.resolve_calls == []
    assert session.rollback_calls == 1


def test_confirmation_rejects_invalid_place_index_without_map_lookup(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    state = _ambiguous_state()
    map_service = FakeMapService(
        ResolvedLocation(
            poi_id="B000A2",
            name="上海万达广场",
            coordinate={"latitude": 31.2, "longitude": 121.5},
        )
    )
    monkeypatch.setattr(
        "app.services.trip_state_location_confirmation_service.get_trip_state",
        lambda session, trip_id: state,
    )

    session = FakeSession()
    with pytest.raises(ValueError, match="outside"):
        TripStateLocationConfirmationService(map_service).confirm(
            session,
            state.trip_id,
            field=TripStateLocationField.PLACES,
            selected_poi_id="B000A2",
            place_index=0,
            expected_revision=0,
        )

    assert map_service.resolve_calls == []
    assert session.rollback_calls == 1
