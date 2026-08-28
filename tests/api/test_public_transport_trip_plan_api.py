from collections.abc import Generator
from pathlib import Path
from uuid import UUID, uuid4

import pytest
from alembic import command
from alembic.config import Config
from fastapi.testclient import TestClient
from sqlalchemy import text
from sqlalchemy.orm import Session

from app.api.trips import get_public_transport_trip_planning_service
from app.repositories.trip_plan import TripPlanStateRevisionConflictError
from app.core.config import Settings
from app.db.session import create_database_engine
from app.db.session import get_db
from app.main import app
from app.models.enums import RouteSegmentMode, TravelMode
from app.schemas.map import GeoPoint, ResolvedLocation, Route, RouteSegment
from app.schemas.trip_public_transport_plan import (
    PublicTransportTripPlan,
    PublicTransportTripPlanLeg,
    TripRouteFactSource,
    TripRouteLegKind,
    TripRouteNode,
    TripRouteNodeKind,
)
from app.schemas.trip_state import TripState
from app.repositories.trip import create_trip
from app.repositories.trip_plan import get_trip_plan
from app.repositories.trip_state import save_trip_state
from app.schemas.trip import TripCreate
from app.services.map_errors import (
    MapConfigurationError,
    MapNoResultsError,
    MapQuotaExceededError,
    MapTimeoutError,
    MapUpstreamError,
)


PROJECT_ROOT = Path(__file__).resolve().parents[2]


def _upgrade_test_database(database_url: str) -> None:
    config = Config(str(PROJECT_ROOT / "alembic.ini"))
    config.set_main_option("sqlalchemy.url", database_url)
    command.upgrade(config, "head")


class FakeSession:
    def __init__(self) -> None:
        self.rollback_calls = 0

    def rollback(self) -> None:
        self.rollback_calls += 1


class FakePlanningService:
    def __init__(self, result: PublicTransportTripPlan | Exception) -> None:
        self.result = result
        self.calls: list[tuple[TripState, object]] = []

    def plan(self, state: TripState, request: object) -> PublicTransportTripPlan:
        self.calls.append((state, request))
        if isinstance(self.result, Exception):
            raise self.result
        return self.result


@pytest.fixture
def client() -> Generator[TestClient, None, None]:
    def override_db() -> Generator[FakeSession, None, None]:
        yield FakeSession()

    app.dependency_overrides[get_db] = override_db
    try:
        yield TestClient(app)
    finally:
        app.dependency_overrides.clear()


def _location(poi_id: str) -> ResolvedLocation:
    return ResolvedLocation(
        poi_id=poi_id,
        name=poi_id,
        city_code="010",
        coordinate=GeoPoint(latitude=39.9, longitude=116.4),
    )


def _plan(trip_id: UUID) -> PublicTransportTripPlan:
    origin = _location("HOME")
    destination = _location("RETURN_HOME")
    origin_node = TripRouteNode(kind=TripRouteNodeKind.ORIGIN, location=origin)
    destination_node = TripRouteNode(
        kind=TripRouteNodeKind.RETURN_DESTINATION,
        location=destination,
    )
    return PublicTransportTripPlan(
        trip_id=trip_id,
        source_state_revision=1,
        nodes=[origin_node, destination_node],
        legs=[
            PublicTransportTripPlanLeg(
                kind=TripRouteLegKind.TO_OUTBOUND_DEPARTURE_NODE,
                origin_node_id=origin_node.node_id,
                destination_node_id=destination_node.node_id,
                origin=origin,
                destination=destination,
                fact_source=TripRouteFactSource.AMAP_LOCAL_PUBLIC_TRANSPORT,
                local_route=Route(
                    travel_mode=TravelMode.PUBLIC_TRANSPORT,
                    distance_meters=100,
                    segments=[RouteSegment(mode=RouteSegmentMode.WALKING, distance_meters=100)],
                ),
            )
        ],
    )


def _request_payload(trip_id: UUID) -> dict[str, object]:
    def intercity_leg(
        departure_poi_id: str, departure_city_code: str, arrival_poi_id: str, arrival_city_code: str
    ) -> dict[str, object]:
        return {
            "travel_mode": "high_speed_rail",
            "departure_poi_id": departure_poi_id,
            "arrival_poi_id": arrival_poi_id,
            "fact": {"service_identifier": "G123", "duration_seconds": 14400},
        }

    return {
        "trip_id": str(trip_id),
        "outbound_intercity": intercity_leg("NANJING_SOUTH", "010", "QINGDAO_NORTH", "0532"),
        "return_intercity": intercity_leg("QINGDAO_NORTH", "0532", "NANJING_SOUTH", "010"),
        "daily_places": [{"day_number": 1, "place_poi_ids": ["PLACE"]}],
    }


