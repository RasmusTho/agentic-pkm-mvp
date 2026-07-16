"""SQLite schema DDL for the dispatcher MVP."""

from __future__ import annotations

import sqlite3

SCHEMA_VERSION = 6

LEGACY_UNTRUSTED_VERIFICATION_STATUS = "legacy_untrusted"

VERIFICATION_V3_REQUIRED_TABLES = frozenset(
    {"verification_runs", "verification_attempts", "verification_exceptions"}
)
VERIFICATION_V3_ADDITIVE_COLUMNS = {
    "verification_runs": frozenset(
        {"current_head_sha", "verified_head_sha", "supporting_authority_json"}
    )
}
VERIFICATION_V3_REQUIRED_COLUMNS = {
    "verification_runs": frozenset(
        {
            "run_id", "idempotency_key", "contract_version", "repository",
            "pr_number", "head_sha", "current_head_sha", "verified_head_sha",
            "stage", "request_json", "supporting_authority_json", "status",
            "claimed_by", "lease_id",
            "lease_expires_at", "last_heartbeat_at", "coordinator_session_id",
            "context_pack_json", "terminal_receipt_json", "stop_reason",
            "retry_after", "created_at", "updated_at",
        }
    ),
    "verification_attempts": frozenset(
        {
            "attempt_id", "run_id", "attempt_kind", "ordinal", "session_id",
            "capability", "reasoning_effort", "context_hash", "outcome",
            "receipt_json", "created_at",
        }
    ),
    "verification_exceptions": frozenset(
        {
            "exception_id", "run_id", "failure_class", "head_sha", "packet_json",
            "created_at", "updated_at",
        }
    ),
}
VERIFICATION_V3_REQUIRED_UNIQUE_KEYS = {
    "verification_runs": (
        ("run_id",), ("idempotency_key",),
        ("repository", "pr_number", "head_sha", "stage"),
    ),
    "verification_attempts": (
        ("attempt_id",), ("run_id", "attempt_kind", "ordinal"),
    ),
    "verification_exceptions": (
        ("exception_id",), ("run_id", "failure_class", "head_sha"),
    ),
}

VERIFICATION_V4_ADDITIVE_COLUMNS = {
    "verification_runs": frozenset({"repair_budget_policy"}),
    "verification_attempts": frozenset(
        {"finding_id", "failure_domain", "mechanism_id"}
    ),
}
VERIFICATION_V5_ADDITIVE_COLUMNS = {
    "verification_runs": frozenset({"closing_authority_json"}),
}
VERIFICATION_V6_ADDITIVE_COLUMNS = {
    "verification_runs": frozenset({"legacy_recovery_audit_json"}),
}


def has_unique_key(
    conn: sqlite3.Connection, table: str, required_key: tuple[str, ...]
) -> bool:
    """Return whether ``table`` enforces exactly ``required_key``."""
    columns = conn.execute(f"PRAGMA table_info({table})").fetchall()
    primary_key = tuple(
        str(row[1])
        for row in sorted(columns, key=lambda row: int(row[5]))
        if int(row[5]) > 0
    )
    if primary_key == required_key:
        return True

    for index in conn.execute(f"PRAGMA index_list({table})").fetchall():
        if not bool(index[2]) or bool(index[4]):
            continue
        index_columns = tuple(
            str(row[2])
            for row in conn.execute(f"PRAGMA index_info({index[1]})").fetchall()
        )
        if index_columns == required_key:
            return True
    return False


