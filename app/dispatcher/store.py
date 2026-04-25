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
from app.dispatcher.schema import DDL_STATEMENTS, SCHEMA_VERSION


class DispatcherStore(Protocol):
    def initialize(self) -> None: ...
    def upsert_task(self, task: TaskRecord) -> None: ...
    def get_task(self, task_id: str) -> TaskRecord | None: ...
    def upsert_lease(self, lease: LeaseRecord) -> None: ...
    def get_lease(self, lease_id: str) -> LeaseRecord | None: ...
    def append_event(self, event: EventRecord) -> None: ...
    def list_events(self, task_id: str | None = None) -> list[EventRecord]: ...


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

    @property
    def db_path(self) -> Path:
        return self._db_path

    def _connect(self) -> sqlite3.Connection:
        self._db_path.parent.mkdir(parents=True, exist_ok=True)
        conn = sqlite3.connect(self._db_path)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA foreign_keys = ON")
        return conn

    def initialize(self) -> None:
        with self._connect() as conn:
            for stmt in DDL_STATEMENTS:
                conn.execute(stmt)
            conn.execute(
                "INSERT OR REPLACE INTO dispatcher_meta(key, value) VALUES (?, ?)",
                ("schema_version", str(SCHEMA_VERSION)),
            )
            conn.commit()

    # ----- tasks -----

    def upsert_task(self, task: TaskRecord) -> None:
        with self._connect() as conn:
            conn.execute(
                """
                INSERT INTO dispatcher_tasks (
                    task_id, issue_number, title, status, priority,
                    source_anchor_refs, claimed_by, lease_id, lease_expires_at,
                    linked_pr, blocked_reason, last_heartbeat_at, sync_state,
                    created_at, updated_at
                ) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
                ON CONFLICT(task_id) DO UPDATE SET
                    issue_number=excluded.issue_number,
                    title=excluded.title,
                    status=excluded.status,
                    priority=excluded.priority,
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
