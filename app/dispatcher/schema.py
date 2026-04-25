"""SQLite schema DDL for the dispatcher MVP."""

from __future__ import annotations

SCHEMA_VERSION = 1

DDL_STATEMENTS: tuple[str, ...] = (
    """
    CREATE TABLE IF NOT EXISTS dispatcher_tasks (
        task_id TEXT PRIMARY KEY,
        issue_number INTEGER NOT NULL,
        title TEXT NOT NULL,
        status TEXT NOT NULL,
        priority TEXT NOT NULL,
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
    "CREATE INDEX IF NOT EXISTS idx_dispatcher_events_task ON dispatcher_events(task_id)",
    "CREATE INDEX IF NOT EXISTS idx_dispatcher_leases_resource ON dispatcher_leases(resource)",
)
