"""Higher-level dispatcher operations used by the CLI.

Thin service layer for mutations not covered by queue or leases modules.
"""

from __future__ import annotations

import uuid
from datetime import datetime, timezone

from app.dispatcher.models import EventRecord, TaskRecord
from app.dispatcher.store import SqliteStore


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="microseconds")


def _make_event_id() -> str:
    return f"evt-{uuid.uuid4().hex[:8]}"


def _make_task_id() -> str:
    return f"task-{uuid.uuid4().hex[:8]}"


def update_task(
    store: SqliteStore,
    task_id: str,
    status: str | None,
    note: str | None,
    actor: str,
) -> TaskRecord:
    """Update task status and/or record a note. Emits task.updated event."""
    task = store.get_task(task_id)
    if task is None:
        raise ValueError(f"Task {task_id} not found")

    payload: dict = {}
    if status is not None:
        task.status = status
        payload["status"] = status
        if status != "blocked":
            task.blocked_reason = None
    if note is not None:
        payload["note"] = note

    task.updated_at = _utc_now()
    store.upsert_task(task)

    store.append_event(EventRecord(
        event_id=_make_event_id(),
        timestamp=_utc_now(),
        task_id=task_id,
        event_type="task.updated",
        actor=actor,
        payload=payload or None,
    ))

    return task


def link_pr(
    store: SqliteStore,
    task_id: str,
    pr_number: int,
    actor: str,
) -> TaskRecord:
    """Link a PR number to a task. Emits task.updated event."""
    task = store.get_task(task_id)
    if task is None:
        raise ValueError(f"Task {task_id} not found")

    task.linked_pr = str(pr_number)
    task.updated_at = _utc_now()
    store.upsert_task(task)

    store.append_event(EventRecord(
        event_id=_make_event_id(),
        timestamp=_utc_now(),
        task_id=task_id,
        event_type="task.updated",
        actor=actor,
        payload={"linked_pr": pr_number},
    ))

    return task


