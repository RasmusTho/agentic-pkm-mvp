import os
import shlex
import typing as t


from app.config.database import normalize_database_url, resolve_database_url


def resolve_dsn(conninfo: t.Optional[str] = None) -> str:
    return normalize_database_url(resolve_database_url(os.environ, conninfo, default=False), sqlalchemy=False)


def resolve_sqlalchemy_url(conninfo: t.Optional[str] = None) -> str:
    return normalize_database_url(resolve_database_url(os.environ, conninfo, default=False), sqlalchemy=True)


def dsn() -> str:
    return resolve_dsn()


def _keyword_conninfo_parts(conninfo: str) -> t.Optional[dict[str, str]]:
    if "://" in conninfo or "=" not in conninfo:
        return None
    try:
        fields = shlex.split(conninfo)
    except ValueError:
        return {}

    parts: dict[str, str] = {}
    for field in fields:
        if "=" not in field:
            return {}
        key, value = field.split("=", 1)
        if not key:
            return {}
        parts[key.lower()] = value
    return parts


def looks_like_prod_dsn(conninfo: t.Optional[str] = None) -> bool:
    """Heuristic: does this DSN point at the production database?

    Used as a safety guard by `make db-restore` so a bare restore can never
    clobber prod. Prod is identified by either:
      - the database name being exactly ``app`` (dev=``app_dev``, test=``app_test``), or
      - the host port being the prod-published port ``15432``
        (dev=``15433``, test=``15434``).

    This is intentionally conservative: it errs toward flagging ambiguous DSNs
    as prod so the restore refuses rather than silently overwriting prod data.
    """
    url = resolve_dsn(conninfo)
    if not url:
        return False

    keyword_parts = _keyword_conninfo_parts(url)
    if keyword_parts is not None:
        if not keyword_parts:
            return True
        if keyword_parts.get("dbname") == "app":
            return True
        port = keyword_parts.get("port")
        if port is not None:
            try:
                return int(port) == 15432
            except ValueError:
                return True
        return False

    if "://" not in url:
        return True

    try:
        from urllib.parse import parse_qs, urlsplit  # noqa: PLC0415

        parts = urlsplit(url)
    except Exception:
        return False

    query = parse_qs(parts.query)
    db_name = query.get("dbname", [(parts.path or "").lstrip("/").split("?", 1)[0]])[-1]
    if db_name == "app":
        return True

    try:
        port = int(query["port"][-1]) if "port" in query else parts.port
        if port == 15432:
            return True
    except ValueError:
        # Malformed port: treat as ambiguous → flag as prod (conservative).
        return True

    return False


def connect(conninfo: t.Optional[str] = None, **kwargs):
    import psycopg  # noqa: PLC0415

    return psycopg.connect(resolve_dsn(conninfo), **kwargs)


def ping_postgres(*, timeout: float = 1.0, conninfo: t.Optional[str] = None) -> tuple[bool, str]:
    import psycopg  # noqa: PLC0415

    dsn_value = resolve_dsn(conninfo)
    if not dsn_value:
        return False, "missing dsn"
    try:
        with psycopg.connect(dsn_value, connect_timeout=timeout) as conn:
            with conn.cursor() as cur:
                cur.execute("SELECT 1")
                cur.fetchone()
        return True, "postgres reachable"
    except Exception as exc:
        return False, f"postgres unreachable ({type(exc).__name__})"
