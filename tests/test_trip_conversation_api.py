from collections.abc import Generator
from datetime import datetime, timezone
from uuid import UUID, uuid4

import pytest
from fastapi.testclient import TestClient

from app.api.trips import get_trip_state_conversation_service
from app.db.session import get_db
from app.main import app
from app.schemas.trip_state import TripState
from app.schemas.trip_state_assessment import TripStateAssessment
from app.schemas.trip_state_clarification import TripStateClarification
from app.services.llm_provider import LlmConfigurationError, LlmUpstreamError
from app.services.trip_state_conversation_service import TripStateConversationResult
from app.services.trip_state_location_resolution_service import LocationResolutionFailure


class FakeConversationService:
    def __init__(self, result: TripStateConversationResult | Exception) -> None:
        self._result = result
        self.calls: list[tuple[object, UUID, str]] = []

    def handle(
        self, session: object, trip_id: UUID, user_message: str, *, commit: bool = True
    ) -> TripStateConversationResult:
        self.calls.append((session, trip_id, user_message, commit))
        if isinstance(self._result, Exception):
            raise self._result
        return self._result


class FakeSession:
    def __init__(self) -> None:
        self.rollback_calls = 0
        self.commit_calls = 0
        self.refreshed: list[object] = []

    def rollback(self) -> None:
        self.rollback_calls += 1

    def commit(self) -> None:
        self.commit_calls += 1

    def refresh(self, value: object) -> None:
        self.refreshed.append(value)


class FakeTrip:
    def __init__(self, trip_id: UUID) -> None:
        self.id = trip_id
        self.name = None
        self.start_date = None
        self.end_date = None
        self.created_at = datetime.now(timezone.utc)
        self.updated_at = self.created_at


@pytest.fixture
def client() -> Generator[TestClient, None, None]:
    def override_db() -> Generator[FakeSession, None, None]:
        yield FakeSession()

    app.dependency_overrides[get_db] = override_db
    try:
        yield TestClient(app)
    finally:
        app.dependency_overrides.clear()


def _result(
    trip_id: UUID, *, failure_field: str = "destination"
) -> TripStateConversationResult:
    state = TripState(trip_id=trip_id)
    return TripStateConversationResult(
        state=state,
        location_failures=[
            LocationResolutionFailure(
                field=failure_field,
                query="北京",
                error_code="upstream_error",
            )
        ],
        assessment=TripStateAssessment(
            missing_fields=[], pending_locations=[], is_ready=True
        ),
        clarification=TripStateClarification(),
    )


def _override_conversation(service: FakeConversationService) -> None:
    app.dependency_overrides[get_trip_state_conversation_service] = lambda: service


