"""Short-lived server-side candidate set for an unselected map recommendation."""

from datetime import datetime
from typing import Any
from uuid import UUID, uuid4

from sqlalchemy import Boolean, DateTime, ForeignKey, Integer, String, Uuid, func
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base


class TripRecommendationSessionRecord(Base):
    __tablename__ = "trip_recommendation_sessions"

    id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True, default=uuid4)
    trip_id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), ForeignKey("trips.id"), nullable=False, index=True)
    kind: Mapped[str] = mapped_column(String(20), nullable=False)
    query: Mapped[str | None] = mapped_column(String(80))
    candidates: Mapped[list[dict[str, Any]]] = mapped_column(JSONB, nullable=False)
    state_revision: Mapped[int] = mapped_column(Integer, nullable=False)
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)
