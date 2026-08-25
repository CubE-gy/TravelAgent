from app.db.session import create_database_engine


def test_create_database_engine_uses_postgresql_url() -> None:
    engine = create_database_engine(
        "postgresql+psycopg://user:password@localhost:5434/travel_agent_dev"
    )

    try:
        assert engine.url.drivername == "postgresql+psycopg"
        assert engine.url.database == "travel_agent_dev"
    finally:
        engine.dispose()
