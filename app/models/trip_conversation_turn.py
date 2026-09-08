"""Persisted record of one handled natural-language conversation turn."""

from datetime import datetime
from typing import Any
from uuid import UUID, uuid4

from sqlalchemy import DateTime, ForeignKey, Integer, Text, Uuid, func
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base


class TripConversationTurnRecord(Base):
    __tablename__ = "trip_conversation_turns"

    id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True, default=uuid4)
    trip_id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), ForeignKey("trips.id"), nullable=False, index=True)
    turn_index: Mapped[int] = mapped_column(Integer, nullable=False)
    user_message: Mapped[str] = mapped_column(Text, nullable=False)
    assistant_message: Mapped[str | None] = mapped_column(Text)
    state_revision: Mapped[int] = mapped_column(Integer, nullable=False)
    trace: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)
