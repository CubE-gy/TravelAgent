"""Persistence helpers for the one active recommendation candidate set per Trip."""

from uuid import UUID

from sqlalchemy import update
from sqlalchemy.orm import Session

from app.models.trip_recommendation_session import TripRecommendationSessionRecord


def replace_active_recommendation_session(
    session: Session, trip_id: UUID, *, kind: str, query: str | None,
    candidates: list[dict[str, object]], state_revision: int,
) -> TripRecommendationSessionRecord:
    session.execute(update(TripRecommendationSessionRecord).where(
        TripRecommendationSessionRecord.trip_id == trip_id,
        TripRecommendationSessionRecord.is_active.is_(True),
    ).values(is_active=False))
    record = TripRecommendationSessionRecord(
        trip_id=trip_id, kind=kind, query=query, candidates=candidates,
        state_revision=state_revision,
    )
    session.add(record)
    session.flush()
    return record


def get_active_recommendation_session(
    session: Session, trip_id: UUID, recommendation_session_id: UUID,
) -> TripRecommendationSessionRecord | None:
    record = session.get(TripRecommendationSessionRecord, recommendation_session_id)
    return record if record and record.trip_id == trip_id and record.is_active else None
