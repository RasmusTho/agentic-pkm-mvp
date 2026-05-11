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
        return False, f"postgres unreachable: {exc}"
