import pytest
from pydantic import ValidationError

from app.core.config import Settings


def test_settings_accept_explicit_database_url() -> None:
    settings = Settings(
        _env_file=None,
        database_url="postgresql+psycopg://user:password@localhost:5432/travel_agent",
        test_database_url="postgresql+psycopg://user:password@localhost:5433/travel_agent_test",
    )

    assert settings.app_env == "development"
    assert settings.amap_web_api_key is None
    assert str(settings.database_url) == (
        "postgresql+psycopg://user:password@localhost:5432/travel_agent"
    )


def test_settings_reads_environment_variables(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("APP_ENV", "test")
    monkeypatch.setenv(
        "DATABASE_URL",
        "postgresql+psycopg://user:password@localhost:5432/travel_agent",
    )
    monkeypatch.setenv(
        "TEST_DATABASE_URL",
        "postgresql+psycopg://user:password@localhost:5433/travel_agent_test",
    )
    monkeypatch.setenv("AMAP_WEB_API_KEY", "test-amap-key")

    settings = Settings(_env_file=None)

    assert settings.app_env == "test"
    assert settings.amap_web_api_key is not None
    assert settings.amap_web_api_key.get_secret_value() == "test-amap-key"


def test_settings_loads_dotenv_file(tmp_path) -> None:
    env_file = tmp_path / ".env"
    env_file.write_text(
        "APP_ENV=test\n"
        "DATABASE_URL=postgresql+psycopg://user:password@localhost:5432/travel_agent\n"
        "TEST_DATABASE_URL=postgresql+psycopg://user:password@localhost:5433/travel_agent_test\n",
        encoding="utf-8",
    )

    settings = Settings(_env_file=env_file)

    assert settings.app_env == "test"
    assert str(settings.database_url) == (
        "postgresql+psycopg://user:password@localhost:5432/travel_agent"
    )


def test_settings_requires_database_url() -> None:
    with pytest.raises(ValidationError, match="database_url"):
        Settings(
            _env_file=None,
            test_database_url="postgresql+psycopg://user:password@localhost:5433/travel_agent_test",
        )
