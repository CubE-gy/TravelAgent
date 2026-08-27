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
from app.repositories.trip_plan import get_trip_plan, save_trip_plan
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


PROJECT_ROOT = Path(__file__).resolve().parents[1]


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
    destination = _location("STATION")
    return PublicTransportTripPlan(
        trip_id=trip_id,
        nodes=[
            TripRouteNode(kind=TripRouteNodeKind.ORIGIN, location=origin),
            TripRouteNode(kind=TripRouteNodeKind.OUTBOUND_DEPARTURE_NODE, location=destination),
        ],
        legs=[
            PublicTransportTripPlanLeg(
                kind=TripRouteLegKind.TO_OUTBOUND_DEPARTURE_NODE,
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
            first_plan = _plan(trip.id, distance_meters=100)

            assert get_trip_plan(session, trip.id) is None
            assert save_trip_plan(session, first_plan) == first_plan

        with Session(engine) as session:
            assert get_trip_plan(session, trip_id) == first_plan
            replacement_plan = _plan(trip_id, distance_meters=200)
            assert save_trip_plan(session, replacement_plan) == replacement_plan

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
                save_trip_plan(session, _plan(uuid4(), distance_meters=100))
    finally:
        engine.dispose()
