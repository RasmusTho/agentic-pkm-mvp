from __future__ import annotations

from pathlib import Path

import pytest

from app.builderops.control_plane import (
    ExplicitSqliteAdapter,
    PostgresBuilderOpsStore,
    production_store,
)


def test_production_store_fails_closed_without_postgres(tmp_path: Path) -> None:
    with pytest.raises(RuntimeError, match="BUILDEROPS_DATABASE_URL"):
        production_store({})
    with pytest.raises(RuntimeError, match="PostgreSQL"):
        production_store({"BUILDEROPS_DATABASE_URL": str(tmp_path / "builderops.sqlite3")})

    store = production_store({"BUILDEROPS_DATABASE_URL": "postgresql://user:pass@db/builderops"})
    assert isinstance(store, PostgresBuilderOpsStore)
    assert not (tmp_path / "builderops.sqlite3").exists()
    adapter = ExplicitSqliteAdapter(tmp_path / "migration-source.sqlite3")
    assert adapter.path.name == "migration-source.sqlite3"
