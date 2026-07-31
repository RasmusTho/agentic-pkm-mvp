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


# Every environment key resolve_runtime_database_url() reads to name a database.
# Kept as ONE tuple because callers that must decide "has this runtime named a
# database at all?" (the self-owned outbox skip predicate, #4214 D1) may not
# maintain a second, narrower key list: a predicate that reads fewer keys than
# the resolver silently classifies a real, reachable database as unconfigured.
RUNTIME_DATABASE_ENV_KEYS: tuple[str, ...] = (
    "DATABASE_URL",
    "DB_DSN",
    "PKM_DB_NAME_DEV",
    "PKM_DB_NAME_TEST",
    "PKM_DB_NAME_PROD",
    "POSTGRES_USER",
    "POSTGRES_PASSWORD",
    "PKM_DB_HOST",
    "PKM_DB_PORT",
)


def runtime_database_is_named(env: Mapping[str, str]) -> bool:
    """Whether the environment names a database at all.

    ``False`` means every value :func:`resolve_runtime_database_url` would use
    is a built-in default, so the DSN it returns is the compose-shaped fallback
    (``postgresql+psycopg://app:app@db:5432/app``) nobody asked for — not an
    operator-named database.
    """
    return any(_clean(env, key) for key in RUNTIME_DATABASE_ENV_KEYS)


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


def explicit_runtime_database_url(env: Mapping[str, str]) -> str | None:
    """The DSN this runtime has explicitly named, or ``None`` when it named none.

    This is :func:`resolve_runtime_database_url` with its unconditional fallback
    made visible: when the answer is not ``None`` it is *byte-identical* to what
    ``resolve_runtime_database_url(env)`` returns, so a caller deciding whether
    a connection would reach an operator-named database and the connection
    itself cannot disagree.

    Motivation (#4214 D1): ``conn_rw()`` resolves through
    ``resolve_runtime_database_url``, which never returns an empty string. A
    caller that predicted "no database is configured" from ``DATABASE_URL`` /
    ``DB_DSN`` alone was therefore narrower than the connection it stood in
    for — a runtime naming its database through ``PKM_DB_HOST`` /
    ``PKM_DB_NAME_*`` / ``POSTGRES_*`` would have connected successfully while
    the predicate called it unconfigured.
    """
    if not runtime_database_is_named(env):
        return None
    return resolve_runtime_database_url(env)


__all__ = [
    "RUNTIME_DATABASE_ENV_KEYS",
    "default_database_name",
    "explicit_runtime_database_url",
    "resolve_runtime_database_url",
    "runtime_database_is_named",
]
