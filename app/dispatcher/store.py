"""SQLite-backed dispatcher store.

The store is intentionally narrow: persist task, lease, and event rows behind
an interface so a Postgres implementation can replace it later without
rewriting callers. Queue selection and claim lifecycle are out of scope for the
foundation slice.
"""

from __future__ import annotations

import json
import sqlite3
from pathlib import Path
from typing import Any, Protocol

from app.dispatcher.events import JsonlEventWriter
from app.dispatcher.models import EventRecord, LeaseRecord, TaskRecord
from app.dispatcher.schema import (
    DDL_STATEMENTS,
    SCHEMA_VERSION,
    verification_v3_schema_error,
)


class DispatcherStore(Protocol):
    def initialize(self) -> None: ...
    def upsert_task(self, task: TaskRecord) -> None: ...
    def get_task(self, task_id: str) -> TaskRecord | None: ...
    def upsert_lease(self, lease: LeaseRecord) -> None: ...
    def get_lease(self, lease_id: str) -> LeaseRecord | None: ...
    def append_event(self, event: EventRecord) -> None: ...
    def list_tasks(
        self, status: str | None = None, repo: str | None = None
    ) -> list[TaskRecord]: ...
    def list_events(self, task_id: str | None = None) -> list[EventRecord]: ...
    def get_meta(self, key: str) -> str | None: ...
    def set_meta(self, key: str, value: str) -> None: ...


def _dumps(value: Any) -> str | None:
    if value is None:
        return None
    return json.dumps(value, sort_keys=True, ensure_ascii=False)


def _loads(value: str | None) -> Any:
    if value is None or value == "":
        return None
    return json.loads(value)


