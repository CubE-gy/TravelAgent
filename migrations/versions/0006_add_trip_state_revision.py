"""Add a monotonic revision to each persistent TripState.

Revision ID: 0006_add_trip_state_revision
Revises: 0005_create_trip_plans
Create Date: 2026-08-27
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op


revision: str = "0006_add_trip_state_revision"
down_revision: str | None = "0005_create_trip_plans"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Initialize existing state records at revision one."""
    op.add_column(
        "trip_states",
        sa.Column("revision", sa.Integer(), server_default=sa.text("1"), nullable=False),
    )


def downgrade() -> None:
    """Remove the persisted TripState revision."""
    op.drop_column("trip_states", "revision")