def verification_v3_schema_error(
    conn: sqlite3.Connection,
    *,
    allow_additive_migration: bool = False,
) -> str | None:
    """Validate v3 audit invariants, optionally before additive head migration."""
    tables = {
        str(row[0])
        for row in conn.execute(
            "SELECT name FROM sqlite_master WHERE type = 'table'"
        ).fetchall()
    }
    missing_tables = sorted(VERIFICATION_V3_REQUIRED_TABLES - tables)
    if missing_tables:
        return f"missing dispatcher tables: {', '.join(missing_tables)}"
    for table, required in VERIFICATION_V3_REQUIRED_COLUMNS.items():
        columns = {
            str(row[1])
            for row in conn.execute(f"PRAGMA table_info({table})").fetchall()
        }
        missing_columns = required - columns
        if allow_additive_migration:
            missing_columns -= VERIFICATION_V3_ADDITIVE_COLUMNS.get(table, frozenset())
        if missing_columns:
            return (
                f"missing dispatcher columns in {table}: "
                f"{', '.join(sorted(missing_columns))}"
            )
    for table, required_keys in VERIFICATION_V3_REQUIRED_UNIQUE_KEYS.items():
        for required_key in required_keys:
            if not has_unique_key(conn, table, required_key):
                return (
                    f"missing required unique key in {table}: "
                    f"{', '.join(required_key)}"
                )
    return None


def verification_v4_schema_error(
    conn: sqlite3.Connection,
    *,
    allow_additive_migration: bool = False,
) -> str | None:
    """Validate v4 repair-budget persistence and inherited audit invariants."""
    inherited = verification_v3_schema_error(
        conn, allow_additive_migration=allow_additive_migration
    )
    if inherited is not None:
        return inherited
    for table, required in VERIFICATION_V4_ADDITIVE_COLUMNS.items():
        columns = {
            str(row[1])
            for row in conn.execute(f"PRAGMA table_info({table})").fetchall()
        }
        missing_columns = required - columns
        if allow_additive_migration:
            missing_columns = frozenset()
        if missing_columns:
            return (
                f"missing dispatcher columns in {table}: "
                f"{', '.join(sorted(missing_columns))}"
            )
    return None


def verification_v5_schema_error(
    conn: sqlite3.Connection,
    *,
    allow_additive_migration: bool = False,
) -> str | None:
    """Validate v5 exact closing-authority persistence."""
    inherited = verification_v4_schema_error(
        conn, allow_additive_migration=allow_additive_migration
    )
    if inherited is not None:
        return inherited
    for table, required in VERIFICATION_V5_ADDITIVE_COLUMNS.items():
        columns = {
            str(row[1])
            for row in conn.execute(f"PRAGMA table_info({table})").fetchall()
        }
        missing_columns = required - columns
        if allow_additive_migration:
            missing_columns = frozenset()
        if missing_columns:
            return (
                f"missing dispatcher columns in {table}: "
                f"{', '.join(sorted(missing_columns))}"
            )
    return None


def verification_v6_schema_error(
    conn: sqlite3.Connection,
    *,
    allow_additive_migration: bool = False,
) -> str | None:
    """Validate v6 same-head legacy recovery audit persistence."""
    inherited = verification_v5_schema_error(
        conn, allow_additive_migration=allow_additive_migration
    )
    if inherited is not None:
        return inherited
    for table, required in VERIFICATION_V6_ADDITIVE_COLUMNS.items():
        columns = {
            str(row[1])
            for row in conn.execute(f"PRAGMA table_info({table})").fetchall()
        }
        missing_columns = required - columns
        if allow_additive_migration:
            missing_columns = frozenset()
        if missing_columns:
            return (
                f"missing dispatcher columns in {table}: "
                f"{', '.join(sorted(missing_columns))}"
            )
    return None

