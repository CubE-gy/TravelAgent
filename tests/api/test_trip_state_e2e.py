"""Stage 2 end-to-end coverage using the real API and PostgreSQL persistence."""

from collections.abc import Generator
from pathlib import Path
from uuid import UUID

import pytest
from alembic import command
from alembic.config import Config
from fastapi.testclient import TestClient
from sqlalchemy import text
from sqlalchemy.orm import Session

from app.core.config import Settings
from app.db.session import create_database_engine, get_db
from app.main import app
from app.repositories.trip import get_trip_by_id
from app.repositories.trip_state import get_trip_state
from app.schemas.map import PoiCandidate, ResolvedCity, ResolvedLocation
from app.schemas.trip_state import TripStatePatch
from app.schemas.trip_state_clarification import (
    ClarificationQuestion,
    TripStateClarification,
)
from app.services.trip_state_extraction_service import TripStateMessageUnderstanding
from app.services.trip_agent_reply_service import AgentFinalReply
from app.services.llm_provider import LlmUpstreamError


PROJECT_ROOT = Path(__file__).resolve().parents[2]


def _upgrade_test_database(database_url: str) -> None:
    config = Config(str(PROJECT_ROOT / "alembic.ini"))
    config.set_main_option("sqlalchemy.url", database_url)
    command.upgrade(config, "head")


class FakeLlmProvider:
    """Return the two scripted extraction and clarification results for this journey."""

    def __init__(self) -> None:
        self._extractions = iter(
            [
                TripStateMessageUnderstanding(
                    patch=TripStatePatch(destination={"query": "北京"})
                ),
                TripStateMessageUnderstanding(
                    patch=TripStatePatch(accommodation={"query": "王府井附近"})
                ),
            ]
        )
        self._clarifications = iter(
            [
                TripStateClarification(
                    questions=[
                        ClarificationQuestion(
                            topic_id="missing:origin", question="从哪里出发？"
                        ),
                        ClarificationQuestion(
                            topic_id="missing:return_destination", question="最终返回哪里？"
                        ),
                        ClarificationQuestion(
                            topic_id="missing:accommodation", question="住宿在哪里？"
                        ),
                        ClarificationQuestion(
                            topic_id="missing:places", question="想去哪些地点？"
                        ),
                        ClarificationQuestion(
                            topic_id="missing:intercity_travel_mode", question="城际怎么去？"
                        ),
                        ClarificationQuestion(
                            topic_id="missing:local_travel_mode", question="当地怎么出行？"
                        ),
                    ]
                ),
                TripStateClarification(
                    questions=[
                        ClarificationQuestion(
                            topic_id="missing:origin", question="从哪里出发？"
                        ),
                        ClarificationQuestion(
                            topic_id="missing:return_destination", question="最终返回哪里？"
                        ),
                        ClarificationQuestion(
                            topic_id="missing:places", question="想去哪些地点？"
                        ),
                        ClarificationQuestion(
                            topic_id="missing:intercity_travel_mode", question="城际怎么去？"
                        ),
                        ClarificationQuestion(
                            topic_id="missing:local_travel_mode", question="当地怎么出行？"
                        ),
                    ]
                ),
            ]
        )

    def generate_structured(self, messages: list[object], response_model: type[object]) -> object:
        if response_model is TripStateMessageUnderstanding:
            return next(self._extractions)
        if response_model is TripStateClarification:
            return next(self._clarifications)
        if response_model is AgentFinalReply:
            return AgentFinalReply(message="已更新行程。")
        raise AssertionError(f"unexpected response model: {response_model}")


class FakeAmapApiService:
    """Provide deterministic Stage 1 facts without network access."""

    def __init__(self, api_key: object) -> None:
        self.api_key = api_key

    def resolve_city(self, query: str) -> ResolvedCity | None:
        if query != "北京":
            return None
        return ResolvedCity(name="北京市", city_code="010", adcode="110000",
                            center={"latitude": 39.9, "longitude": 116.4})

    def search_pois(self, keyword: str, *, region: str | None = None) -> list[PoiCandidate]:
        poi_id = {"北京": "CITY_BEIJING", "王府井附近": "HOTEL_WANGFUJING"}[keyword]
        return [
            PoiCandidate(
                poi_id=poi_id,
                name=keyword,
                coordinate={"latitude": 39.9, "longitude": 116.4},
            )
        ]

    def resolve_location(self, poi_id: str) -> ResolvedLocation:
        return ResolvedLocation(
            poi_id=poi_id,
            name={"CITY_BEIJING": "北京市", "HOTEL_WANGFUJING": "王府井"}[poi_id],
            coordinate={"latitude": 39.9, "longitude": 116.4},
        )


