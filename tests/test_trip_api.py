from pathlib import Path
from datetime import date
from uuid import uuid4

import pytest
from alembic import command
from alembic.config import Config
from fastapi.testclient import TestClient
from sqlalchemy import text
from sqlalchemy.orm import Session

from app.core.config import Settings
from app.db.session import create_database_engine, get_db
from app.main import app
from app.models.trip import Trip
from app.repositories.trip import get_trip_by_id
from app.repositories.trip_state import get_trip_state, save_trip_state
from app.schemas.trip_state import TripState
from app.schemas.trip_state_assessment import RequiredTripStateField
from app.services.trip_state_assessor import assess_trip_state


PROJECT_ROOT = Path(__file__).resolve().parents[1]


def _upgrade_test_database(database_url: str) -> None:
    config = Config(str(PROJECT_ROOT / "alembic.ini"))
    config.set_main_option("sqlalchemy.url", database_url)
    command.upgrade(config, "head")


@pytest.mark.integration
def test_create_trip_persists_data_in_test_database() -> None:
    test_database_url = str(Settings().test_database_url)
    _upgrade_test_database(test_database_url)
    engine = create_database_engine(test_database_url)

    def override_get_db():
        from sqlalchemy.orm import Session

        with Session(engine) as session:
            yield session

    app.dependency_overrides[get_db] = override_get_db
    try:
        with TestClient(app) as client:
            response = client.post(
                "/trips",
                json={
                    "name": "北京五日游",
                    "start_date": "2026-10-01",
                    "end_date": "2026-10-05",
                },
            )
            missing_response = client.get(f"/trips/{uuid4()}")

        assert response.status_code == 201
        created_trip = response.json()
        assert created_trip["name"] == "北京五日游"
        assert created_trip["start_date"] == "2026-10-01"
        assert created_trip["end_date"] == "2026-10-05"
        assert missing_response.status_code == 404
        assert missing_response.json() == {"detail": "Trip not found"}

        with TestClient(app) as client:
            get_response = client.get(f"/trips/{created_trip['id']}")

        assert get_response.status_code == 200
        assert get_response.json() == created_trip

        with TestClient(app) as client:
            update_response = client.patch(
                f"/trips/{created_trip['id']}",
                json={"name": "更新后的北京五日游", "end_date": "2026-10-06"},
            )
            invalid_date_response = client.patch(
                f"/trips/{created_trip['id']}",
                json={"end_date": "2026-09-30"},
            )
            missing_update_response = client.patch(
                f"/trips/{uuid4()}",
                json={"name": "不存在的旅行"},
            )
            null_update_responses = [
                client.patch(f"/trips/{created_trip['id']}", json={field_name: None})
                for field_name in ("name", "start_date", "end_date")
            ]
            updated_get_response = client.get(f"/trips/{created_trip['id']}")

        assert update_response.status_code == 200
        updated_trip = update_response.json()
        assert updated_trip["name"] == "更新后的北京五日游"
        assert updated_trip["end_date"] == "2026-10-06"
        assert invalid_date_response.status_code == 422
        assert invalid_date_response.json() == {
            "detail": "start_date must not be after end_date"
        }
        assert missing_update_response.status_code == 404
        assert missing_update_response.json() == {"detail": "Trip not found"}
        assert all(response.status_code == 422 for response in null_update_responses)
        assert updated_get_response.status_code == 200
        assert updated_get_response.json() == updated_trip

        with engine.begin() as connection:
            persisted_name = connection.execute(
                text("SELECT name FROM trips WHERE id = :trip_id"),
                {"trip_id": created_trip["id"]},
            ).scalar_one()
            connection.execute(
                text("DELETE FROM trips WHERE id = :trip_id"),
                {"trip_id": created_trip["id"]},
            )

        assert persisted_name == "更新后的北京五日游"
    finally:
        app.dependency_overrides.clear()
        engine.dispose()


@pytest.mark.integration
def test_patch_trip_handles_partial_dates_and_syncs_existing_trip_state() -> None:
    database_url = str(Settings().test_database_url)
    _upgrade_test_database(database_url)
    engine = create_database_engine(database_url)
    trip_ids: list[object] = []
    no_dates_trip_id: object | None = None
    start_only_trip_id: object | None = None
    end_only_trip_id: object | None = None
    state_trip_id: object | None = None

    def override_get_db():
        with Session(engine) as session:
            yield session

    app.dependency_overrides[get_db] = override_get_db
    try:
        with Session(engine) as session:
            no_dates_trip = Trip()
            start_only_trip = Trip(start_date=date(2026, 10, 1))
            end_only_trip = Trip(end_date=date(2026, 10, 3))
            state_trip = Trip(start_date=date(2026, 10, 1), end_date=date(2026, 10, 3))
            session.add_all([no_dates_trip, start_only_trip, end_only_trip, state_trip])
            session.commit()
            trip_ids = [
                no_dates_trip.id,
                start_only_trip.id,
                end_only_trip.id,
                state_trip.id,
            ]
            no_dates_trip_id, start_only_trip_id, end_only_trip_id, state_trip_id = trip_ids
            save_trip_state(
                session,
                TripState(
                    trip_id=state_trip.id,
                    departure_date="2026-10-01",
                    return_date="2026-10-03",
                ),
            )

        with TestClient(app) as client:
            no_dates_response = client.patch(
                f"/trips/{no_dates_trip_id}", json={"name": "无日期旅行"}
            )
            start_only_response = client.patch(
                f"/trips/{start_only_trip_id}", json={"name": "仅有出发日"}
            )
            end_only_response = client.patch(
                f"/trips/{end_only_trip_id}", json={"name": "仅有返程日"}
            )
            date_sync_response = client.patch(
                f"/trips/{state_trip_id}", json={"end_date": "2026-10-04"}
            )
            name_only_response = client.patch(
                f"/trips/{state_trip_id}", json={"name": "仅修改名称"}
            )
            invalid_date_response = client.patch(
                f"/trips/{state_trip_id}", json={"start_date": "2026-10-05"}
            )

        assert no_dates_response.status_code == 200
        assert start_only_response.status_code == 200
        assert end_only_response.status_code == 200
        assert date_sync_response.status_code == 200
        assert date_sync_response.json()["end_date"] == "2026-10-04"
        assert name_only_response.status_code == 200
        assert invalid_date_response.status_code == 422

        with Session(engine) as session:
            persisted_state = get_trip_state(session, state_trip_id)
            persisted_trip = get_trip_by_id(session, state_trip_id)

        assert persisted_trip is not None
        assert persisted_trip.name == "仅修改名称"
        assert persisted_trip.start_date.isoformat() == "2026-10-01"
        assert persisted_trip.end_date.isoformat() == "2026-10-04"
        assert persisted_state is not None
        assert persisted_state.departure_date.isoformat() == "2026-10-01"
        assert persisted_state.return_date.isoformat() == "2026-10-04"
        assessment = assess_trip_state(persisted_state)
        assert RequiredTripStateField.DEPARTURE_DATE not in assessment.missing_fields
        assert RequiredTripStateField.RETURN_DATE not in assessment.missing_fields
    finally:
        app.dependency_overrides.clear()
        with engine.begin() as connection:
            for trip_id in trip_ids:
                connection.execute(
                    text("DELETE FROM trip_states WHERE trip_id = :trip_id"),
                    {"trip_id": trip_id},
                )
                connection.execute(
                    text("DELETE FROM trips WHERE id = :trip_id"), {"trip_id": trip_id}
                )
        engine.dispose()
