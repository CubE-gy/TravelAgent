import pytest
from sqlalchemy import text

from app.core.config import Settings
from app.db.session import create_database_engine


@pytest.mark.integration
def test_development_and_test_databases_accept_connections() -> None:
    settings = Settings()

    for database_url in (settings.database_url, settings.test_database_url):
        engine = create_database_engine(str(database_url))
        try:
            with engine.connect() as connection:
                assert connection.execute(text("SELECT 1")).scalar_one() == 1
        finally:
            engine.dispose()
