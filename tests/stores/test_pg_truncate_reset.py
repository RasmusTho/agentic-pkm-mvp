"""Canonical store reset must honor inbound FK semantics (#3510)."""

import os
from unittest.mock import MagicMock
from uuid import uuid4

import pytest

from app.stores import pg


def test_truncate_reset_names_canonical_fk_cascade_consumers(monkeypatch) -> None:
    conn = MagicMock()
    cur = conn.__enter__.return_value.cursor.return_value.__enter__.return_value
    monkeypatch.setattr(pg, "pg_available", lambda: True)
    monkeypatch.setattr(pg, "_ensure_tables", lambda: None)
    monkeypatch.setattr(pg, "_connect", lambda: conn)

    pg.truncate_pg_tables()

    statements = [call.args[0].lower() for call in cur.execute.call_args_list]
    assert statements == [
        "delete from store_vector_index where vault_binding_id = %s",
        "delete from store_relation_memberships where vault_binding_id = %s",
        "delete from store_relations where vault_binding_id = %s",
        "delete from vector_index_meta where vault_binding_id = %s",
        "delete from public.chunks where vault_binding_id = %s",
        "delete from public.embeddings where vault_binding_id = %s",
        "delete from public.relations where vault_binding_id = %s",
        "delete from public.membership where vault_binding_id = %s",
        "delete from store_objects where vault_binding_id = %s",
    ]
    assert all(
        call.args[1] == (pg.COMPATIBILITY_BINDING_ID,)
        for call in cur.execute.call_args_list
    )
    assert all("truncate" not in statement and "cascade" not in statement for statement in statements)


@pytest.mark.pg
def test_truncate_reset_observed_semantics_on_migrated_database() -> None:
    """Live check: cascade children are emptied, SET NULL consumers survive."""
    if not os.environ.get("DATABASE_URL"):
        pytest.skip("DATABASE_URL not set")
    object_id = str(uuid4())
    with pg._connect() as conn:
        with conn.cursor() as cur:
            cur.execute("SELECT to_regclass('public.chunks'), to_regclass('public.decisions')")
            row = cur.fetchone()
            reg = list(row.values()) if isinstance(row, dict) else list(row)
            if not all(reg):
                pytest.skip("legacy chunk/decision tables absent on this schema")
            cur.execute(
                "INSERT INTO store_objects (vault_binding_id, object_id, kind, payload) "
                "VALUES (%s, %s, 'note', '{}'::jsonb)"
                " ON CONFLICT (vault_binding_id, object_id) DO NOTHING",
                (pg.COMPATIBILITY_BINDING_ID, object_id),
            )
            cur.execute(
                "INSERT INTO chunks (id, vault_binding_id, object_id, idx, offset_start, offset_end, text)"
                " VALUES (%s, %s, %s, 0, 0, 1, 'x')",
                (str(uuid4()), pg.COMPATIBILITY_BINDING_ID, object_id),
            )
            cur.execute(
                "INSERT INTO decisions (vault_binding_id, object_id, agent, kind, key, value)"
                " VALUES (%s, %s, 'truncate-reset-test', 'k', 'key', '{}'::jsonb)",
                (pg.COMPATIBILITY_BINDING_ID, object_id),
            )
        conn.commit()

    pg.truncate_pg_tables()

    with pg._connect() as conn:
        with conn.cursor() as cur:
            cur.execute(
                "SELECT count(*) AS n FROM chunks "
                "WHERE vault_binding_id = %s AND object_id = %s",
                (pg.COMPATIBILITY_BINDING_ID, object_id),
            )
            row = cur.fetchone()
            chunk_count = row["n"] if isinstance(row, dict) else row[0]
            cur.execute(
                "SELECT count(*) AS n FROM decisions"
                " WHERE vault_binding_id = %s"
                " AND agent = 'truncate-reset-test' AND object_id IS NULL",
                (pg.COMPATIBILITY_BINDING_ID,),
            )
            row = cur.fetchone()
            surviving = row["n"] if isinstance(row, dict) else row[0]
            cur.execute(
                "DELETE FROM decisions "
                "WHERE vault_binding_id = %s AND agent = 'truncate-reset-test'",
                (pg.COMPATIBILITY_BINDING_ID,),
            )
        conn.commit()
    assert chunk_count == 0
    assert surviving >= 1
