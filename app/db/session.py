from functools import lru_cache
from collections.abc import Generator

from sqlalchemy import create_engine
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session, sessionmaker

from app.core.config import get_settings


def create_database_engine(database_url: str) -> Engine:
    """Create a PostgreSQL engine without opening a connection yet."""
    return create_engine(database_url, pool_pre_ping=True)


@lru_cache
def get_engine() -> Engine:
    """Return the process-wide engine for the development database."""
    return create_database_engine(str(get_settings().database_url))


def get_session_factory() -> sessionmaker[Session]:
    """Return a factory that creates isolated database sessions."""
    return sessionmaker(bind=get_engine(), expire_on_commit=False)


def get_db() -> Generator[Session, None, None]:
    """Provide one database session for an API request."""
    session = get_session_factory()()
    try:
        yield session
    finally:
        session.close()
