"""SQLite schema for the BuilderOps Vault store."""

SCHEMA_VERSION = 2

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
    """
    CREATE TABLE IF NOT EXISTS builderops_idempotency_keys (
        key TEXT PRIMARY KEY,
        operation TEXT NOT NULL,
        request_hash TEXT NOT NULL,
        result_record_id TEXT NOT NULL,
        response_payload TEXT NOT NULL,
        created_by TEXT NOT NULL,
        created_at TEXT NOT NULL
    )
    """,
    """
    CREATE INDEX IF NOT EXISTS idx_builderops_idempotency_result
    ON builderops_idempotency_keys(result_record_id)
    """,
    """
    CREATE TABLE IF NOT EXISTS builderops_leases (
        resource_id TEXT PRIMARY KEY,
        lease_id TEXT NOT NULL UNIQUE,
        actor TEXT NOT NULL,
        acquired_at TEXT NOT NULL,
        expires_at TEXT NOT NULL
    )
    """,
    """
    CREATE INDEX IF NOT EXISTS idx_builderops_leases_expires
    ON builderops_leases(expires_at)
    """,
]