def test_handle_trip_message_returns_state_and_next_questions(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    trip_id = uuid4()
    service = FakeConversationService(_result(trip_id))
    _override_conversation(service)
    monkeypatch.setattr("app.api.trips.get_trip_by_id", lambda session, identifier: object())

    response = client.post(f"/trips/{trip_id}/messages", json={"message": "  酒店改到国贸附近  "})

    assert response.status_code == 200
    assert response.json() == {
        "state": {
            "trip_id": str(trip_id),
            "origin": None,
            "destination": None,
            "return_destination": None,
            "departure_date": None,
            "return_date": None,
            "accommodation": None,
            "places": [],
            "intercity_travel_mode": None,
            "local_travel_mode": None,
            "vehicle": None,
        },
        "location_failures": [
            {
                "field": "destination",
                "query": "北京",
                "error_code": "upstream_error",
                "place_index": None,
            }
        ],
        "assessment": {"missing_fields": [], "pending_locations": [], "is_ready": True},
        "clarification": {"questions": []},
    }
    assert len(service.calls) == 1
    assert service.calls[0][1:] == (trip_id, "酒店改到国贸附近", True)


@pytest.mark.parametrize("message", ["", "   "])
def test_handle_trip_message_rejects_empty_message(
    client: TestClient, monkeypatch: pytest.MonkeyPatch, message: str
) -> None:
    trip_id = uuid4()
    service = FakeConversationService(_result(trip_id))
    _override_conversation(service)
    monkeypatch.setattr("app.api.trips.get_trip_by_id", lambda session, identifier: object())

    response = client.post(f"/trips/{trip_id}/messages", json={"message": message})

    assert response.status_code == 422
    assert service.calls == []


def test_first_message_creates_trip_and_persists_conversation_atomically(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    trip_id = uuid4()
    trip = FakeTrip(trip_id)
    service = FakeConversationService(_result(trip_id))
    _override_conversation(service)
    monkeypatch.setattr("app.api.trips.create_empty_trip", lambda session: trip)

    response = client.post("/trips/conversations", json={"message": "我要去北京"})

    assert response.status_code == 201
    assert response.json()["trip"]["id"] == str(trip_id)
    assert response.json()["trip"]["name"] is None
    assert service.calls[0][1:] == (trip_id, "我要去北京", False)


def test_first_message_returns_origin_location_failures_without_server_error(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    trip_id = uuid4()
    service = FakeConversationService(_result(trip_id, failure_field="origin"))
    _override_conversation(service)
    monkeypatch.setattr("app.api.trips.create_empty_trip", lambda session: FakeTrip(trip_id))

    response = client.post("/trips/conversations", json={"message": "我要去北京"})

    assert response.status_code == 201
    assert response.json()["location_failures"][0]["field"] == "origin"


def test_first_message_rolls_back_empty_trip_when_conversation_fails(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    trip = FakeTrip(uuid4())
    service = FakeConversationService(LlmUpstreamError("provider failed"))
    _override_conversation(service)
    monkeypatch.setattr("app.api.trips.create_empty_trip", lambda session: trip)

    response = client.post("/trips/conversations", json={"message": "我要去北京"})

    assert response.status_code == 502
    assert response.json() == {"detail": "Trip conversation could not be processed"}


def test_handle_trip_message_rejects_unknown_trip_before_conversation(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    service = FakeConversationService(_result(uuid4()))
    _override_conversation(service)
    monkeypatch.setattr("app.api.trips.get_trip_by_id", lambda session, identifier: None)

    response = client.post(f"/trips/{uuid4()}/messages", json={"message": "去北京"})

    assert response.status_code == 404
    assert service.calls == []


def test_handle_trip_message_converts_invalid_state_update_to_422(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    trip_id = uuid4()
    service = FakeConversationService(ValueError("vehicle conflicts with transport mode"))
    _override_conversation(service)
    monkeypatch.setattr("app.api.trips.get_trip_by_id", lambda session, identifier: object())

    response = client.post(f"/trips/{trip_id}/messages", json={"message": "改坐公共交通"})

    assert response.status_code == 422
    assert response.json() == {"detail": "Trip conversation update is invalid"}


@pytest.mark.parametrize(
    ("error", "expected_status", "expected_detail"),
    [
        (LlmUpstreamError("provider message"), 502, "Trip conversation could not be processed"),
        (
            LlmConfigurationError("missing key"),
            503,
            "Trip conversation service is unavailable",
        ),
    ],
)
def test_handle_trip_message_converts_provider_errors_without_leaking_details(
    client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
    error: Exception,
    expected_status: int,
    expected_detail: str,
) -> None:
    trip_id = uuid4()
    service = FakeConversationService(error)
    _override_conversation(service)
    monkeypatch.setattr("app.api.trips.get_trip_by_id", lambda session, identifier: object())

    response = client.post(f"/trips/{trip_id}/messages", json={"message": "去北京"})

    assert response.status_code == expected_status
    assert response.json() == {"detail": expected_detail}


@pytest.mark.parametrize("path", ["/trips/conversations", f"/trips/{uuid4()}/messages"])
def test_conversation_dependency_converts_llm_configuration_errors_to_503(
    client: TestClient, monkeypatch: pytest.MonkeyPatch, path: str
) -> None:
    def raise_configuration_error(*args: object, **kwargs: object) -> object:
        del args, kwargs
        raise LlmConfigurationError("missing LLM_API_KEY for secret-model")

    monkeypatch.setattr("app.api.trips.create_llm_provider", raise_configuration_error)

    response = client.post(path, json={"message": "我要去北京"})

    assert response.status_code == 503
    assert response.json() == {"detail": "Trip conversation service is unavailable"}
