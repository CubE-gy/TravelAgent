from collections.abc import Generator
from uuid import UUID, uuid4

import pytest
from fastapi.testclient import TestClient

from app.api.trips import get_trip_state_location_confirmation_service
from app.db.session import get_db
from app.main import app
from app.schemas.map import ResolvedLocation
from app.schemas.trip_state import (
    LocationIntent,
    LocationResolutionStatus,
    TripState,
    TripStateLocationField,
)
from app.schemas.trip_state_assessment import TripStateAssessment
from app.services.map_errors import MapUpstreamError


class FakeConfirmationService:
    def __init__(self, result: tuple[TripState, TripStateAssessment] | Exception) -> None:
        self._result = result
        self.calls: list[tuple[object, UUID, object, str, int | None]] = []

    def confirm(
        self,
        session: object,
        trip_id: UUID,
        *,
        field: object,
        selected_poi_id: str,
        place_index: int | None,
    ) -> tuple[TripState, TripStateAssessment]:
        self.calls.append((session, trip_id, field, selected_poi_id, place_index))
        if isinstance(self._result, Exception):
            raise self._result
        return self._result


@pytest.fixture
def client() -> Generator[TestClient, None, None]:
    def override_db() -> Generator[object, None, None]:
        yield object()

    app.dependency_overrides[get_db] = override_db
    try:
        yield TestClient(app)
    finally:
        app.dependency_overrides.clear()


def _result(trip_id: UUID) -> tuple[TripState, TripStateAssessment]:
    state = TripState(
        trip_id=trip_id,
        destination=LocationIntent(
            query="万达广场",
            resolution_status=LocationResolutionStatus.RESOLVED,
            resolved_location=ResolvedLocation(
                poi_id="B000A2",
                name="上海万达广场",
                coordinate={"latitude": 31.2, "longitude": 121.5},
            ),
        ),
    )
    return state, TripStateAssessment(
        missing_fields=[], pending_locations=[], is_ready=True
    )


def _override(service: FakeConfirmationService) -> None:
    app.dependency_overrides[get_trip_state_location_confirmation_service] = lambda: service


def test_confirm_trip_location_returns_confirmed_state(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    trip_id = uuid4()
    service = FakeConfirmationService(_result(trip_id))
    _override(service)
    monkeypatch.setattr("app.api.trips.get_trip_by_id", lambda session, identifier: object())

    response = client.post(
        f"/trips/{trip_id}/locations/confirm",
        json={"field": "destination", "poi_id": " B000A2 "},
    )

    assert response.status_code == 200
    assert response.json()["state"]["destination"]["resolution_status"] == "resolved"
    assert response.json()["state"]["destination"]["resolved_location"]["poi_id"] == "B000A2"
    assert service.calls[0][1:] == (
        trip_id,
        TripStateLocationField.DESTINATION,
        "B000A2",
        None,
    )


def test_confirm_trip_location_requires_valid_places_index(client: TestClient) -> None:
    response = client.post(
        f"/trips/{uuid4()}/locations/confirm",
        json={"field": "places", "poi_id": "B000A2"},
    )

    assert response.status_code == 422


def test_confirm_trip_location_stops_before_confirmation_for_unknown_trip(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    service = FakeConfirmationService(_result(uuid4()))
    _override(service)
    monkeypatch.setattr("app.api.trips.get_trip_by_id", lambda session, identifier: None)

    response = client.post(
        f"/trips/{uuid4()}/locations/confirm",
        json={"field": "destination", "poi_id": "B000A2"},
    )

    assert response.status_code == 404
    assert service.calls == []


def test_confirm_trip_location_converts_invalid_selection_to_422(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    trip_id = uuid4()
    service = FakeConfirmationService(
        ValueError("selected_poi_id must belong to the location candidates")
    )
    _override(service)
    monkeypatch.setattr("app.api.trips.get_trip_by_id", lambda session, identifier: object())

    response = client.post(
        f"/trips/{trip_id}/locations/confirm",
        json={"field": "destination", "poi_id": "B000MISSING"},
    )

    assert response.status_code == 422
    assert response.json() == {
        "detail": "selected_poi_id must belong to the location candidates"
    }


def test_confirm_trip_location_hides_map_failure_details(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    trip_id = uuid4()
    service = FakeConfirmationService(MapUpstreamError())
    _override(service)
    monkeypatch.setattr("app.api.trips.get_trip_by_id", lambda session, identifier: object())

    response = client.post(
        f"/trips/{trip_id}/locations/confirm",
        json={"field": "destination", "poi_id": "B000A2"},
    )

    assert response.status_code == 502
    assert response.json() == {"detail": "Location confirmation could not be completed"}
