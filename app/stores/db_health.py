from __future__ import annotations

from typing import Optional, Tuple

from app.db.dsn import ping_postgres as _ping_postgres, resolve_dsn as _resolve_dsn


def resolve_dsn() -> str:
    return _resolve_dsn()


def ping_postgres(*, timeout: float = 1.0, conninfo: Optional[str] = None) -> Tuple[bool, str]:
    return _ping_postgres(timeout=timeout, conninfo=conninfo)
