"""Persisted user-confirmed memory scoped to one Trip."""

from datetime import datetime
from typing import Any
from uuid import UUID, uuid4

from sqlalchemy import DateTime, ForeignKey, String, UniqueConstraint, Uuid, func
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base


class TripMemoryRecord(Base):
    __tablename__ = "trip_memories"
    __table_args__ = (UniqueConstraint("trip_id", "category", "key", name="uq_trip_memory_key"),)

    id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True, default=uuid4)
    trip_id: Mapped[UUID] = mapped_column(Uuid(as_uuid=True), ForeignKey("trips.id"), nullable=False, index=True)
    category: Mapped[str] = mapped_column(String(40), nullable=False)
    key: Mapped[str] = mapped_column(String(100), nullable=False)
    value: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False)
