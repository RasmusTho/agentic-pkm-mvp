from __future__ import annotations

from collections.abc import Mapping
import os
import stat
from urllib.parse import quote, urlencode

from app.config.environment import ENV_DEV, ENV_PROD, ENV_TEST, active_environment


# Image/producer compatibility marker for governed Linux channel deployment.
DATABASE_FILE_CREDENTIAL_PROTOCOL = 1


class DatabaseCredentialError(RuntimeError):
    def __init__(self) -> None:
        super().__init__("database credential configuration refused")


class _FileResolvedURL(str):
    """In-process resolver result; environment strings never carry this provenance."""


def credential_free_database_fields(value: str) -> dict[str, str]:
    """Validate external conninfo without returning a provider/parser exception."""
    from psycopg.conninfo import conninfo_to_dict

    try:
        fields = conninfo_to_dict(value.replace("postgresql+psycopg://", "postgresql://", 1))
    except Exception:
        raise DatabaseCredentialError() from None
    if any(key in fields for key in ("password", "passfile", "service", "servicefile", "sslpassword")):
        raise DatabaseCredentialError()
    return fields


def _file_password(path: str) -> str:
    descriptor = None
    try:
        if not path or not os.path.isabs(path):
            raise DatabaseCredentialError()
        descriptor = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
        info = os.fstat(descriptor)
        if not stat.S_ISREG(info.st_mode) or info.st_size > 65536:
            raise DatabaseCredentialError()
        value = os.read(descriptor, 65537).decode("utf-8", errors="strict")
        if not value or not all(char.isprintable() for char in value):
            raise DatabaseCredentialError()
        return value
    except Exception:
        raise DatabaseCredentialError() from None
    finally:
        if descriptor is not None:
            os.close(descriptor)


def resolve_database_url(env: Mapping[str, str], conninfo: str | None = None, *, default: bool = True) -> str:
    """The single file-aware boundary for runtime, SQLAlchemy and direct clients.

    Only a resolver-produced object is idempotent. Converting it to a plain string
    (e.g. an environment roundtrip) deliberately loses its trusted provenance.
    """
    if isinstance(conninfo, _FileResolvedURL):
        return conninfo
    if "DATABASE_PASSWORD_FILE" not in env:
        if conninfo:
            return conninfo.strip()
        if not default and not (_clean(env, "DATABASE_URL") or _clean(env, "DB_DSN")):
            return ""
        return _legacy_runtime_database_url(env)
    if any(_clean(env, key) for key in ("POSTGRES_PASSWORD", "PGPASSWORD", "PGPASSFILE", "PGSERVICE", "PGSERVICEFILE")):
        raise DatabaseCredentialError()
    # Reject both overrides, even when precedence would hide one of them.
    for key in ("DATABASE_URL", "DB_DSN"):
        if _clean(env, key):
            credential_free_database_fields(_clean(env, key))
    explicit = conninfo or _clean(env, "DATABASE_URL") or _clean(env, "DB_DSN")
    fields = credential_free_database_fields(explicit) if explicit else {}
    env_name = active_environment(env)
    name_key = {ENV_DEV: "PKM_DB_NAME_DEV", ENV_TEST: "PKM_DB_NAME_TEST"}.get(env_name, "PKM_DB_NAME_PROD")
    fields.setdefault("dbname", _clean(env, name_key) or default_database_name(env_name))
    fields.setdefault("user", _clean(env, "POSTGRES_USER") or "app")
    fields.setdefault("host", _clean(env, "PKM_DB_HOST") or "db")
    fields.setdefault("port", _clean(env, "PKM_DB_PORT") or "5432")
    password = _file_password(_clean(env, "DATABASE_PASSWORD_FILE"))
    # Put connection fields in the query to preserve sockets, multi-host values,
    # escaped database names, TLS and other libpq options without a second parser.
    fields["password"] = password
    return _FileResolvedURL("postgresql+psycopg:///?" + urlencode(fields, quote_via=quote))


def normalize_database_url(value: str, *, sqlalchemy: bool) -> str:
    normalized = value.replace("postgresql+psycopg://", "postgresql://", 1)
    if sqlalchemy:
        normalized = normalized.replace("postgresql://", "postgresql+psycopg://", 1)
    return _FileResolvedURL(normalized) if isinstance(value, _FileResolvedURL) else normalized


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
    "DATABASE_PASSWORD_FILE",
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
    return "DATABASE_PASSWORD_FILE" in env or any(_clean(env, key) for key in RUNTIME_DATABASE_ENV_KEYS)


def resolve_runtime_database_url(env: Mapping[str, str]) -> str:
    return resolve_database_url(env)


def _legacy_runtime_database_url(env: Mapping[str, str]) -> str:
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
