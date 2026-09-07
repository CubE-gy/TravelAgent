"""Create server-side transient recommendation candidate sessions.

Revision ID: 0008_create_trip_recommendation_sessions
Revises: 0007_create_trip_memories
"""
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0008_create_trip_recommendation_sessions"
down_revision: str | None = "0007_create_trip_memories"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table("trip_recommendation_sessions", sa.Column("id", sa.Uuid(), primary_key=True), sa.Column("trip_id", sa.Uuid(), sa.ForeignKey("trips.id"), nullable=False), sa.Column("kind", sa.String(20), nullable=False), sa.Column("query", sa.String(80)), sa.Column("candidates", postgresql.JSONB(), nullable=False), sa.Column("state_revision", sa.Integer(), nullable=False), sa.Column("is_active", sa.Boolean(), nullable=False, server_default=sa.true()), sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False))
    op.create_index("ix_trip_recommendation_sessions_trip_id", "trip_recommendation_sessions", ["trip_id"])


def downgrade() -> None:
    op.drop_index("ix_trip_recommendation_sessions_trip_id", table_name="trip_recommendation_sessions")
    op.drop_table("trip_recommendation_sessions")
