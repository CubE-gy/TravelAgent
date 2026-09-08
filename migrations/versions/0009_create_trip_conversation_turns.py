"""Create the persisted conversation turn history for a Trip.

Revision ID: 0009_create_trip_conversation_turns
Revises: 0008_create_trip_recommendation_sessions
"""
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0009_create_trip_conversation_turns"
down_revision: str | None = "0008_create_trip_recommendation_sessions"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table("trip_conversation_turns", sa.Column("id", sa.Uuid(), primary_key=True), sa.Column("trip_id", sa.Uuid(), sa.ForeignKey("trips.id"), nullable=False), sa.Column("turn_index", sa.Integer(), nullable=False), sa.Column("user_message", sa.Text(), nullable=False), sa.Column("assistant_message", sa.Text()), sa.Column("state_revision", sa.Integer(), nullable=False), sa.Column("trace", postgresql.JSONB(), nullable=False), sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False), sa.UniqueConstraint("trip_id", "turn_index", name="uq_trip_conversation_turn_index"))
    op.create_index("ix_trip_conversation_turns_trip_id", "trip_conversation_turns", ["trip_id"])


def downgrade() -> None:
    op.drop_index("ix_trip_conversation_turns_trip_id", table_name="trip_conversation_turns")
    op.drop_table("trip_conversation_turns")
