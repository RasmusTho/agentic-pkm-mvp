import os
import typing as t


def resolve_dsn(conninfo: t.Optional[str] = None) -> str:
    url = (conninfo or os.getenv("DATABASE_URL") or os.getenv("DB_DSN") or "").strip()
    if url.startswith("postgresql+psycopg://"):
        url = "postgresql://" + url.split("postgresql+psycopg://", 1)[1]
    return url


def resolve_sqlalchemy_url(conninfo: t.Optional[str] = None) -> str:
    url = (conninfo or os.getenv("DATABASE_URL") or os.getenv("DB_DSN") or "").strip()
    if not url:
        return ""
    if url.startswith("postgresql+psycopg://"):
        return url
    if url.startswith("postgresql://"):
        return "postgresql+psycopg://" + url.split("postgresql://", 1)[1]
    return url


def dsn() -> str:
    return resolve_dsn()


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
    try:
        from urllib.parse import urlsplit  # noqa: PLC0415

        parts = urlsplit(url)
    except Exception:
        return False

    db_name = (parts.path or "").lstrip("/").split("?", 1)[0]
    if db_name == "app":
        return True

    try:
        if parts.port == 15432:
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
