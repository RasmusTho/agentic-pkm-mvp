from __future__ import annotations

from pathlib import Path

import tomllib

from app.builderops.control_plane.migrations import AUTHORITY_EPOCH, MIGRATIONS, SCHEMA_VERSION


def test_builderops_migrations_do_not_use_product_lineage() -> None:
    migration_dir = Path("app/builderops/control_plane/migrations")
    product_lineage = Path("app/alembic")
    assert migration_dir.is_dir()
    assert product_lineage not in migration_dir.parents
    assert MIGRATIONS
    assert all(path.parent == migration_dir.resolve() for path in MIGRATIONS)
    assert SCHEMA_VERSION == len(MIGRATIONS)
    assert AUTHORITY_EPOCH == 1
    sql = "\n".join(path.read_text(encoding="utf-8") for path in MIGRATIONS)
    assert "alembic_version" not in sql
    assert "builderops_schema_migrations" in sql
    packaging = tomllib.loads(Path("pyproject.toml").read_text(encoding="utf-8"))
    package_data = packaging["tool"]["setuptools"]["package-data"]
    assert package_data["app.builderops.control_plane.migrations"] == ["*.sql"]
