"""Allow a Trip created from its first natural-language message to lack metadata.

Revision ID: 0004_allow_empty_trip_metadata
Revises: 0003_create_trip_states
Create Date: 2026-08-26
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op


revision: str = "0004_allow_empty_trip_metadata"
down_revision: str | None = "0003_create_trip_states"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.alter_column("trips", "name", existing_type=sa.String(length=200), nullable=True)
    op.alter_column("trips", "start_date", existing_type=sa.Date(), nullable=True)
    op.alter_column("trips", "end_date", existing_type=sa.Date(), nullable=True)


def downgrade() -> None:
    op.alter_column("trips", "end_date", existing_type=sa.Date(), nullable=False)
    op.alter_column("trips", "start_date", existing_type=sa.Date(), nullable=False)
    op.alter_column("trips", "name", existing_type=sa.String(length=200), nullable=False)
