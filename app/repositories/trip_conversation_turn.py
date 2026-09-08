"""Storage operations for recorded Trip conversation turns."""

from typing import Any

from sqlalchemy import desc, func, select
from sqlalchemy.orm import Session

from app.models.trip_conversation_turn import TripConversationTurnRecord


def add_trip_conversation_turn(
    session: Session,
    trip_id: object,
    *,
    user_message: str,
    assistant_message: str | None,
    state_revision: int,
    trace: dict[str, Any],
) -> TripConversationTurnRecord:
    """Append one turn without committing the caller's transaction."""
    turn_index = (
        session.scalar(
            select(func.count())
            .select_from(TripConversationTurnRecord)
            .where(TripConversationTurnRecord.trip_id == trip_id)
        )
        or 0
    )
    record = TripConversationTurnRecord(
        trip_id=trip_id,
        turn_index=turn_index,
        user_message=user_message,
        assistant_message=assistant_message,
        state_revision=state_revision,
        trace=trace,
    )
    session.add(record)
    session.flush()
    return record


def list_trip_conversation_turns(
    session: Session, trip_id: object, *, limit: int = 20
) -> list[TripConversationTurnRecord]:
    """Return the latest turns of one Trip in chronological order."""
    newest_first = session.scalars(
        select(TripConversationTurnRecord)
        .where(TripConversationTurnRecord.trip_id == trip_id)
        .order_by(desc(TripConversationTurnRecord.turn_index))
        .limit(limit)
    ).all()
    return list(reversed(list(newest_first)))
