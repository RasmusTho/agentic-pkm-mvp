"""SQLite schema DDL for the dispatcher MVP."""

from __future__ import annotations

SCHEMA_VERSION = 3

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
        stage TEXT NOT NULL,
        request_json TEXT NOT NULL,
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
