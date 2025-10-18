from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    database_url: str = "postgresql+psycopg://app:app@db:5432/appdb"
    app_version: str = "0.1.0"
    class Config:
        env_file = ".env"
        env_file_encoding = "utf-8"

settings = Settings()