DDL_STATEMENTS: tuple[str, ...] = (
    """
    CREATE TABLE IF NOT EXISTS dispatcher_tasks (
        task_id TEXT PRIMARY KEY,
        issue_number INTEGER NOT NULL,
        title TEXT NOT NULL,
        status TEXT NOT NULL,
        priority TEXT NOT NULL,
        repo TEXT NOT NULL DEFAULT '',
        source_anchor_refs TEXT NOT NULL,
        claimed_by TEXT,
        lease_id TEXT,
        lease_expires_at TEXT,
        linked_pr TEXT,
        blocked_reason TEXT,
        last_heartbeat_at TEXT,
        sync_state TEXT,
        created_at TEXT NOT NULL,
        updated_at TEXT NOT NULL
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS dispatcher_leases (
        lease_id TEXT PRIMARY KEY,
        resource TEXT NOT NULL,
        holder TEXT NOT NULL,
        ttl_seconds INTEGER NOT NULL,
        acquired_at TEXT NOT NULL,
        expires_at TEXT NOT NULL,
        heartbeat_at TEXT,
        released_at TEXT,
        release_reason TEXT
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS dispatcher_events (
        event_id TEXT PRIMARY KEY,
        timestamp TEXT NOT NULL,
        task_id TEXT NOT NULL,
        event_type TEXT NOT NULL,
        actor TEXT NOT NULL,
        lease_id TEXT,
        payload TEXT
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS dispatcher_meta (
        key TEXT PRIMARY KEY,
        value TEXT NOT NULL
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS verification_runs (
        run_id TEXT PRIMARY KEY,
        idempotency_key TEXT NOT NULL UNIQUE,
        contract_version TEXT NOT NULL,
        repository TEXT NOT NULL,
        pr_number INTEGER NOT NULL,
        head_sha TEXT NOT NULL,
        current_head_sha TEXT NOT NULL,
        verified_head_sha TEXT,
        stage TEXT NOT NULL,
        request_json TEXT NOT NULL,
        supporting_authority_json TEXT NOT NULL DEFAULT '[]',
        closing_authority_json TEXT NOT NULL DEFAULT '[]',
        legacy_recovery_audit_json TEXT,
        repair_budget_policy TEXT NOT NULL DEFAULT 'v2',
        status TEXT NOT NULL,
        claimed_by TEXT,
        lease_id TEXT,
        lease_expires_at TEXT,
        last_heartbeat_at TEXT,
        coordinator_session_id TEXT,
        context_pack_json TEXT,
        terminal_receipt_json TEXT,
        stop_reason TEXT,
        retry_after TEXT,
        created_at TEXT NOT NULL,
        updated_at TEXT NOT NULL,
        UNIQUE(repository, pr_number, head_sha, stage)
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS verification_attempts (
        attempt_id TEXT PRIMARY KEY,
        run_id TEXT NOT NULL,
        attempt_kind TEXT NOT NULL,
        ordinal INTEGER NOT NULL,
        session_id TEXT NOT NULL,
        capability TEXT NOT NULL,
        reasoning_effort TEXT NOT NULL,
        context_hash TEXT NOT NULL,
        outcome TEXT NOT NULL,
        finding_id TEXT,
        failure_domain TEXT,
        mechanism_id TEXT,
        receipt_json TEXT,
        created_at TEXT NOT NULL,
        FOREIGN KEY(run_id) REFERENCES verification_runs(run_id),
        UNIQUE(run_id, attempt_kind, ordinal)
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS verification_exceptions (
        exception_id TEXT PRIMARY KEY,
        run_id TEXT NOT NULL,
        failure_class TEXT NOT NULL,
        head_sha TEXT NOT NULL,
        packet_json TEXT NOT NULL,
        created_at TEXT NOT NULL,
        updated_at TEXT NOT NULL,
        FOREIGN KEY(run_id) REFERENCES verification_runs(run_id),
        UNIQUE(run_id, failure_class, head_sha)
    )
    """,
    "CREATE INDEX IF NOT EXISTS idx_dispatcher_events_task ON dispatcher_events(task_id)",
    "CREATE INDEX IF NOT EXISTS idx_dispatcher_leases_resource ON dispatcher_leases(resource)",
    "CREATE INDEX IF NOT EXISTS idx_verification_runs_status ON verification_runs(status)",
    "CREATE INDEX IF NOT EXISTS idx_verification_attempts_run ON verification_attempts(run_id)",
)
