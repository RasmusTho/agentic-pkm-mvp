"""Test-only helpers for dispatcher tests."""

from __future__ import annotations

import uuid
from datetime import datetime, timezone

from app.dispatcher.models import TaskRecord
from app.dispatcher.store import SqliteStore


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="microseconds")


_SEED_TASKS = [
    {"issue_number": 9001, "title": "Test: implement feature A", "status": "ready", "priority": "high", "blocked_reason": None},
    {"issue_number": 9002, "title": "Test: write tests for B", "status": "ready", "priority": "med", "blocked_reason": None},
    {"issue_number": 9003, "title": "Test: blocked by upstream", "status": "blocked", "priority": "low", "blocked_reason": "waiting for upstream"},
]


def seed_tasks(store: SqliteStore) -> list[TaskRecord]:
    """Populate store with synthetic tasks for testing. Never calls GitHub."""
    now = _utc_now()
    created: list[TaskRecord] = []
    for d in _SEED_TASKS:
        task = TaskRecord(
            task_id=f"task-{uuid.uuid4().hex[:8]}",
            issue_number=d["issue_number"],
            title=d["title"],
            status=d["status"],
            priority=d["priority"],
            source_anchor_refs=[],
            blocked_reason=d["blocked_reason"],
            created_at=now,
            updated_at=now,
        )
        store.upsert_task(task)
        created.append(task)
    return created
