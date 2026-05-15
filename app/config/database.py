from __future__ import annotations

from collections.abc import Mapping
from urllib.parse import quote

from app.config.environment import ENV_DEV, ENV_PROD, ENV_TEST, active_environment


def _clean(env: Mapping[str, str], key: str) -> str:
    return str(env.get(key, "") or "").strip()


def default_database_name(env_name: str) -> str:
    if env_name == ENV_DEV:
        return "app_dev"
    if env_name == ENV_TEST:
        return "app_test"
    if env_name == ENV_PROD:
        return "app"
    return "app"


def resolve_runtime_database_url(env: Mapping[str, str]) -> str:
    explicit = _clean(env, "DATABASE_URL") or _clean(env, "DB_DSN")
    if explicit:
        return explicit

    env_name = active_environment(env)
    if env_name == ENV_DEV:
        db_name = _clean(env, "PKM_DB_NAME_DEV") or default_database_name(env_name)
    elif env_name == ENV_TEST:
        db_name = _clean(env, "PKM_DB_NAME_TEST") or default_database_name(env_name)
    else:
        db_name = _clean(env, "PKM_DB_NAME_PROD") or default_database_name(env_name)

    user = _clean(env, "POSTGRES_USER") or "app"
    password = _clean(env, "POSTGRES_PASSWORD") or "app"
    host = _clean(env, "PKM_DB_HOST") or "db"
    port = _clean(env, "PKM_DB_PORT") or "5432"

    return f"postgresql+psycopg://{quote(user)}:{quote(password)}@{host}:{port}/{db_name}"


__all__ = ["default_database_name", "resolve_runtime_database_url"]
