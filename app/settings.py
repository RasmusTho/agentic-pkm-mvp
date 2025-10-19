from __future__ import annotations

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    db_dsn: str = "postgresql+psycopg://app:app@postgres:5432/app"
    vector_backend: str = "pgvector"
    embed_model: str = "openai/text-embedding-3-large"

    app_version: str = "0.1.0"
    api_key: str | None = None
    rate_limit_enabled: bool = False
    rate_limit_redis_url: str | None = None
    rate_limit_default: str = "60/minute"
    metrics_enabled: bool = False

    # Legacy fields retained for compatibility with ingest/watch tooling
    vault_dir: str = (
        "/Users/rasmus/Library/Mobile Documents/iCloud~md~obsidian/Documents/" "Mimers valv"
    )
    chunk_size: int = 800
    chunk_overlap: int = 120
    watch_dir: str = "/Users/rasmus/Library/Mobile Documents/com~apple~CloudDocs/" "watchfolder"
    processed_dir: str = (
        "/Users/rasmus/Library/Mobile Documents/com~apple~CloudDocs/watchfolder/" "processed"
    )
    inbox_subdir: str = "@Inbox"
    staging_db_path: str = "storage/staging.duckdb"

    @property
    def database_url(self) -> str:
        return self.db_dsn


settings = Settings()