class SqliteStore:
    """SQLite implementation of :class:`DispatcherStore`.

    Pairs with a :class:`JsonlEventWriter`; ``append_event`` writes to both so
    the SQLite row and JSONL audit line stay correlated by ``event_id``.
    """

    def __init__(
        self,
        db_path: Path,
        event_writer: JsonlEventWriter | None = None,
    ) -> None:
        self._db_path = Path(db_path)
        self._event_writer = event_writer
        self._schema_ensured = False

    @property
    def db_path(self) -> Path:
        return self._db_path

    def _connect(self) -> sqlite3.Connection:
        self._db_path.parent.mkdir(parents=True, exist_ok=True)
        conn = sqlite3.connect(self._db_path)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA foreign_keys = ON")
        if not self._schema_ensured:
            self._ensure_schema(conn)
            self._schema_ensured = True
        return conn

    def _ensure_schema(self, conn: sqlite3.Connection) -> None:
        """Self-heal an on-disk DB created before the ``repo`` column (schema v1).

        Runs on every connection, not just :meth:`initialize` — a long-lived
        shared instance (e.g. the Demerzel dispatcher) is never re-``init``ed
        once its DB file exists, so a migration reachable only from
        ``initialize()`` would never execute against it. Cached via
        ``self._schema_ensured`` so a tight loop of many ``_connect()`` calls
        (e.g. one dispatcher ``pull`` upserting hundreds of issues) pays the
        cheap outer check once per process, not once per row.

        The migration itself (ADD COLUMN + two backfill UPDATEs) runs inside
        one explicit ``BEGIN IMMEDIATE`` transaction, committed or rolled back
        together: ``ALTER TABLE`` autocommits immediately outside an explicit
        transaction in Python's sqlite3 driver, so without this a crash
        between the ALTER and the backfill UPDATEs would permanently strand
        legacy rows with ``repo=''`` (the column-exists check has nothing
        left to detect). ``BEGIN IMMEDIATE`` also takes SQLite's write lock
        up front, so a second process racing this same migration blocks
        until the first finishes rather than hitting "duplicate column name"
        on its own ``ALTER TABLE`` — the column check is re-run *after*
        acquiring the lock (not just before) so the loser sees the column
        already present and skips straight to committing a no-op.
        """
        exists = conn.execute(
            "SELECT 1 FROM sqlite_master WHERE type='table' AND name='dispatcher_tasks'"
        ).fetchone()
        if exists is None:
            # Fresh DB: initialize() will create the table via DDL_STATEMENTS,
            # which already includes the repo column — nothing to migrate.
            return
        columns = {row["name"] for row in conn.execute("PRAGMA table_info(dispatcher_tasks)")}
        meta_exists = conn.execute(
            "SELECT 1 FROM sqlite_master WHERE type='table' AND name='dispatcher_meta'"
        ).fetchone()
        current_version = None
        if meta_exists is not None:
            row = conn.execute(
                "SELECT value FROM dispatcher_meta WHERE key='schema_version'"
            ).fetchone()
            current_version = None if row is None else str(row["value"])
        verification_columns: set[str] = set()
        verification_runs_exists = conn.execute(
            "SELECT 1 FROM sqlite_master WHERE type='table' AND name='verification_runs'"
        ).fetchone()
        if verification_runs_exists is not None:
            verification_columns = {
                row["name"] for row in conn.execute("PRAGMA table_info(verification_runs)")
            }
        verification_heads_complete = {
            "current_head_sha",
            "verified_head_sha",
        }.issubset(verification_columns)
        if "repo" in columns and current_version == str(SCHEMA_VERSION):
            schema_error = verification_v3_schema_error(
                conn, allow_additive_migration=True
            )
            if schema_error is not None:
                raise ValueError(schema_error)
            if verification_heads_complete:
                return

        # Only the original v1 layout is a supported migration source.  In
        # particular, do not turn a database written by a newer dispatcher
        # into the current schema merely because its version differs from
        # ours: opening a future database must fail loudly and leave its
        # recovery evidence untouched.  The first v1 release predated
        # dispatcher_meta, so its absence is recognized only together with
        # the v1-specific missing ``repo`` column.
        is_unversioned_v1 = current_version is None and "repo" not in columns
        if current_version not in {"1", "2", str(SCHEMA_VERSION)} and not is_unversioned_v1:
            version = "missing" if current_version is None else repr(current_version)
            raise ValueError(f"unsupported dispatcher schema_version: {version}")
        if current_version == "2" and "repo" not in columns:
            raise ValueError("dispatcher schema_version 2 is incompatible with the on-disk schema")

        conn.execute("BEGIN IMMEDIATE")
        try:
            # Re-check under the write lock: another process may have
            # completed this same migration between our check above and
            # acquiring the lock here.
            columns = {row["name"] for row in conn.execute("PRAGMA table_info(dispatcher_tasks)")}
            # The database may have changed while waiting for the write lock.
            # Re-read its version under that lock before performing any DDL.
            meta_exists = conn.execute(
                "SELECT 1 FROM sqlite_master WHERE type='table' AND name='dispatcher_meta'"
            ).fetchone()
            current_version = None
            if meta_exists is not None:
                row = conn.execute(
                    "SELECT value FROM dispatcher_meta WHERE key='schema_version'"
                ).fetchone()
                current_version = None if row is None else str(row["value"])
            is_unversioned_v1 = current_version is None and "repo" not in columns
            if current_version not in {"1", "2", str(SCHEMA_VERSION)} and not is_unversioned_v1:
                version = "missing" if current_version is None else repr(current_version)
                raise ValueError(f"unsupported dispatcher schema_version: {version}")
            if current_version == str(SCHEMA_VERSION) and "repo" in columns:
                schema_error = verification_v3_schema_error(
                    conn, allow_additive_migration=True
                )
                if schema_error is not None:
                    raise ValueError(schema_error)
                verification_columns = {
                    row["name"]
                    for row in conn.execute("PRAGMA table_info(verification_runs)")
                }
                if "current_head_sha" not in verification_columns:
                    conn.execute(
                        "ALTER TABLE verification_runs ADD COLUMN "
                        "current_head_sha TEXT NOT NULL DEFAULT ''"
                    )
                    conn.execute(
                        "UPDATE verification_runs SET current_head_sha=head_sha "
                        "WHERE current_head_sha=''"
                    )
                if "verified_head_sha" not in verification_columns:
                    conn.execute(
                        "ALTER TABLE verification_runs ADD COLUMN verified_head_sha TEXT"
                    )
                schema_error = verification_v3_schema_error(conn)
                if schema_error is not None:
                    raise ValueError(schema_error)
                conn.commit()
                return
            if current_version == str(SCHEMA_VERSION):
                raise ValueError(
                    f"dispatcher schema_version {SCHEMA_VERSION} is incompatible with the on-disk schema"
                )
            if current_version == "2" and "repo" not in columns:
                raise ValueError(
                    "dispatcher schema_version 2 is incompatible with the on-disk schema"
                )
            if "repo" not in columns:
                conn.execute("ALTER TABLE dispatcher_tasks ADD COLUMN repo TEXT NOT NULL DEFAULT ''")
                # The legacy task_id format (pre-multi-repo) had no repo
                # qualifier and was only ever produced for
                # RasmusTho/agentic-pkm-mvp pulls; backfill repo and re-key
                # task_id to the current repo-qualified form so these rows
                # don't linger as orphaned duplicates the moment a pull runs
                # under the new scheme. Also re-key the matching event-log
                # rows so historical events stay joinable to the renamed task.
                conn.execute(
                    """
                    UPDATE dispatcher_tasks
                    SET repo = 'RasmusTho/agentic-pkm-mvp',
                        task_id = 'github-RasmusTho--agentic-pkm-mvp-issue-' || issue_number
                    WHERE task_id LIKE 'github-issue-%'
                    """
                )
                conn.execute(
                    """
                    UPDATE dispatcher_events
                    SET task_id = 'github-RasmusTho--agentic-pkm-mvp-issue-'
                        || substr(task_id, length('github-issue-') + 1)
                    WHERE task_id LIKE 'github-issue-%'
                    """
                )
            for stmt in DDL_STATEMENTS:
                conn.execute(stmt)
            conn.execute(
                "INSERT OR REPLACE INTO dispatcher_meta(key, value) VALUES (?, ?)",
                ("schema_version", str(SCHEMA_VERSION)),
            )
            conn.commit()
        except Exception:
            conn.rollback()
            raise

    def initialize(self) -> None:
        with self._connect() as conn:
            for stmt in DDL_STATEMENTS:
                conn.execute(stmt)
            conn.execute(
                "INSERT OR REPLACE INTO dispatcher_meta(key, value) VALUES (?, ?)",
                ("schema_version", str(SCHEMA_VERSION)),
            )
            conn.commit()

    # ----- coordination metadata -----

    def get_meta(self, key: str) -> str | None:
        with self._connect() as conn:
            row = conn.execute(
                "SELECT value FROM dispatcher_meta WHERE key = ?", (key,)
            ).fetchone()
        return None if row is None else str(row["value"])

    def set_meta(self, key: str, value: str) -> None:
        with self._connect() as conn:
            conn.execute(
                "INSERT INTO dispatcher_meta(key, value) VALUES (?, ?) "
                "ON CONFLICT(key) DO UPDATE SET value=excluded.value",
                (key, value),
            )
            conn.commit()

    # ----- tasks -----

    def upsert_task(self, task: TaskRecord) -> None:
        with self._connect() as conn:
            conn.execute(
                """
                INSERT INTO dispatcher_tasks (
                    task_id, issue_number, title, status, priority, repo,
                    source_anchor_refs, claimed_by, lease_id, lease_expires_at,
                    linked_pr, blocked_reason, last_heartbeat_at, sync_state,
                    created_at, updated_at
                ) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
                ON CONFLICT(task_id) DO UPDATE SET
                    issue_number=excluded.issue_number,
                    title=excluded.title,
                    status=excluded.status,
                    priority=excluded.priority,
                    repo=excluded.repo,
                    source_anchor_refs=excluded.source_anchor_refs,
                    claimed_by=excluded.claimed_by,
                    lease_id=excluded.lease_id,
                    lease_expires_at=excluded.lease_expires_at,
                    linked_pr=excluded.linked_pr,
                    blocked_reason=excluded.blocked_reason,
                    last_heartbeat_at=excluded.last_heartbeat_at,
                    sync_state=excluded.sync_state,
                    updated_at=excluded.updated_at
                """,
                (
                    task.task_id,
                    task.issue_number,
                    task.title,
                    task.status,
                    task.priority,
                    task.repo,
                    _dumps(list(task.source_anchor_refs)),
                    task.claimed_by,
                    task.lease_id,
                    task.lease_expires_at,
                    task.linked_pr,
                    task.blocked_reason,
                    task.last_heartbeat_at,
                    _dumps(task.sync_state),
                    task.created_at,
                    task.updated_at,
                ),
            )
            conn.commit()

    def get_task(self, task_id: str) -> TaskRecord | None:
        with self._connect() as conn:
            row = conn.execute(
                "SELECT * FROM dispatcher_tasks WHERE task_id = ?", (task_id,)
            ).fetchone()
        if row is None:
            return None
        return TaskRecord(
            task_id=row["task_id"],
            issue_number=row["issue_number"],
            title=row["title"],
            status=row["status"],
            priority=row["priority"],
            repo=row["repo"],
            source_anchor_refs=list(_loads(row["source_anchor_refs"]) or []),
            claimed_by=row["claimed_by"],
            lease_id=row["lease_id"],
            lease_expires_at=row["lease_expires_at"],
            linked_pr=row["linked_pr"],
            blocked_reason=row["blocked_reason"],
            last_heartbeat_at=row["last_heartbeat_at"],
            sync_state=_loads(row["sync_state"]),
            created_at=row["created_at"],
            updated_at=row["updated_at"],
        )

    # ----- leases -----

    def upsert_lease(self, lease: LeaseRecord) -> None:
        with self._connect() as conn:
            conn.execute(
                """
                INSERT INTO dispatcher_leases (
                    lease_id, resource, holder, ttl_seconds, acquired_at,
                    expires_at, heartbeat_at, released_at, release_reason
                ) VALUES (?,?,?,?,?,?,?,?,?)
                ON CONFLICT(lease_id) DO UPDATE SET
                    resource=excluded.resource,
                    holder=excluded.holder,
                    ttl_seconds=excluded.ttl_seconds,
                    acquired_at=excluded.acquired_at,
                    expires_at=excluded.expires_at,
                    heartbeat_at=excluded.heartbeat_at,
                    released_at=excluded.released_at,
                    release_reason=excluded.release_reason
                """,
                (
                    lease.lease_id,
                    lease.resource,
                    lease.holder,
                    lease.ttl_seconds,
                    lease.acquired_at,
                    lease.expires_at,
                    lease.heartbeat_at,
                    lease.released_at,
                    lease.release_reason,
                ),
            )
            conn.commit()

    def get_lease(self, lease_id: str) -> LeaseRecord | None:
        with self._connect() as conn:
            row = conn.execute(
                "SELECT * FROM dispatcher_leases WHERE lease_id = ?", (lease_id,)
            ).fetchone()
        if row is None:
            return None
        return LeaseRecord(
            lease_id=row["lease_id"],
            resource=row["resource"],
            holder=row["holder"],
            ttl_seconds=row["ttl_seconds"],
            acquired_at=row["acquired_at"],
            expires_at=row["expires_at"],
            heartbeat_at=row["heartbeat_at"],
            released_at=row["released_at"],
            release_reason=row["release_reason"],
        )

    # ----- events -----

    def append_event(self, event: EventRecord) -> None:
        with self._connect() as conn:
            conn.execute(
                """
                INSERT INTO dispatcher_events (
                    event_id, timestamp, task_id, event_type, actor,
                    lease_id, payload
                ) VALUES (?,?,?,?,?,?,?)
                """,
                (
                    event.event_id,
                    event.timestamp,
                    event.task_id,
                    event.event_type,
                    event.actor,
                    event.lease_id,
                    _dumps(event.payload),
                ),
            )
            conn.commit()
        if self._event_writer is not None:
            self._event_writer.append(event)

    def list_tasks(
        self, status: str | None = None, repo: str | None = None
    ) -> list[TaskRecord]:
        clauses: list[str] = []
        params: list[Any] = []
        if status is not None:
            clauses.append("status = ?")
            params.append(status)
        if repo is not None:
            clauses.append("repo = ?")
            params.append(repo)
        where = f"WHERE {' AND '.join(clauses)} " if clauses else ""
        with self._connect() as conn:
            rows = conn.execute(
                f"SELECT * FROM dispatcher_tasks {where}"
                "ORDER BY updated_at DESC, created_at DESC",
                tuple(params),
            ).fetchall()
        return [
            TaskRecord(
                task_id=r["task_id"],
                issue_number=r["issue_number"],
                title=r["title"],
                status=r["status"],
                priority=r["priority"],
                repo=r["repo"],
                source_anchor_refs=list(_loads(r["source_anchor_refs"]) or []),
                claimed_by=r["claimed_by"],
                lease_id=r["lease_id"],
                lease_expires_at=r["lease_expires_at"],
                linked_pr=r["linked_pr"],
                blocked_reason=r["blocked_reason"],
                last_heartbeat_at=r["last_heartbeat_at"],
                sync_state=_loads(r["sync_state"]),
                created_at=r["created_at"],
                updated_at=r["updated_at"],
            )
            for r in rows
        ]

    def list_events(self, task_id: str | None = None) -> list[EventRecord]:
        with self._connect() as conn:
            if task_id is None:
                rows = conn.execute(
                    "SELECT * FROM dispatcher_events ORDER BY timestamp, event_id"
                ).fetchall()
            else:
                rows = conn.execute(
                    "SELECT * FROM dispatcher_events WHERE task_id = ? "
                    "ORDER BY timestamp, event_id",
                    (task_id,),
                ).fetchall()
        return [
            EventRecord(
                event_id=r["event_id"],
                timestamp=r["timestamp"],
                task_id=r["task_id"],
                event_type=r["event_type"],
                actor=r["actor"],
                lease_id=r["lease_id"],
                payload=_loads(r["payload"]),
            )
            for r in rows
        ]
