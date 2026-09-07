from pathlib import Path

import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy import text
from sqlalchemy.orm import Session

from app.core.config import Settings
from app.db.session import create_database_engine
from app.repositories.trip import create_empty_trip
from app.repositories.trip_memory import forget_trip_memory, list_trip_memories, upsert_trip_memory


PROJECT_ROOT = Path(__file__).resolve().parents[2]


@pytest.mark.integration
def test_trip_memory_is_scoped_upserted_and_forgotten() -> None:
    database_url = str(Settings().test_database_url)
    config = Config(str(PROJECT_ROOT / "alembic.ini"))
    config.set_main_option("sqlalchemy.url", database_url)
    command.upgrade(config, "head")
    engine = create_database_engine(database_url)
    trip_id = None
    try:
        with Session(engine) as session:
            trip = create_empty_trip(session)
            trip_id = trip.id
            upsert_trip_memory(session, trip_id, "preference", "hotel", {"text": "安静"})
            upsert_trip_memory(session, trip_id, "preference", "hotel", {"text": "靠近地铁"})
            session.commit()
        with Session(engine) as session:
            memories = list_trip_memories(session, trip_id)
            assert [(memory.category, memory.key, memory.value) for memory in memories] == [
                ("preference", "hotel", {"text": "靠近地铁"})
            ]
            forget_trip_memory(session, trip_id, "preference", "hotel")
            session.commit()
        with Session(engine) as session:
            assert list_trip_memories(session, trip_id) == []
    finally:
        if trip_id is not None:
            with engine.begin() as connection:
                connection.execute(text("DELETE FROM trip_memories WHERE trip_id = :trip_id"), {"trip_id": trip_id})
                connection.execute(text("DELETE FROM trips WHERE id = :trip_id"), {"trip_id": trip_id})
        engine.dispose()
