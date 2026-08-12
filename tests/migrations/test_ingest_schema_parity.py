from app.stores.pg import _MIGRATION_OWNED_AUTOCREATE_SQL


def test_ingest_tables_match_migration_and_autocreate() -> None:
    schema = {name: "\n".join(statements) for name, statements in _MIGRATION_OWNED_AUTOCREATE_SQL}
    assert "PRIMARY KEY (vault_binding_id, id)" in schema["membership"]
    assert "FOREIGN KEY (vault_binding_id, chunk_id)" in schema["embeddings"]
    assert "UNIQUE (vault_binding_id, id)" in schema["chunks"]
