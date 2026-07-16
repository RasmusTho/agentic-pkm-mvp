"""Fail-closed production store selection and explicit legacy adapter seam."""

from __future__ import annotations

from collections.abc import Mapping
from pathlib import Path

from app.builderops.control_plane.store import PostgresBuilderOpsStore


class ExplicitSqliteAdapter:
    """Marker for migration/test injection; never selected by production config."""

    def __init__(self, path: Path) -> None:
        self.path = Path(path)

    def open_source(self):  # type: ignore[no-untyped-def]
        """Construct the legacy reader only after explicit adapter injection."""
        from app.builderops.store import SqliteBuilderOpsStore

        return SqliteBuilderOpsStore(self.path, read_only=True)


def production_store(env: Mapping[str, str]) -> PostgresBuilderOpsStore:
    dsn = env.get("BUILDEROPS_DATABASE_URL", "").strip()
    if not dsn:
        raise RuntimeError("BUILDEROPS_DATABASE_URL is required for production BuilderOps")
    if not dsn.startswith(("postgresql://", "postgres://", "postgresql+psycopg://")):
        raise RuntimeError(
            "BuilderOps production authority must be PostgreSQL; SQLite fallback is forbidden"
        )
    return PostgresBuilderOpsStore(dsn)
