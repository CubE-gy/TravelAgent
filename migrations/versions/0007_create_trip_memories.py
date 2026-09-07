"""Create Trip-scoped semantic memory.

Revision ID: 0007_create_trip_memories
Revises: 0006_add_trip_state_revision
"""
from collections.abc import Sequence
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql
from alembic import op

revision: str = "0007_create_trip_memories"
down_revision: str | None = "0006_add_trip_state_revision"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

def upgrade() -> None:
    op.create_table("trip_memories", sa.Column("id", sa.Uuid(), primary_key=True), sa.Column("trip_id", sa.Uuid(), sa.ForeignKey("trips.id"), nullable=False), sa.Column("category", sa.String(40), nullable=False), sa.Column("key", sa.String(100), nullable=False), sa.Column("value", postgresql.JSONB(), nullable=False), sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False), sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False), sa.UniqueConstraint("trip_id", "category", "key", name="uq_trip_memory_key"))
    op.create_index("ix_trip_memories_trip_id", "trip_memories", ["trip_id"])

def downgrade() -> None:
    op.drop_index("ix_trip_memories_trip_id", table_name="trip_memories")
    op.drop_table("trip_memories")
