from collections.abc import Generator
from datetime import datetime, timezone
from types import SimpleNamespace
from uuid import UUID, uuid4

import pytest
from fastapi.testclient import TestClient

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


class FakeSession:
    pass


@pytest.fixture
def client() -> Generator[TestClient, None, None]:
    app.dependency_overrides[get_db] = lambda: FakeSession()
    try:
        yield TestClient(app)
    finally:
        app.dependency_overrides.clear()


def _trip(trip_id: UUID) -> SimpleNamespace:
    timestamp = datetime(2026, 1, 1, tzinfo=timezone.utc)
    return SimpleNamespace(
        id=trip_id,
        name="北京旅行",
        start_date=None,
        end_date=None,
        created_at=timestamp,
        updated_at=timestamp,
    )


def _location(poi_id: str) -> ResolvedLocation:
    return ResolvedLocation(
        poi_id=poi_id,
        name=poi_id,
        coordinate=GeoPoint(latitude=39.9, longitude=116.4),
    )


def _plan(trip_id: UUID, source_state_revision: int = 1) -> PublicTransportTripPlan:
    origin = _location("HOME")
    destination = _location("RETURN_HOME")
    origin_node = TripRouteNode(kind=TripRouteNodeKind.ORIGIN, location=origin)
    destination_node = TripRouteNode(
        kind=TripRouteNodeKind.RETURN_DESTINATION, location=destination
    )
    return PublicTransportTripPlan(
        trip_id=trip_id,
        source_state_revision=source_state_revision,
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
                    segments=[
                        RouteSegment(mode=RouteSegmentMode.WALKING, distance_meters=100)
                    ],
                ),
            )
        ],
    )


def test_workspace_returns_trip_state_and_current_plan(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    trip_id = uuid4()
    monkeypatch.setattr("app.api.trips.get_trip_by_id", lambda session, identifier: _trip(trip_id))
    monkeypatch.setattr(
        "app.api.trips.get_trip_state", lambda session, identifier: TripState(trip_id=trip_id, revision=1)
    )
    monkeypatch.setattr("app.api.trips.get_trip_plan", lambda session, identifier: _plan(trip_id))

    response = client.get(f"/trips/{trip_id}/workspace")

    assert response.status_code == 200
    assert response.json()["trip"]["id"] == str(trip_id)
    assert response.json()["state"]["revision"] == 1
    assert response.json()["public_transport_plan"]["stale"] is False


def test_workspace_allows_missing_state_and_plan(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    trip_id = uuid4()
    monkeypatch.setattr("app.api.trips.get_trip_by_id", lambda session, identifier: _trip(trip_id))
    monkeypatch.setattr("app.api.trips.get_trip_state", lambda session, identifier: None)
    monkeypatch.setattr("app.api.trips.get_trip_plan", lambda session, identifier: None)

    response = client.get(f"/trips/{trip_id}/workspace")

    assert response.status_code == 200
    assert response.json()["state"] is None
    assert response.json()["public_transport_plan"] is None


def test_workspace_marks_outdated_plan_stale(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    trip_id = uuid4()
    monkeypatch.setattr("app.api.trips.get_trip_by_id", lambda session, identifier: _trip(trip_id))
    monkeypatch.setattr(
        "app.api.trips.get_trip_state", lambda session, identifier: TripState(trip_id=trip_id, revision=2)
    )
    monkeypatch.setattr("app.api.trips.get_trip_plan", lambda session, identifier: _plan(trip_id))

    response = client.get(f"/trips/{trip_id}/workspace")

    assert response.status_code == 200
    assert response.json()["public_transport_plan"]["stale"] is True


def test_workspace_rejects_unknown_trip(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr("app.api.trips.get_trip_by_id", lambda session, identifier: None)

    response = client.get(f"/trips/{uuid4()}/workspace")

    assert response.status_code == 404
    assert response.json() == {"detail": "Trip not found"}
