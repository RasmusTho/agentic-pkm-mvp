def __getattr__(name):
    if name in {"engine", "SessionLocal", "Base", "conn_ro", "conn_rw", "ensure_schema"}:
        from . import sqlalchemy as _sa
        return getattr(_sa, name)
    if name in {"resolve_dsn"}:
        from .dsn import resolve_dsn
        return resolve_dsn
    raise AttributeError(name)

__all__ = ("engine", "SessionLocal", "Base", "conn_ro", "conn_rw", "ensure_schema", "resolve_dsn")