@pytest.mark.integration
def test_two_messages_restore_and_update_the_same_persisted_trip_state(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    database_url = str(Settings().test_database_url)
    _upgrade_test_database(database_url)
    engine = create_database_engine(database_url)
    provider = FakeLlmProvider()
    trip_id: UUID | None = None

    def override_get_db() -> Generator[Session, None, None]:
        with Session(engine) as session:
            yield session

    app.dependency_overrides[get_db] = override_get_db
    monkeypatch.setattr("app.api.trips.create_llm_provider", lambda settings: provider)
    monkeypatch.setattr("app.api.trips.AmapApiService", FakeAmapApiService)
    try:
        with TestClient(app) as client:
            create_response = client.post(
                "/trips",
                json={
                    "name": "北京旅行",
                    "start_date": "2026-10-01",
                    "end_date": "2026-10-03",
                },
            )
            assert create_response.status_code == 201
            trip_id = UUID(create_response.json()["id"])

            first_response = client.post(
                f"/trips/{trip_id}/messages",
                json={"message": "我要去北京", "expected_revision": 0},
            )
            second_response = client.post(
                f"/trips/{trip_id}/messages",
                json={"message": "住王府井附近", "expected_revision": 1},
            )

        assert first_response.status_code == 200
        assert first_response.json()["state"]["destination"]["resolution_status"] == "resolved"
        assert first_response.json()["clarification"]["questions"] == []
        assert second_response.status_code == 200
        assert second_response.json()["state"]["destination"]["resolved_city"]["name"] == "北京市"
        assert second_response.json()["state"]["accommodation"]["resolved_location"]["name"] == "王府井"
        assert second_response.json()["clarification"]["questions"] == []

        with Session(engine) as session:
            persisted_state = get_trip_state(session, trip_id)

        assert persisted_state is not None
        assert persisted_state.destination is not None
        assert persisted_state.destination.resolved_city is not None
        assert persisted_state.destination.resolved_city.name == "北京市"
        assert persisted_state.accommodation is not None
        assert persisted_state.accommodation.resolved_location is not None
        assert persisted_state.accommodation.resolved_location.name == "王府井"
        assert persisted_state.departure_date.isoformat() == "2026-10-01"
        assert persisted_state.return_date.isoformat() == "2026-10-03"

        with Session(engine) as session:
            persisted_trip = get_trip_by_id(session, trip_id)

        assert persisted_trip is not None
        assert persisted_trip.start_date.isoformat() == "2026-10-01"
        assert persisted_trip.end_date.isoformat() == "2026-10-03"
    finally:
        app.dependency_overrides.clear()
        if trip_id is not None:
            with engine.begin() as connection:
                connection.execute(
                    text("DELETE FROM trip_conversation_turns WHERE trip_id = :trip_id"),
                    {"trip_id": trip_id},
                )
                connection.execute(
                    text("DELETE FROM trip_states WHERE trip_id = :trip_id"),
                    {"trip_id": trip_id},
                )
                connection.execute(
                    text("DELETE FROM trips WHERE id = :trip_id"), {"trip_id": trip_id}
                )
        engine.dispose()


@pytest.mark.integration
def test_first_natural_language_message_creates_trip_and_state_together(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    database_url = str(Settings().test_database_url)
    _upgrade_test_database(database_url)
    engine = create_database_engine(database_url)

    class FirstMessageProvider:
        def generate_structured(self, messages: list[object], response_model: type[object]) -> object:
            del messages
            if response_model is TripStateMessageUnderstanding:
                return TripStateMessageUnderstanding(
                    patch=TripStatePatch(
                        origin={"query": "南京新街口"},
                        destination={"query": "北京"},
                        return_destination={"query": "南京新街口"},
                        departure_date="2026-10-01",
                        return_date="2026-10-03",
                        accommodation={"query": "王府井附近"},
                        places=[{"query": "故宫"}],
                        intercity_travel_mode="high_speed_rail",
                        local_travel_mode="public_transport",
                    )
                )
            if response_model is TripStateClarification:
                return TripStateClarification()
            if response_model is AgentFinalReply:
                return AgentFinalReply(message="已根据地图结果更新行程。")
            raise AssertionError(f"unexpected response model: {response_model}")

    class FirstMessageMapService:
        def __init__(self, api_key: object) -> None:
            del api_key

        def resolve_city(self, query: str) -> None:
            return None

        def search_pois(self, keyword: str, *, region: str | None = None) -> list[PoiCandidate]:
            del region
            return [
                PoiCandidate(
                    poi_id=f"POI_{keyword}",
                    name=keyword,
                    coordinate={"latitude": 39.9, "longitude": 116.4},
                )
            ]

        def resolve_location(self, poi_id: str) -> ResolvedLocation:
            return ResolvedLocation(
                poi_id=poi_id,
                name=poi_id.removeprefix("POI_"),
                coordinate={"latitude": 39.9, "longitude": 116.4},
            )

    def override_get_db() -> Generator[Session, None, None]:
        with Session(engine) as session:
            yield session

    app.dependency_overrides[get_db] = override_get_db
    monkeypatch.setattr("app.api.trips.create_llm_provider", lambda settings: FirstMessageProvider())
    monkeypatch.setattr("app.api.trips.AmapApiService", FirstMessageMapService)
    trip_id: UUID | None = None
    try:
        with TestClient(app) as client:
            response = client.post(
                "/trips/conversations",
                json={"message": "从南京新街口去北京，住王府井，想去故宫"},
            )

        assert response.status_code == 201
        payload = response.json()
        trip_id = UUID(payload["trip"]["id"])
        assert payload["trip"]["name"] is None
        assert payload["trip"]["start_date"] == "2026-10-01"
        assert payload["trip"]["end_date"] == "2026-10-03"
        assert payload["state"]["origin"]["resolution_status"] == "resolved"
        assert payload["state"]["return_destination"]["resolution_status"] == "resolved"
        assert payload["assessment"]["is_ready"] is True

        with Session(engine) as session:
            persisted_state = get_trip_state(session, trip_id)

        assert persisted_state is not None
        assert persisted_state.departure_date.isoformat() == "2026-10-01"

        with Session(engine) as session:
            persisted_trip = get_trip_by_id(session, trip_id)

        assert persisted_trip is not None
        assert persisted_trip.start_date.isoformat() == "2026-10-01"
        assert persisted_trip.end_date.isoformat() == "2026-10-03"
    finally:
        app.dependency_overrides.clear()
        if trip_id is not None:
            with engine.begin() as connection:
                connection.execute(
                    text("DELETE FROM trip_conversation_turns WHERE trip_id = :trip_id"),
                    {"trip_id": trip_id},
                )
                connection.execute(
                    text("DELETE FROM trip_states WHERE trip_id = :trip_id"),
                    {"trip_id": trip_id},
                )
                connection.execute(
                    text("DELETE FROM trips WHERE id = :trip_id"), {"trip_id": trip_id})
        engine.dispose()


@pytest.mark.integration
def test_failed_first_natural_language_message_leaves_no_trip(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    database_url = str(Settings().test_database_url)
    _upgrade_test_database(database_url)
    engine = create_database_engine(database_url)

    class FailingProvider:
        def generate_structured(self, messages: list[object], response_model: type[object]) -> object:
            del messages, response_model
            raise LlmUpstreamError("provider unavailable")

    def override_get_db() -> Generator[Session, None, None]:
        with Session(engine) as session:
            yield session

    app.dependency_overrides[get_db] = override_get_db
    monkeypatch.setattr("app.api.trips.create_llm_provider", lambda settings: FailingProvider())
    try:
        with engine.connect() as connection:
            count_before = connection.execute(text("SELECT count(*) FROM trips")).scalar_one()

        with TestClient(app) as client:
            response = client.post("/trips/conversations", json={"message": "我要去北京"})

        with engine.connect() as connection:
            count_after = connection.execute(text("SELECT count(*) FROM trips")).scalar_one()

        assert response.status_code == 502
        assert count_after == count_before
    finally:
        app.dependency_overrides.clear()
        engine.dispose()


@pytest.mark.integration
def test_failed_extraction_rolls_back_an_existing_trip_state_update(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    database_url = str(Settings().test_database_url)
    _upgrade_test_database(database_url)
    engine = create_database_engine(database_url)

    class FailingExtractionProvider:
        def generate_structured(self, messages: list[object], response_model: type[object]) -> object:
            del messages, response_model
            raise LlmUpstreamError("provider unavailable")

    def override_get_db() -> Generator[Session, None, None]:
        with Session(engine) as session:
            yield session

    app.dependency_overrides[get_db] = override_get_db
    monkeypatch.setattr(
        "app.api.trips.create_llm_provider",
        lambda settings: FailingExtractionProvider(),
    )
    trip_id: UUID | None = None
    try:
        with TestClient(app) as client:
            create_response = client.post(
                "/trips",
                json={
                    "name": "北京旅行",
                    "start_date": "2026-10-01",
                    "end_date": "2026-10-03",
                },
            )
            assert create_response.status_code == 201
            trip_id = UUID(create_response.json()["id"])

            response = client.post(
                f"/trips/{trip_id}/messages",
                json={"message": "我要去北京", "expected_revision": 0},
            )

        assert response.status_code == 502
        with Session(engine) as session:
            persisted_state = get_trip_state(session, trip_id)
            persisted_trip = get_trip_by_id(session, trip_id)

        assert persisted_state is None
        assert persisted_trip is not None
        assert persisted_trip.start_date.isoformat() == "2026-10-01"
        assert persisted_trip.end_date.isoformat() == "2026-10-03"
    finally:
        app.dependency_overrides.clear()
        if trip_id is not None:
            with engine.begin() as connection:
                connection.execute(
                    text("DELETE FROM trip_conversation_turns WHERE trip_id = :trip_id"),
                    {"trip_id": trip_id},
                )
                connection.execute(
                    text("DELETE FROM trip_states WHERE trip_id = :trip_id"),
                    {"trip_id": trip_id},
                )
                connection.execute(
                    text("DELETE FROM trips WHERE id = :trip_id"), {"trip_id": trip_id}
                )
        engine.dispose()
