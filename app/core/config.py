from functools import lru_cache

from typing import Literal

from pydantic import PostgresDsn, SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Validated runtime configuration loaded from environment variables."""

    app_env: str = "development"
    database_url: PostgresDsn
    test_database_url: PostgresDsn
    amap_web_api_key: SecretStr | None = None
    frontend_origins: list[str] = ["http://localhost:5173"]
    llm_provider: Literal["mock", "real"] = "mock"
    llm_api_key: SecretStr | None = None
    llm_base_url: str = "https://api.yhlxj.ai/v1"
    llm_model: str | None = None

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )


@lru_cache
def get_settings() -> Settings:
    """Return the process-wide validated application configuration."""
    return Settings()
