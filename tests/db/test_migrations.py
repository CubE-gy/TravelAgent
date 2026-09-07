from pathlib import Path

import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy import text

from app.core.config import Settings
from app.db.session import create_database_engine


PROJECT_ROOT = Path(__file__).resolve().parents[2]
HEAD_REVISION = "0007_create_trip_memories"


def _alembic_config(database_url: str) -> Config:
    config = Config(str(PROJECT_ROOT / "alembic.ini"))
    config.set_main_option("sqlalchemy.url", database_url)
    return config


@pytest.mark.integration
def test_migration_baseline_applies_to_each_database() -> None:
    settings = Settings()

    for database_url in (settings.database_url, settings.test_database_url):
        command.upgrade(_alembic_config(str(database_url)), "head")

        engine = create_database_engine(str(database_url))
        try:
            with engine.connect() as connection:
                revision = connection.execute(
                    text("SELECT version_num FROM alembic_version")
                ).scalar_one()
                trip_state_revision_column_exists = connection.execute(
                    text(
                        "SELECT EXISTS ("
                        "SELECT 1 FROM information_schema.columns "
                        "WHERE table_name = 'trip_states' AND column_name = 'revision'"
                        ")"
                    )
                ).scalar_one()
                trip_memories_exists = connection.execute(
                    text("SELECT to_regclass('public.trip_memories') IS NOT NULL")
                ).scalar_one()
        finally:
            engine.dispose()

        assert revision == HEAD_REVISION
        assert trip_state_revision_column_exists is True
        assert trip_memories_exists is True
