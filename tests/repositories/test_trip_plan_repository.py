from pathlib import Path
from uuid import uuid4

import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy import text
from sqlalchemy.orm import Session

from app.core.config import Settings
from app.db.session import create_database_engine
from app.models.enums import RouteSegmentMode, TravelMode
from app.repositories.trip import create_trip
from app.repositories.trip_plan import (
    TripPlanStateRevisionConflictError,
    get_trip_plan,
    save_trip_plan,
)
from app.repositories.trip_state import save_trip_state
from app.schemas.map import GeoPoint, ResolvedLocation, Route, RouteSegment
from app.schemas.trip import TripCreate
from app.schemas.trip_public_transport_plan import (
    PublicTransportTripPlan,
    PublicTransportTripPlanLeg,
    TripRouteFactSource,
    TripRouteLegKind,
    TripRouteNode,
    TripRouteNodeKind,
)
from app.schemas.trip_state import TripState


PROJECT_ROOT = Path(__file__).resolve().parents[2]


def _upgrade_test_database(database_url: str) -> None:
    config = Config(str(PROJECT_ROOT / "alembic.ini"))
    config.set_main_option("sqlalchemy.url", database_url)
    command.upgrade(config, "head")


def _location(poi_id: str) -> ResolvedLocation:
    return ResolvedLocation(
        poi_id=poi_id,
        name=poi_id,
        city_code="010",
        coordinate=GeoPoint(latitude=39.9, longitude=116.4),
    )


def _plan(trip_id: object, *, distance_meters: int) -> PublicTransportTripPlan:
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
                    distance_meters=distance_meters,
                    segments=[
                        RouteSegment(
                            mode=RouteSegmentMode.WALKING,
                            distance_meters=distance_meters,
                        )
                    ],
                ),
            )
        ],
    )


def test_save_trip_plan_requires_an_expected_state_revision() -> None:
    with pytest.raises(TypeError, match="expected_state_revision"):
        save_trip_plan(object(), _plan(uuid4(), distance_meters=100))  # type: ignore[arg-type]


@pytest.mark.integration
def test_trip_plan_can_be_saved_read_and_replaced_in_postgresql() -> None:
    database_url = str(Settings().test_database_url)
    _upgrade_test_database(database_url)
    engine = create_database_engine(database_url)
    trip_id = None
    try:
        with Session(engine) as session:
            trip = create_trip(
                session,
                TripCreate(name="北京出行", start_date="2026-10-01", end_date="2026-10-02"),
            )
            trip_id = trip.id
            save_trip_state(
                session,
                TripState(trip_id=trip.id),
                expected_revision=0,
            )
            session.commit()
            first_plan = _plan(trip.id, distance_meters=100)

            assert get_trip_plan(session, trip.id) is None
            assert (
                save_trip_plan(session, first_plan, expected_state_revision=1)
                == first_plan
            )
            with pytest.raises(ValueError, match="source revision"):
                save_trip_plan(session, first_plan, expected_state_revision=2)

        with Session(engine) as session:
            assert get_trip_plan(session, trip_id) == first_plan
            replacement_plan = _plan(trip_id, distance_meters=200)
            assert (
                save_trip_plan(session, replacement_plan, expected_state_revision=1)
                == replacement_plan
            )

        with Session(engine) as session:
            assert get_trip_plan(session, trip_id) == replacement_plan
            record_count = session.execute(
                text("SELECT COUNT(*) FROM trip_plans WHERE trip_id = :trip_id"),
                {"trip_id": trip_id},
            ).scalar_one()

        assert record_count == 1
    finally:
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


@pytest.mark.integration
def test_trip_plan_cannot_be_saved_without_an_existing_trip() -> None:
    database_url = str(Settings().test_database_url)
    _upgrade_test_database(database_url)
    engine = create_database_engine(database_url)
    try:
        with Session(engine) as session:
            with pytest.raises(ValueError, match="Trip not found"):
                save_trip_plan(
                    session,
                    _plan(uuid4(), distance_meters=100),
                    expected_state_revision=1,
                )
    finally:
        engine.dispose()


@pytest.mark.integration
def test_trip_plan_rejects_a_stale_state_revision_without_overwriting_current_plan() -> None:
    database_url = str(Settings().test_database_url)
    _upgrade_test_database(database_url)
    engine = create_database_engine(database_url)
    trip_id = None
    try:
        with Session(engine) as session:
            trip = create_trip(
                session,
                TripCreate(name="并发路线", start_date="2026-10-01", end_date="2026-10-02"),
            )
            trip_id = trip.id
            first_state = save_trip_state(
                session,
                TripState(trip_id=trip.id),
                expected_revision=0,
            )
            session.commit()
            current_plan = _plan(trip.id, distance_meters=100)
            save_trip_plan(
                session,
                current_plan,
                expected_state_revision=first_state.revision,
            )

        with Session(engine) as session:
            save_trip_state(
                session,
                TripState(trip_id=trip_id, revision=1, destination={"query": "上海"}),
                expected_revision=1,
            )
            session.commit()

        with Session(engine) as session:
            stale_plan = _plan(trip_id, distance_meters=200)
            with pytest.raises(TripPlanStateRevisionConflictError):
                save_trip_plan(
                    session,
                    stale_plan,
                    expected_state_revision=stale_plan.source_state_revision,
                )
            session.rollback()
            assert get_trip_plan(session, trip_id) == current_plan
    finally:
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
                    text("DELETE FROM trips WHERE id = :trip_id"),
                    {"trip_id": trip_id},
                )
        engine.dispose()
