"""Process settings. Environment variables override defaults; nothing here is secret in git."""

from __future__ import annotations

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    database_url: str = "sqlite+pysqlite:///./etl.db"
    log_level: str = "INFO"
    app_env: str = "local"
    db_pool_size: int = 5
    db_startup_retries: int = 0
    max_orders_per_request: int = 1000
