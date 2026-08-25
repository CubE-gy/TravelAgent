"""Create the Alembic migration baseline.

Revision ID: 0001_migration_baseline
Revises:
Create Date: 2026-08-25
"""

from collections.abc import Sequence

from alembic import op


revision: str = "0001_migration_baseline"
down_revision: str | None = None
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Establish the version marker before business tables are introduced."""


def downgrade() -> None:
    """Remove no schema objects; Alembic removes its version marker itself."""
