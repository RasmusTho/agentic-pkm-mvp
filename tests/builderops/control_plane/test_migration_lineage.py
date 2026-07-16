from __future__ import annotations

import pytest

pytestmark = pytest.mark.pg


def test_initialize_refuses_newer_schema_and_authority_epoch(control_plane_store, envelope) -> None:
    store = control_plane_store
    with store._connect() as conn:
        conn.execute(
            "INSERT INTO builderops_schema_migrations(version, name, checksum) "
            "VALUES (2, '0002_future.sql', 'future')"
        )
        conn.execute(
            "UPDATE builderops_authority_metadata "
            "SET authority_epoch = 2, schema_version = 2 WHERE singleton"
        )

    with pytest.raises(RuntimeError, match="newer or unknown migration version"):
        store.initialize()
    assert store.readiness() == {"authority_epoch": 2, "schema_version": 2}

    with store._connect() as conn:
        conn.execute("DELETE FROM builderops_schema_migrations WHERE version = 2")
        conn.execute(
            "UPDATE builderops_authority_metadata "
            "SET authority_epoch = 1, schema_version = 2 WHERE singleton"
        )
    with pytest.raises(RuntimeError, match="database schema is newer"):
        store.initialize()
    assert store.readiness() == {"authority_epoch": 1, "schema_version": 2}

    with store._connect() as conn:
        conn.execute(
            "UPDATE builderops_authority_metadata "
            "SET authority_epoch = 2, schema_version = 1 WHERE singleton"
        )
    with pytest.raises(RuntimeError, match="authority epoch is newer"):
        store.initialize()
    assert store.readiness() == {"authority_epoch": 2, "schema_version": 1}


@pytest.mark.parametrize(
    ("column", "value"),
    (("name", "corrupted.sql"), ("checksum", "corrupted")),
)
def test_initialize_refuses_mismatched_applied_migration_lineage(
    control_plane_store, envelope, column: str, value: str
) -> None:
    store = control_plane_store
    with store._connect() as conn:
        conn.execute(
            f"UPDATE builderops_schema_migrations SET {column} = %s WHERE version = 1",  # noqa: S608
            (value,),
        )
    with pytest.raises(RuntimeError, match="does not match this release lineage"):
        store.initialize()


def test_initialize_is_idempotent_for_exact_current_lineage(control_plane_store, envelope) -> None:
    control_plane_store.initialize()
    assert control_plane_store.readiness() == {"authority_epoch": 1, "schema_version": 1}
