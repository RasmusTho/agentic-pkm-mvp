from __future__ import annotations

import os
from importlib import import_module

from pydantic_settings import BaseSettings, SettingsConfigDict


_VALID_BOOL_ENV_VALUES = {"1", "true", "yes", "on", "0", "false", "no", "off"}


def _normalize_bool_env(name: str) -> None:
    raw = os.environ.get(name)
    if raw is None:
        return
    if raw.strip().lower() in _VALID_BOOL_ENV_VALUES:
        return
    os.environ[name] = "false"


_normalize_bool_env("DEBUG")


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    db_dsn: str = "postgresql+psycopg://app:app@postgres:5432/app"
    vector_backend: str = "pgvector"
    embed_model: str = "openai/text-embedding-3-large"
    embed_dim: int = 1536
    store_backend: str = "memory"

    app_version: str = "0.1.0"
    debug: bool = False
    api_key: str | None = None
    rate_limit_enabled: bool = False
    rate_limit_redis_url: str | None = None
    rate_limit_default: str = "60/minute"
    metrics_enabled: bool = False
    agent_config_path: str = "config/agent.yaml"

    # Compatibility fields retained for older ingest/watch tooling.
    vault_dir: str = "vault"
    chunk_size: int = 800
    chunk_overlap: int = 120
    watch_dir: str = "watchfolder"
    processed_dir: str = "watchfolder/processed"
    staging_db_path: str = "storage/staging.duckdb"

    @property
    def database_url(self) -> str:
        return self.db_dsn

    @property
    def DATABASE_URL(self) -> str:
        return self.database_url

    @property
    def DEBUG(self) -> bool:
        return self.debug

    @property
    def psycopg_dsn(self) -> str:
        resolver = import_module("app.db.dsn").resolve_dsn
        return resolver(self.db_dsn)


settings = Settings()

__all__ = ["Settings", "settings"]
