"""CLI tests for the dispatcher agent-facing interface.

All tests use isolated temporary state and do not mutate developer/runtime state.
No GitHub API access required.
"""

from __future__ import annotations

import json
import os
from pathlib import Path

import pytest

from app.dispatcher.cli import REQUIRED_COMMANDS, _COMMAND_MAP, main
from app.dispatcher.config import load_paths
from app.dispatcher.events import JsonlEventWriter
from app.dispatcher.store import SqliteStore


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture()
def tmp_env(tmp_path: Path) -> dict[str, str]:
    """Env vars pointing to a temporary state directory."""
    state_dir = tmp_path / "dispatcher"
    return {
        "DISPATCHER_STATE_DIR": str(state_dir),
        "DISPATCHER_DB_PATH": str(state_dir / "dispatcher.sqlite3"),
        "DISPATCHER_EVENTS_PATH": str(state_dir / "events.jsonl"),
    }


@pytest.fixture()
def store(tmp_env: dict[str, str]) -> SqliteStore:
    """Initialized SqliteStore backed by a temp directory."""
    paths = load_paths(tmp_env)
    writer = JsonlEventWriter(paths.events_path)
    s = SqliteStore(db_path=paths.db_path, event_writer=writer)
    s.initialize()
    return s


def _run(argv: list[str], env: dict[str, str]) -> tuple[int, dict]:
    """Run the CLI with the given argv in the given env and parse JSON output."""
    old = os.environ.copy()
    os.environ.update(env)
    try:
        import io
        from contextlib import redirect_stdout
        buf = io.StringIO()
        with redirect_stdout(buf):
            code = main(argv)
        output = buf.getvalue().strip()
    finally:
        os.environ.clear()
        os.environ.update(old)
    return code, json.loads(output) if output else {}


# ---------------------------------------------------------------------------
# AC: all required commands present
# Verify: test_all_required_commands_present
# ---------------------------------------------------------------------------

def test_all_required_commands_present():
    registered = set(_COMMAND_MAP.keys())
    missing = REQUIRED_COMMANDS - registered
    assert not missing, f"Missing required commands: {missing}"


# ---------------------------------------------------------------------------
# AC: next --json returns compact task or explicit empty-queue result
# Verify: test_next_compact_output
# ---------------------------------------------------------------------------

def test_next_compact_output(tmp_env, store):
    code, data = _run(["next", "--agent", "test-agent", "--json"], tmp_env)
    assert code == 0
    assert data["ok"] is True
    assert data["empty"] is True
    assert data["task"] is None


def test_next_compact_output_with_task(tmp_env, store):
    from app.dispatcher.services import seed_demo
    seed_demo(store)
    code, data = _run(["next", "--agent", "test-agent", "--json"], tmp_env)
    assert code == 0
    assert data["ok"] is True
    assert data["task"] is not None
    task = data["task"]
    assert "task_id" in task
    assert "title" in task
    assert "status" in task
    assert "sync_state" not in task


# ---------------------------------------------------------------------------
# AC: claim --json returns task/lease state or explicit claim-conflict error
# Verify: test_claim_json_output
# ---------------------------------------------------------------------------

def test_claim_json_output(tmp_env, store):
    from app.dispatcher.services import seed_demo
    tasks = seed_demo(store)
    ready = next(t for t in tasks if t.status == "ready")

    code, data = _run(
        ["claim", ready.task_id, "--agent", "codex", "--ttl-minutes", "30", "--json"],
        tmp_env,
    )
    assert code == 0
    assert data["ok"] is True
    assert "task" in data
    assert "lease" in data
    assert data["task"]["status"] == "claimed"
    assert data["lease"]["holder"] == "codex"


def test_claim_conflict_returns_error(tmp_env, store):
    from app.dispatcher.services import seed_demo
    tasks = seed_demo(store)
    ready = next(t for t in tasks if t.status == "ready")

    _run(["claim", ready.task_id, "--agent", "codex", "--json"], tmp_env)
    code, data = _run(["claim", ready.task_id, "--agent", "other-agent", "--json"], tmp_env)
    assert code == 1
    assert data["ok"] is False
    assert "error" in data


# ---------------------------------------------------------------------------
# AC: heartbeat --json returns updated lease state or explicit no-active-lease error
# Verify: test_heartbeat_json_output
# ---------------------------------------------------------------------------

def test_heartbeat_json_output(tmp_env, store):
    from app.dispatcher.services import seed_demo
    tasks = seed_demo(store)
    ready = next(t for t in tasks if t.status == "ready")

    _run(["claim", ready.task_id, "--agent", "codex", "--json"], tmp_env)
    code, data = _run(["heartbeat", ready.task_id, "--agent", "codex", "--json"], tmp_env)
    assert code == 0
    assert data["ok"] is True
    assert "lease" in data
    assert data["lease"]["holder"] == "codex"


