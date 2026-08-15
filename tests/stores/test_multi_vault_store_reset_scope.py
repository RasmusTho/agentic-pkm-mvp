"""Per-binding store reset contract for MVR-05A3 (#4577)."""

from __future__ import annotations

import uuid

import psycopg
import pytest

from tests.integration.test_multi_vault_projection_isolation import (
    migrated_store_dsn as _migrated_store_dsn,
)
from tests.migrations.test_multi_vault_ingest_projection_keys import (
    scratch_db_factory,  # noqa: F401 - pytest fixture export
)


migrated_store_dsn = _migrated_store_dsn
pytestmark = pytest.mark.pg


def test_reset_for_one_binding_leaves_other_binding_rows_intact(
    migrated_store_dsn: str,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    object_id = uuid.uuid4()
    set_id = uuid.uuid4()
    with psycopg.connect(migrated_store_dsn) as conn:
        conn.execute(
            "INSERT INTO sets (id, name) VALUES (%s, 'shared-reset-set')",
            (set_id,),
        )
        for binding in ("binding-a", "binding-b"):
            chunk_id = uuid.uuid4()
            conn.execute(
                "INSERT INTO store_objects "
                "(vault_binding_id, object_id, kind, payload) "
                "VALUES (%s, %s, 'note', '{}'::jsonb)",
                (binding, object_id),
            )
            conn.execute(
                "INSERT INTO store_vector_index "
                "(vault_binding_id, object_id, kind, payload, embedding, dim, model) "
                "VALUES (%s, %s, 'note', '{}'::jsonb, "
                "ARRAY[1.0]::double precision[], 1, 'm')",
                (binding, object_id),
            )
            conn.execute(
                "INSERT INTO store_relations "
                "(vault_binding_id, src_id, dst_id, rel) VALUES (%s, %s, %s, 'self')",
                (binding, object_id, object_id),
            )
            conn.execute(
                "INSERT INTO store_relation_memberships "
                "(vault_binding_id, src_id, rel, value) VALUES (%s, %s, 'tag', 'shared')",
                (binding, object_id),
            )
            conn.execute(
                "INSERT INTO vector_index_meta (vault_binding_id, id, identity_json) "
                "VALUES (%s, 1, '{}')",
                (binding,),
            )
            conn.execute(
                "INSERT INTO chunks "
                "(id, vault_binding_id, object_id, idx, offset_start, offset_end, text) "
                "VALUES (%s, %s, %s, 0, 0, 1, 'x')",
                (chunk_id, binding, object_id),
            )
            conn.execute(
                "INSERT INTO embeddings "
                "(id, vault_binding_id, object_id, chunk_id, provider, dim, embedding) "
                "VALUES (%s, %s, %s, %s, 'mock', 1, '[1]'::vector)",
                (uuid.uuid4(), binding, object_id, chunk_id),
            )
            conn.execute(
                "INSERT INTO relations "
                "(id, vault_binding_id, src_id, dst_id, type) "
                "VALUES (%s, %s, %s, %s, 'self')",
                (uuid.uuid4(), binding, object_id, object_id),
            )
            conn.execute(
                "INSERT INTO membership "
                "(id, vault_binding_id, object_id, set_id) VALUES (%s, %s, %s, %s)",
                (uuid.uuid4(), binding, object_id, set_id),
            )
            conn.execute(
                "INSERT INTO decisions (vault_binding_id, object_id, key, value) "
                "VALUES (%s, %s, 'review', '{}'::jsonb)",
                (binding, object_id),
            )

    from app.stores import pg

    monkeypatch.setattr(pg, "_TABLES_READY", False)
    pg.truncate_pg_tables(vault_binding_id="binding-b")

    with psycopg.connect(migrated_store_dsn) as conn:
        for table in (
            "store_objects",
            "store_vector_index",
            "store_relations",
            "store_relation_memberships",
            "vector_index_meta",
            "chunks",
            "embeddings",
            "relations",
            "membership",
        ):
            assert conn.execute(
                f"SELECT count(*) FROM {table} WHERE vault_binding_id = 'binding-a'"
            ).fetchone() == (1,), table
            assert conn.execute(
                f"SELECT count(*) FROM {table} WHERE vault_binding_id = 'binding-b'"
            ).fetchone() == (0,), table

        receipts = conn.execute(
            "SELECT vault_binding_id, object_id FROM decisions ORDER BY vault_binding_id"
        ).fetchall()
    assert receipts == [("binding-a", object_id), ("binding-b", None)]
