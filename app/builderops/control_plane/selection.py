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


def database_environment(env: Mapping[str, str]) -> dict[str, str]:
    """Resolve the BuilderOps DSN from exactly one direct or secret-file source."""
    resolved = dict(env)
    direct = env.get("BUILDEROPS_DATABASE_URL", "").strip()
    secret_file = env.get("BUILDEROPS_DATABASE_URL_FILE", "").strip()
    if direct and secret_file:
        raise RuntimeError(
            "configure exactly one of BUILDEROPS_DATABASE_URL or BUILDEROPS_DATABASE_URL_FILE"
        )
    if secret_file:
        try:
            direct = Path(secret_file).read_text(encoding="utf-8").strip()
        except OSError as exc:
            raise RuntimeError("BuilderOps database secret is unavailable") from exc
        if not direct:
            raise RuntimeError("BuilderOps database secret is empty")
        resolved["BUILDEROPS_DATABASE_URL"] = direct
    return resolved


def production_store(env: Mapping[str, str]) -> PostgresBuilderOpsStore:
    dsn = env.get("BUILDEROPS_DATABASE_URL", "").strip()
    if not dsn:
        raise RuntimeError("BUILDEROPS_DATABASE_URL is required for production BuilderOps")
    if not dsn.startswith(("postgresql://", "postgres://", "postgresql+psycopg://")):
        raise RuntimeError(
            "BuilderOps production authority must be PostgreSQL; SQLite fallback is forbidden"
        )
    return PostgresBuilderOpsStore(dsn)
