from pathlib import Path

import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy import text

from app.core.config import Settings
from app.db.session import create_database_engine


PROJECT_ROOT = Path(__file__).resolve().parents[1]
HEAD_REVISION = "0002_create_trips"


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
        finally:
            engine.dispose()

        assert revision == HEAD_REVISION
