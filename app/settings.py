from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    database_url: str = "postgresql+psycopg://app:app@db:5432/appdb"
    app_version: str = "0.1.0"
    api_key: str | None = None
    rate_limit_enabled: bool = False
    rate_limit_redis_url: str | None = None
    rate_limit_default: str = "60/minute"
    metrics_enabled: bool = False
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

    class Config:
        env_file = ".env"
        env_file_encoding = "utf-8"


settings = Settings()
