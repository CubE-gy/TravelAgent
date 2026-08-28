from pathlib import Path
from uuid import uuid4

import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy import text
from sqlalchemy.orm import Session

from app.core.config import Settings
from app.db.session import create_database_engine
from app.repositories.trip import create_trip
from app.repositories.trip_state import (
    TripStateRevisionConflictError,
    get_trip_state,
    save_trip_state,
)
from app.schemas.trip import TripCreate
from app.schemas.trip_state import TripState


PROJECT_ROOT = Path(__file__).resolve().parents[2]


def _upgrade_test_database(database_url: str) -> None:
    config = Config(str(PROJECT_ROOT / "alembic.ini"))
    config.set_main_option("sqlalchemy.url", database_url)
    command.upgrade(config, "head")


def _create_trip(session: Session):
    return create_trip(
        session,
        TripCreate(name="北京五日游", start_date="2026-10-01", end_date="2026-10-05"),
    )


@pytest.mark.integration
def test_trip_state_can_be_saved_read_and_replaced_in_postgresql() -> None:
    database_url = str(Settings().test_database_url)
    _upgrade_test_database(database_url)
    engine = create_database_engine(database_url)
    trip_id = None
    try:
        with Session(engine) as session:
            trip = _create_trip(session)
            trip_id = trip.id
            first_state = TripState(trip_id=trip.id, destination={"query": "北京"})

            assert get_trip_state(session, trip.id) is None
            first_persisted_state = save_trip_state(
                session, first_state, expected_revision=0
            )
            session.commit()
            assert first_persisted_state.revision == 1

        with Session(engine) as session:
            restored_state = get_trip_state(session, trip_id)

            assert restored_state == first_persisted_state
            replacement_state = TripState(
                trip_id=trip_id,
                revision=restored_state.revision,
                destination={"query": "北京"},
                accommodation={"query": "王府井附近"},
                places=[{"query": "故宫博物院"}],
            )
            replacement_persisted_state = save_trip_state(
                session, replacement_state, expected_revision=1
            )
            session.commit()
            assert replacement_persisted_state.revision == 2

        with Session(engine) as session:
            assert get_trip_state(session, trip_id) == replacement_persisted_state
            record_count = session.execute(
                text("SELECT COUNT(*) FROM trip_states WHERE trip_id = :trip_id"),
                {"trip_id": trip_id},
            ).scalar_one()
            revision = session.execute(
                text("SELECT revision FROM trip_states WHERE trip_id = :trip_id"),
                {"trip_id": trip_id},
            ).scalar_one()

        assert record_count == 1
        assert revision == 2
    finally:
        if trip_id is not None:
            with engine.begin() as connection:
                connection.execute(
                    text("DELETE FROM trip_states WHERE trip_id = :trip_id"),
                    {"trip_id": trip_id},
                )
                connection.execute(
                    text("DELETE FROM trips WHERE id = :trip_id"),
                    {"trip_id": trip_id},
                )
        engine.dispose()


@pytest.mark.integration
def test_trip_state_repository_rejects_a_stale_revision() -> None:
    database_url = str(Settings().test_database_url)
    _upgrade_test_database(database_url)
    engine = create_database_engine(database_url)
    trip_id = None
    try:
        with Session(engine) as session:
            trip = _create_trip(session)
            trip_id = trip.id
            save_trip_state(
                session, TripState(trip_id=trip_id), expected_revision=0
            )
            session.commit()

        with Session(engine) as session:
            stale_state = TripState(trip_id=trip_id, destination={"query": "北京"})
            with pytest.raises(TripStateRevisionConflictError):
                save_trip_state(session, stale_state, expected_revision=0)
            session.rollback()

        with Session(engine) as session:
            persisted_state = get_trip_state(session, trip_id)
        assert persisted_state is not None
        assert persisted_state.revision == 1
        assert persisted_state.destination is None
    finally:
        if trip_id is not None:
            with engine.begin() as connection:
                connection.execute(
                    text("DELETE FROM trip_states WHERE trip_id = :trip_id"),
                    {"trip_id": trip_id},
                )
                connection.execute(
                    text("DELETE FROM trips WHERE id = :trip_id"),
                    {"trip_id": trip_id},
                )
        engine.dispose()


@pytest.mark.integration
def test_trip_state_cannot_be_saved_without_an_existing_trip() -> None:
    database_url = str(Settings().test_database_url)
    _upgrade_test_database(database_url)
    engine = create_database_engine(database_url)
    try:
        with Session(engine) as session:
            with pytest.raises(ValueError, match="Trip not found"):
                save_trip_state(
                    session, TripState(trip_id=uuid4()), expected_revision=0
                )
    finally:
        engine.dispose()


@pytest.mark.integration
def test_trip_state_repository_does_not_commit_the_callers_transaction() -> None:
    database_url = str(Settings().test_database_url)
    _upgrade_test_database(database_url)
    engine = create_database_engine(database_url)
    trip_id = None
    try:
        with Session(engine) as session:
            trip = _create_trip(session)
            trip_id = trip.id
            save_trip_state(
                session, TripState(trip_id=trip_id), expected_revision=0
            )
            session.rollback()

        with Session(engine) as session:
            assert get_trip_state(session, trip_id) is None
    finally:
        if trip_id is not None:
            with engine.begin() as connection:
                connection.execute(
                    text("DELETE FROM trips WHERE id = :trip_id"),
                    {"trip_id": trip_id},
                )
        engine.dispose()
