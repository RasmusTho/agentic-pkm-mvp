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
    assert statements[:4] == [
        "delete from store_vector_index",
        "delete from store_relation_memberships",
        "delete from store_relations",
        "delete from vector_index_meta",
    ]
    explicit_consumers = statements[4]
    for table in ("chunks", "embeddings", "relations", "membership"):
        assert f"delete from public.{table}" in explicit_consumers
    assert statements[5] == "delete from store_objects"
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
                "INSERT INTO store_objects (object_id, kind, payload) VALUES (%s, 'note', '{}'::jsonb)"
                " ON CONFLICT (object_id) DO NOTHING",
                (object_id,),
            )
            cur.execute(
                "INSERT INTO chunks (id, object_id, idx, offset_start, offset_end, text)"
                " VALUES (%s, %s, 0, 0, 1, 'x')",
                (str(uuid4()), object_id),
            )
            cur.execute(
                "INSERT INTO decisions (object_id, agent, kind, key, value)"
                " VALUES (%s, 'truncate-reset-test', 'k', 'key', '{}'::jsonb)",
                (object_id,),
            )
        conn.commit()

    pg.truncate_pg_tables()

    with pg._connect() as conn:
        with conn.cursor() as cur:
            cur.execute("SELECT count(*) AS n FROM chunks WHERE object_id = %s", (object_id,))
            row = cur.fetchone()
            chunk_count = row["n"] if isinstance(row, dict) else row[0]
            cur.execute(
                "SELECT count(*) AS n FROM decisions"
                " WHERE agent = 'truncate-reset-test' AND object_id IS NULL"
            )
            row = cur.fetchone()
            surviving = row["n"] if isinstance(row, dict) else row[0]
            cur.execute("DELETE FROM decisions WHERE agent = 'truncate-reset-test'")
        conn.commit()
    assert chunk_count == 0
    assert surviving >= 1
