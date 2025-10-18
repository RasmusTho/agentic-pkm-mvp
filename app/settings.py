from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    database_url: str = "postgresql+psycopg://app:app@db:5432/appdb"
    app_version: str = "0.1.0"
    api_key: str | None = None
    rate_limit_enabled: bool = False
    rate_limit_redis_url: str | None = None
    rate_limit_default: str = "60/minute"
    metrics_enabled: bool = False
    class Config:
        env_file = ".env"
        env_file_encoding = "utf-8"

settings = Settings()
