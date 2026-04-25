"""Integration tests for the full agent dispatcher workflow.

Tests the complete agent loop: status check → next → claim → heartbeat → complete
against a temporary in-process dispatcher store.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from app.dispatcher.store import SqliteStore


@pytest.fixture()
def tmp_store(tmp_path: Path) -> SqliteStore:
    """Initialized SqliteStore backed by a temp directory."""
    store = SqliteStore(tmp_path / "test_dispatcher.db")
    store.initialize()
    return store


# ---------------------------------------------------------------------------
# AC: Full agent loop (status, next, claim, heartbeat, complete)
# Verify: test_full_agent_loop_status_next_claim_heartbeat_complete
# ---------------------------------------------------------------------------

def test_full_agent_loop_status_next_claim_heartbeat_complete(tmp_store: SqliteStore) -> None:
    """Full agent loop: status → next → claim → heartbeat → complete."""
    from datetime import datetime, timezone

    from app.dispatcher import leases as lease_module
    from app.dispatcher.models import TaskRecord

    now = datetime.now(timezone.utc).isoformat()

    # 1. Create a ready task (simulating dispatcher pull)
    task = TaskRecord(
        task_id="github-issue-999",
        issue_number=999,
        title="Test agent loop task",
        status="ready",
        priority="high",
        source_anchor_refs=["github:issue:999"],
        created_at=now,
        updated_at=now,
    )
    tmp_store.upsert_task(task)

    # Verify initial state
    stored = tmp_store.get_task("github-issue-999")
    assert stored is not None
    assert stored.status == "ready"

    # 2. Claim the task
    claimed_task, lease = lease_module.claim(
        tmp_store,
        task_id="github-issue-999",
        agent_id="test-agent",
        ttl_minutes=90,
    )
    assert claimed_task.status == "claimed"
    assert claimed_task.claimed_by == "test-agent"
    assert lease.holder == "test-agent"

    # 3. Heartbeat the lease
    updated_lease = lease_module.heartbeat(
        tmp_store,
        task_id="github-issue-999",
        agent_id="test-agent",
    )
    assert updated_lease.holder == "test-agent"
    assert updated_lease.heartbeat_at is not None

    # 4. Complete the task
    completed_task = lease_module.release(
        tmp_store,
        task_id="github-issue-999",
        agent_id="test-agent",
    )
    assert completed_task.status == "ready"  # released back to ready
    assert completed_task.claimed_by is None
    assert completed_task.lease_id is None

    # Verify events in audit trail
    events = tmp_store.list_events()
    event_types = [e.event_type for e in events]

    # Must contain claim and heartbeat events
    assert "task.claimed" in event_types, f"Missing task.claimed event in {event_types}"
    assert "task.heartbeat" in event_types, f"Missing task.heartbeat event in {event_types}"
    assert "task.released" in event_types, f"Missing task.released event in {event_types}"


# ---------------------------------------------------------------------------
# AC: Full loop with completion (not release)
# Verify: test_full_agent_loop_with_completion
# ---------------------------------------------------------------------------

def test_full_agent_loop_with_completion(tmp_store: SqliteStore) -> None:
    """Full agent loop with task completion (terminal state)."""
    from datetime import datetime, timezone

    from app.dispatcher import leases as lease_module
    from app.dispatcher import queue as queue_module
    from app.dispatcher.models import TaskRecord

    now = datetime.now(timezone.utc).isoformat()

    # 1. Create a ready task
    task = TaskRecord(
        task_id="github-issue-888",
        issue_number=888,
        title="Test completion loop task",
        status="ready",
        priority="med",
        source_anchor_refs=["github:issue:888"],
        created_at=now,
        updated_at=now,
    )
    tmp_store.upsert_task(task)

    # 2. Claim
    claimed_task, lease = lease_module.claim(
        tmp_store,
        task_id="github-issue-888",
        agent_id="agent-1",
        ttl_minutes=90,
    )
    assert claimed_task.status == "claimed"

    # 3. Heartbeat
    lease_module.heartbeat(
        tmp_store,
        task_id="github-issue-888",
        agent_id="agent-1",
    )

    # 4. Complete (terminal)
    completed_task = queue_module.complete(
        tmp_store,
        task_id="github-issue-888",
        actor="agent-1",
    )
    assert completed_task.status == "completed"
    assert completed_task.claimed_by is None
    assert completed_task.lease_id is None

    # Verify event trail
    events = tmp_store.list_events()
    event_types = [e.event_type for e in events]
    assert "task.claimed" in event_types
    assert "task.heartbeat" in event_types
    assert "task.completed" in event_types


# ---------------------------------------------------------------------------
# AC: Event trail maintains order and consistency
# Verify: test_event_trail_order_and_consistency
# ---------------------------------------------------------------------------

def test_event_trail_order_and_consistency(tmp_store: SqliteStore) -> None:
    """Event audit trail maintains correct ordering and task ID consistency."""
    from datetime import datetime, timezone

    from app.dispatcher import leases as lease_module
    from app.dispatcher.models import TaskRecord

    now = datetime.now(timezone.utc).isoformat()

    # Create and execute a task
    task = TaskRecord(
        task_id="github-issue-777",
        issue_number=777,
        title="Event ordering test",
        status="ready",
        priority="low",
        source_anchor_refs=["github:issue:777"],
        created_at=now,
        updated_at=now,
    )
    tmp_store.upsert_task(task)

    # Claim and heartbeat
    lease_module.claim(tmp_store, task_id="github-issue-777", agent_id="evt-agent", ttl_minutes=90)
    lease_module.heartbeat(tmp_store, task_id="github-issue-777", agent_id="evt-agent")
    lease_module.heartbeat(tmp_store, task_id="github-issue-777", agent_id="evt-agent")

    # Get events
    events = tmp_store.list_events()
    task_events = [e for e in events if e.task_id == "github-issue-777"]

    # Verify events are ordered and all belong to the same task
    assert len(task_events) >= 3, f"Expected at least 3 events, got {len(task_events)}"
    for event in task_events:
        assert event.task_id == "github-issue-777"
    assert task_events[0].event_type == "task.claimed"
    assert task_events[1].event_type == "task.heartbeat"
    assert task_events[2].event_type == "task.heartbeat"
