"""Higher-level dispatcher operations used by the CLI.

Thin service layer for mutations not covered by queue or leases modules.
"""

from __future__ import annotations

import json
import uuid
from datetime import datetime, timezone

from app.dispatcher.models import EventRecord, TaskRecord
from app.dispatcher.signboard import canonical_status
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


def move_task(
    store: SqliteStore,
    task_id: str,
    status: str,
    actor: str,
    note: str | None = None,
) -> TaskRecord:
    """Move a task to a lifecycle status. Emits task.moved event."""
    next_status = canonical_status(status)
    if next_status == "review":
        return _move_task_to_review(store, task_id, actor, note, allow_handoff=True)

    task = store.get_task(task_id)
    if task is None:
        raise ValueError(f"Task {task_id} not found")

    if next_status == "completed" and task.lease_id is not None:
        raise ValueError(
            f"Cannot move task {task_id} to completed while lease {task.lease_id} is active; "
            "use complete instead"
        )
    previous_status = task.status
    task.status = next_status
    if next_status != "blocked":
        task.blocked_reason = None
    task.updated_at = _utc_now()
    store.upsert_task(task)

    payload: dict = {
        "from_status": previous_status,
        "to_status": next_status,
    }
    if note is not None:
        payload["note"] = note

    store.append_event(EventRecord(
        event_id=_make_event_id(),
        timestamp=_utc_now(),
        task_id=task_id,
        event_type="task.moved",
        actor=actor,
        payload=payload,
    ))

    return task


def move_unclaimed_task_to_review(
    store: SqliteStore,
    task_id: str,
    actor: str,
    note: str | None = None,
) -> TaskRecord:
    """Move only an unclaimed task to Review under the dispatcher write lock.

    This is the Signboard boundary: a projection client has no agent identity
    authority and therefore never performs the claimed-holder handoff.
    """
    return _move_task_to_review(store, task_id, actor, note, allow_handoff=False)


def _move_task_to_review(
    store: SqliteStore,
    task_id: str,
    actor: str,
    note: str | None,
    *,
    allow_handoff: bool,
) -> TaskRecord:
    """Atomically decide and persist the complete Review transition.

    The task state is intentionally not inspected before ``BEGIN IMMEDIATE``:
    otherwise a claim that arrives between a read and a generic upsert can be
    silently overwritten by a stale Review move.
    """

    now = _utc_now()
    with store._connect() as conn:
        conn.execute("BEGIN IMMEDIATE")
        task = conn.execute(
            "SELECT * FROM dispatcher_tasks WHERE task_id = ?", (task_id,)
        ).fetchone()
        if task is None:
            raise ValueError(f"Task {task_id} not found")
        lease_id = task["lease_id"]
        release_event: EventRecord | None = None
        if lease_id is None:
            moved = conn.execute(
                """
                UPDATE dispatcher_tasks
                SET status = 'review', blocked_reason = NULL, updated_at = ?
                WHERE task_id = ? AND lease_id IS NULL
                """,
                (now, task_id),
            )
        else:
            if not allow_handoff:
                raise ValueError(
                    "claimed task Review handoff requires the dispatcher lease holder path"
                )
            lease = conn.execute(
                "SELECT * FROM dispatcher_leases WHERE lease_id = ?", (lease_id,)
            ).fetchone()
            if lease is None or lease["released_at"] is not None:
                raise ValueError(f"Task {task_id} has no active lease for review handoff")
            if lease["holder"] != actor:
                raise ValueError(
                    f"Cannot move task {task_id} to review: lease {lease_id} is held by {lease['holder']}, not {actor}"
                )

            released = conn.execute(
                """
                UPDATE dispatcher_leases
                SET released_at = ?, release_reason = 'review_handoff'
                WHERE lease_id = ? AND released_at IS NULL
                """,
                (now, lease_id),
            )
            if released.rowcount != 1:
                raise ValueError(f"Cannot move task {task_id} to review: lease changed concurrently")

            moved = conn.execute(
                """
                UPDATE dispatcher_tasks
                SET status = 'review', blocked_reason = NULL, lease_id = NULL,
                    claimed_by = NULL, last_heartbeat_at = NULL, lease_expires_at = NULL,
                    updated_at = ?
                WHERE task_id = ? AND lease_id = ?
                """,
                (now, task_id, lease_id),
            )
            release_event = EventRecord(
                event_id=_make_event_id(),
                timestamp=now,
                task_id=task_id,
                event_type="task.released",
                actor=actor,
                lease_id=lease_id,
                payload={"reason": "review_handoff"},
            )
        if moved.rowcount != 1:
            raise ValueError(f"Cannot move task {task_id} to review: task changed concurrently")
        move_payload: dict[str, str] = {"from_status": task["status"], "to_status": "review"}
        if note is not None:
            move_payload["note"] = note
        move_event = EventRecord(
            event_id=_make_event_id(),
            timestamp=now,
            task_id=task_id,
            event_type="task.moved",
            actor=actor,
            payload=move_payload,
        )
        events = (move_event,) if release_event is None else (release_event, move_event)
        for event in events:
            conn.execute(
                """
                INSERT INTO dispatcher_events (
                    event_id, timestamp, task_id, event_type, actor, lease_id, payload
                ) VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    event.event_id,
                    event.timestamp,
                    event.task_id,
                    event.event_type,
                    event.actor,
                    event.lease_id,
                    json.dumps(event.payload, sort_keys=True, ensure_ascii=False)
                    if event.payload is not None
                    else None,
                ),
            )
        conn.commit()

    if store._event_writer is not None:
        if release_event is not None:
            store._event_writer.append(release_event)
        store._event_writer.append(move_event)
    moved_task = store.get_task(task_id)
    assert moved_task is not None
    return moved_task


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
