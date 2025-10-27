import os
import typing as t
import psycopg

def resolve_dsn(conninfo: t.Optional[str] = None) -> str:
    url = (conninfo or os.getenv("DATABASE_URL", "")).strip()
    if url.startswith("postgresql+psycopg://"):
        url = "postgresql://" + url.split("postgresql+psycopg://", 1)[1]
    return url

def dsn() -> str:
    return resolve_dsn()

def connect(conninfo: t.Optional[str] = None, **kwargs):
    return psycopg.connect(resolve_dsn(conninfo), **kwargs)