def _override_planner(service: FakePlanningService) -> None:
    app.dependency_overrides[get_public_transport_trip_planning_service] = lambda: service


def test_create_public_transport_plan_generates_saves_and_returns_plan(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    trip_id = uuid4()
    expected_plan = _plan(trip_id)
    service = FakePlanningService(expected_plan)
    _override_planner(service)
    saved_plans: list[PublicTransportTripPlan] = []
    monkeypatch.setattr("app.api.trips.get_trip_by_id", lambda session, identifier: object())
    monkeypatch.setattr(
        "app.api.trips.get_trip_state", lambda session, identifier: TripState(trip_id=trip_id, revision=1)
    )
    monkeypatch.setattr(
        "app.api.trips.save_trip_plan",
        lambda session, plan, **kwargs: saved_plans.append(plan) or plan,
    )

    response = client.post(
        f"/trips/{trip_id}/public-transport-plan", json=_request_payload(trip_id)
    )

    assert response.status_code == 201
    assert response.json()["trip_id"] == str(trip_id)
    assert response.json()["stale"] is False
    assert len(service.calls) == 1
    assert saved_plans == [expected_plan]


def test_create_public_transport_plan_rejects_missing_trip_or_state_before_planning(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    trip_id = uuid4()
    service = FakePlanningService(_plan(trip_id))
    _override_planner(service)
    monkeypatch.setattr("app.api.trips.get_trip_by_id", lambda session, identifier: None)

    missing_trip = client.post(
        f"/trips/{trip_id}/public-transport-plan", json=_request_payload(trip_id)
    )
    assert missing_trip.status_code == 404
    assert service.calls == []

    monkeypatch.setattr("app.api.trips.get_trip_by_id", lambda session, identifier: object())
    monkeypatch.setattr("app.api.trips.get_trip_state", lambda session, identifier: None)
    missing_state = client.post(
        f"/trips/{trip_id}/public-transport-plan", json=_request_payload(trip_id)
    )

    assert missing_state.status_code == 409
    assert missing_state.json() == {"detail": "TripState has not been created"}
    assert service.calls == []


@pytest.mark.parametrize(
    ("error", "expected_status", "expected_detail"),
    [
        (MapNoResultsError(), 422, "No public transport route is available for this plan"),
        (MapTimeoutError(), 504, "Public transport route request timed out"),
        (MapConfigurationError(), 503, "Public transport planning service is unavailable"),
        (MapQuotaExceededError(), 503, "Public transport planning service is unavailable"),
        (MapUpstreamError(), 502, "Public transport map service is unavailable"),
    ],
)
def test_create_public_transport_plan_maps_map_failures_without_saving(
    client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
    error: Exception,
    expected_status: int,
    expected_detail: str,
) -> None:
    trip_id = uuid4()
    service = FakePlanningService(error)
    _override_planner(service)
    save_calls: list[object] = []
    monkeypatch.setattr("app.api.trips.get_trip_by_id", lambda session, identifier: object())
    monkeypatch.setattr("app.api.trips.get_trip_state", lambda session, identifier: TripState(trip_id=trip_id))
    monkeypatch.setattr(
        "app.api.trips.save_trip_plan", lambda session, plan, **kwargs: save_calls.append(plan) or plan
    )

    response = client.post(
        f"/trips/{trip_id}/public-transport-plan", json=_request_payload(trip_id)
    )

    assert response.status_code == expected_status
    assert response.json() == {"detail": expected_detail}
    assert save_calls == []


def test_create_public_transport_plan_rejects_state_change_during_save(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    trip_id = uuid4()
    service = FakePlanningService(_plan(trip_id))
    _override_planner(service)
    monkeypatch.setattr("app.api.trips.get_trip_by_id", lambda session, identifier: object())
    monkeypatch.setattr(
        "app.api.trips.get_trip_state", lambda session, identifier: TripState(trip_id=trip_id, revision=1)
    )
    monkeypatch.setattr(
        "app.api.trips.save_trip_plan",
        lambda session, plan, **kwargs: (_ for _ in ()).throw(TripPlanStateRevisionConflictError()),
    )

    response = client.post(
        f"/trips/{trip_id}/public-transport-plan", json=_request_payload(trip_id)
    )

    assert response.status_code == 409
    assert response.json() == {
        "detail": "TripState changed while public transport plan was being generated"
    }


def test_create_public_transport_plan_rejects_path_and_payload_trip_id_mismatch(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    path_trip_id = uuid4()
    payload_trip_id = uuid4()
    service = FakePlanningService(_plan(path_trip_id))
    _override_planner(service)
    monkeypatch.setattr("app.api.trips.get_trip_by_id", lambda session, identifier: object())

    response = client.post(
        f"/trips/{path_trip_id}/public-transport-plan", json=_request_payload(payload_trip_id)
    )

    assert response.status_code == 422
    assert response.json() == {"detail": "Planning request trip_id must match path"}
    assert service.calls == []


def test_get_public_transport_plan_returns_saved_plan_without_planning(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    trip_id = uuid4()
    saved_plan = _plan(trip_id)
    monkeypatch.setattr("app.api.trips.get_trip_by_id", lambda session, identifier: object())
    monkeypatch.setattr("app.api.trips.get_trip_plan", lambda session, identifier: saved_plan)
    monkeypatch.setattr(
        "app.api.trips.get_trip_state", lambda session, identifier: TripState(trip_id=trip_id, revision=1)
    )

    response = client.get(f"/trips/{trip_id}/public-transport-plan")

    assert response.status_code == 200
    assert response.json()["trip_id"] == str(trip_id)
    assert response.json()["stale"] is False
    assert response.json()["legs"][0]["fact_source"] == "amap_local_public_transport"


def test_get_public_transport_plan_marks_an_older_snapshot_stale(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    trip_id = uuid4()
    monkeypatch.setattr("app.api.trips.get_trip_by_id", lambda session, identifier: object())
    monkeypatch.setattr("app.api.trips.get_trip_plan", lambda session, identifier: _plan(trip_id))
    monkeypatch.setattr(
        "app.api.trips.get_trip_state", lambda session, identifier: TripState(trip_id=trip_id, revision=2)
    )

    response = client.get(f"/trips/{trip_id}/public-transport-plan")

    assert response.status_code == 200
    assert response.json()["stale"] is True


def test_get_public_transport_plan_rejects_unknown_trip_or_missing_plan(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    trip_id = uuid4()
    monkeypatch.setattr("app.api.trips.get_trip_by_id", lambda session, identifier: None)

    missing_trip = client.get(f"/trips/{trip_id}/public-transport-plan")
    assert missing_trip.status_code == 404
    assert missing_trip.json() == {"detail": "Trip not found"}

    monkeypatch.setattr("app.api.trips.get_trip_by_id", lambda session, identifier: object())
    monkeypatch.setattr("app.api.trips.get_trip_plan", lambda session, identifier: None)
    missing_plan = client.get(f"/trips/{trip_id}/public-transport-plan")

    assert missing_plan.status_code == 404
    assert missing_plan.json() == {"detail": "Public transport plan has not been generated"}


@pytest.mark.integration
def test_create_public_transport_plan_persists_the_generated_plan() -> None:
    database_url = str(Settings().test_database_url)
    _upgrade_test_database(database_url)
    engine = create_database_engine(database_url)
    trip_id: UUID | None = None

    def override_db() -> Generator[Session, None, None]:
        with Session(engine) as session:
            yield session

    app.dependency_overrides[get_db] = override_db
    try:
        with Session(engine) as session:
            trip = create_trip(
                session,
                TripCreate(name="公共交通出行", start_date="2026-10-01", end_date="2026-10-02"),
            )
            trip_id = trip.id
            save_trip_state(
                session, TripState(trip_id=trip.id), expected_revision=0
            )
            session.commit()

        expected_plan = _plan(trip_id)
        service = FakePlanningService(expected_plan)
        _override_planner(service)
        with TestClient(app) as client:
            response = client.post(
                f"/trips/{trip_id}/public-transport-plan", json=_request_payload(trip_id)
            )
            get_response = client.get(f"/trips/{trip_id}/public-transport-plan")

        assert response.status_code == 201
        assert get_response.status_code == 200
        assert get_response.json() == response.json()
        with Session(engine) as session:
            assert get_trip_plan(session, trip_id) == expected_plan
    finally:
        app.dependency_overrides.clear()
        if trip_id is not None:
            with engine.begin() as connection:
                connection.execute(
                    text("DELETE FROM trip_plans WHERE trip_id = :trip_id"),
                    {"trip_id": trip_id},
                )
                connection.execute(
                    text("DELETE FROM trip_states WHERE trip_id = :trip_id"),
                    {"trip_id": trip_id},
                )
                connection.execute(
                    text("DELETE FROM trips WHERE id = :trip_id"), {"trip_id": trip_id})
        engine.dispose()