def test_heartbeat_no_lease_error(tmp_env, store):
    from app.dispatcher.services import seed_demo
    tasks = seed_demo(store)
    ready = next(t for t in tasks if t.status == "ready")

    code, data = _run(["heartbeat", ready.task_id, "--agent", "codex", "--json"], tmp_env)
    assert code == 1
    assert data["ok"] is False
    assert "error" in data


# ---------------------------------------------------------------------------
# AC: release --json returns updated task state
# Verify: test_release_json_output
# ---------------------------------------------------------------------------

def test_release_json_output(tmp_env, store):
    from app.dispatcher.services import seed_demo
    tasks = seed_demo(store)
    ready = next(t for t in tasks if t.status == "ready")

    _run(["claim", ready.task_id, "--agent", "codex", "--json"], tmp_env)
    code, data = _run(["release", ready.task_id, "--agent", "codex", "--json"], tmp_env)
    assert code == 0
    assert data["ok"] is True
    assert data["task"]["status"] == "ready"
    assert data["task"]["claimed_by"] is None


# ---------------------------------------------------------------------------
# AC: block --json returns updated blocked task state
# Verify: test_block_json_output
# ---------------------------------------------------------------------------

def test_block_json_output(tmp_env, store):
    from app.dispatcher.services import seed_demo
    tasks = seed_demo(store)
    ready = next(t for t in tasks if t.status == "ready")

    code, data = _run(
        ["block", ready.task_id, "--reason", "waiting for upstream", "--json"],
        tmp_env,
    )
    assert code == 0
    assert data["ok"] is True
    assert data["task"]["status"] == "blocked"
    assert data["task"]["blocked_reason"] == "waiting for upstream"


# ---------------------------------------------------------------------------
# AC: events --json returns recent dispatcher events
# Verify: test_events_json_output
# ---------------------------------------------------------------------------

def test_events_json_output(tmp_env, store):
    from app.dispatcher.services import seed_demo
    tasks = seed_demo(store)
    ready = next(t for t in tasks if t.status == "ready")
    _run(["claim", ready.task_id, "--agent", "codex", "--json"], tmp_env)

    code, data = _run(["events", "--tail", "20", "--json"], tmp_env)
    assert code == 0
    assert data["ok"] is True
    assert "events" in data
    assert isinstance(data["events"], list)
    assert data["count"] >= 1
    event = data["events"][0]
    assert "event_id" in event
    assert "event_type" in event
    assert "timestamp" in event


# ---------------------------------------------------------------------------
# AC: seed-demo creates local demo tasks without GitHub access
# Verify: test_seed_demo_creates_tasks
# ---------------------------------------------------------------------------

def test_seed_demo_creates_tasks(tmp_env):
    _run(["init", "--json"], tmp_env)
    code, data = _run(["seed-demo", "--json"], tmp_env)
    assert code == 0
    assert data["ok"] is True
    assert data["created"] >= 1
    for task in data["tasks"]:
        assert "task_id" in task
        assert "title" in task
        assert "status" in task


# ---------------------------------------------------------------------------
# AC: JSON output avoids large blobs and full board dumps
# Verify: test_json_output_compact
# ---------------------------------------------------------------------------

def test_json_output_compact(tmp_env, store):
    from app.dispatcher.services import seed_demo
    seed_demo(store)

    code, data = _run(["queue", "--json"], tmp_env)
    assert code == 0
    for task in data.get("tasks", []):
        assert "sync_state" not in task, "sync_state must not appear in compact output"

    code, data = _run(["next", "--agent", "codex", "--json"], tmp_env)
    assert code == 0
    if data.get("task"):
        assert "sync_state" not in data["task"]


# ---------------------------------------------------------------------------
# Supplemental: init, show, update, link-pr, status
# ---------------------------------------------------------------------------

def test_init_returns_paths(tmp_env):
    code, data = _run(["init", "--json"], tmp_env)
    assert code == 0
    assert data["ok"] is True
    assert "state_dir" in data
    assert "db_path" in data
    assert "events_path" in data


def test_show_returns_task(tmp_env, store):
    from app.dispatcher.services import seed_demo
    tasks = seed_demo(store)
    code, data = _run(["show", tasks[0].task_id, "--json"], tmp_env)
    assert code == 0
    assert data["ok"] is True
    assert data["task"]["task_id"] == tasks[0].task_id


def test_show_not_found(tmp_env, store):
    code, data = _run(["show", "nonexistent-task-id", "--json"], tmp_env)
    assert code == 1
    assert data["ok"] is False


def test_update_status(tmp_env, store):
    from app.dispatcher.services import seed_demo
    tasks = seed_demo(store)
    ready = next(t for t in tasks if t.status == "ready")
    code, data = _run(
        ["update", ready.task_id, "--status", "in_progress", "--json"],
        tmp_env,
    )
    assert code == 0
    assert data["ok"] is True
    assert data["task"]["status"] == "in_progress"


def test_status_command(tmp_env):
    _run(["init", "--json"], tmp_env)
    code, data = _run(["status", "--json"], tmp_env)
    assert code == 0
    assert data["ok"] is True
    assert "db_path" in data
