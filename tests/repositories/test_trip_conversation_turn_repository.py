from pathlib import Path

import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy import text
from sqlalchemy.orm import Session

from app.core.config import Settings
from app.db.session import create_database_engine
from app.repositories.trip import create_empty_trip
from app.repositories.trip_conversation_turn import (
    add_trip_conversation_turn,
    list_trip_conversation_turns,
)


PROJECT_ROOT = Path(__file__).resolve().parents[2]


@pytest.mark.integration
def test_conversation_turns_are_appended_and_listed_in_order() -> None:
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
            for index, message in enumerate(["我要去北京", "住国贸附近", "再加中山陵"]):
                add_trip_conversation_turn(
                    session,
                    trip_id,
                    user_message=message,
                    assistant_message=f"已记录{index}",
                    state_revision=index,
                    trace={"decision": "update_trip_state", "llm_calls": []},
                )
            session.commit()
        with Session(engine) as session:
            turns = list_trip_conversation_turns(session, trip_id)
            assert [turn.user_message for turn in turns] == [
                "我要去北京",
                "住国贸附近",
                "再加中山陵",
            ]
            assert [turn.turn_index for turn in turns] == [0, 1, 2]
            assert [turn.state_revision for turn in turns] == [0, 1, 2]
            assert turns[0].trace["decision"] == "update_trip_state"
            assert list_trip_conversation_turns(session, trip_id, limit=2) == turns[1:]
    finally:
        if trip_id is not None:
            with engine.begin() as connection:
                connection.execute(
                    text("DELETE FROM trip_conversation_turns WHERE trip_id = :trip_id"),
                    {"trip_id": trip_id},
                )
                connection.execute(
                    text("DELETE FROM trips WHERE id = :trip_id"), {"trip_id": trip_id}
                )
        engine.dispose()
