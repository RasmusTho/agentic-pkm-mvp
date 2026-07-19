"""Canonical store reset must honor inbound FK semantics (#3510)."""

from unittest.mock import MagicMock

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
