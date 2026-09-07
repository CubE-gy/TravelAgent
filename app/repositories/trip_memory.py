"""Storage operations for current-trip semantic memory."""

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.trip_memory import TripMemoryRecord


def list_trip_memories(session: Session, trip_id: object) -> list[TripMemoryRecord]:
    return list(session.scalars(select(TripMemoryRecord).where(TripMemoryRecord.trip_id == trip_id).order_by(TripMemoryRecord.updated_at)).all())


def upsert_trip_memory(session: Session, trip_id: object, category: str, key: str, value: dict[str, object]) -> None:
    record = session.scalars(select(TripMemoryRecord).where(TripMemoryRecord.trip_id == trip_id, TripMemoryRecord.category == category, TripMemoryRecord.key == key)).first()
    if record is None:
        session.add(TripMemoryRecord(trip_id=trip_id, category=category, key=key, value=value))
    else:
        record.value = value


def forget_trip_memory(session: Session, trip_id: object, category: str, key: str) -> None:
    record = session.scalars(select(TripMemoryRecord).where(TripMemoryRecord.trip_id == trip_id, TripMemoryRecord.category == category, TripMemoryRecord.key == key)).first()
    if record is not None:
        session.delete(record)
