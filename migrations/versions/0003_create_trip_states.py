"""Create persistent current TripState records.

Revision ID: 0003_create_trip_states
Revises: 0002_create_trips
Create Date: 2026-08-26
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql


revision: str = "0003_create_trip_states"
down_revision: str | None = "0002_create_trips"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Create one current state record for each Trip."""
    op.create_table(
        "trip_states",
        sa.Column("trip_id", sa.Uuid(), nullable=False),
        sa.Column("state", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(["trip_id"], ["trips.id"]),
        sa.PrimaryKeyConstraint("trip_id"),
    )


def downgrade() -> None:
    """Remove persistent current TripState records."""
    op.drop_table("trip_states")
