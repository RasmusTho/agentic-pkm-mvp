"""SQLite schema for the minimal BuilderOps Vault store."""

SCHEMA_VERSION = 1

DDL_STATEMENTS = [
    """
    CREATE TABLE IF NOT EXISTS builderops_records (
        id TEXT PRIMARY KEY,
        object_type TEXT NOT NULL,
        authority_class TEXT NOT NULL,
        lifecycle_state TEXT NOT NULL,
        promotion_status TEXT NOT NULL,
        created_at TEXT NOT NULL,
        updated_at TEXT NOT NULL,
        created_by TEXT NOT NULL,
        summary TEXT NOT NULL,
        source_refs TEXT NOT NULL,
        payload TEXT NOT NULL
    )
    """,
    """
    CREATE INDEX IF NOT EXISTS idx_builderops_records_type_created
    ON builderops_records(object_type, created_at)
    """,
    """
    CREATE TABLE IF NOT EXISTS builderops_meta (
        key TEXT PRIMARY KEY,
        value TEXT NOT NULL
    )
    """,
]
