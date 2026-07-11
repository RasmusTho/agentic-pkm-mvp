"""CLI tests for the dispatcher agent-facing interface.

All tests use isolated temporary state and do not mutate developer/runtime state.
No GitHub API access required.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from app.dispatcher.cli import REQUIRED_COMMANDS, _COMMAND_MAP, main
from app.dispatcher.config import load_paths
from app.dispatcher.events import JsonlEventWriter
from app.dispatcher.singleton import fcntl, singleton_paths
from app.dispatcher.store import SqliteStore

REPO_ROOT = Path(__file__).resolve().parents[2]
VALID_READY_BODY = (
    REPO_ROOT / "tests/fixtures/issue_readiness/valid_ready_candidate.md"
).read_text(encoding="utf-8")


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture()
def tmp_env(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> dict[str, str]:
    """Env vars pointing to a temporary state directory.

    Applied to the process env via monkeypatch (function-scoped, auto-restored)
    and also returned so callers can pass the dict to load_paths(...).
    """
    state_dir = tmp_path / "dispatcher"
    env = {
        "DISPATCHER_STATE_DIR": str(state_dir),
        "DISPATCHER_DB_PATH": str(state_dir / "dispatcher.sqlite3"),
        "DISPATCHER_EVENTS_PATH": str(state_dir / "events.jsonl"),
    }
    for key, value in env.items():
        monkeypatch.setenv(key, value)
    return env


@pytest.fixture()
def store(tmp_env: dict[str, str]) -> SqliteStore:
    """Initialized SqliteStore backed by a temp directory."""
    paths = load_paths(tmp_env)
    writer = JsonlEventWriter(paths.events_path)
    s = SqliteStore(db_path=paths.db_path, event_writer=writer)
    s.initialize()
    return s


def _run(argv: list[str]) -> tuple[int, dict]:
    """Run the CLI with the given argv and parse JSON output.

    The dispatcher env (DISPATCHER_*) is applied by the ``tmp_env`` fixture via
    monkeypatch, so callers pass only argv here.
    """
    import io
    from contextlib import redirect_stdout
    buf = io.StringIO()
    with redirect_stdout(buf):
        code = main(argv)
    output = buf.getvalue().strip()
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
    code, data = _run(["next", "--agent", "test-agent", "--json"])
    assert code == 0
    assert data["ok"] is True
    assert data["empty"] is True
    assert data["task"] is None


def test_next_compact_output_with_task(tmp_env, store):
    from tests.dispatcher.helpers import seed_tasks
    seed_tasks(store)
    code, data = _run(["next", "--agent", "test-agent", "--json"])
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
    from tests.dispatcher.helpers import seed_tasks
    tasks = seed_tasks(store)
    ready = next(t for t in tasks if t.status == "ready")

    code, data = _run(
        ["claim", ready.task_id, "--agent", "codex", "--ttl-minutes", "30", "--json"],
    )
    assert code == 0
    assert data["ok"] is True
    assert "task" in data
    assert "lease" in data
    assert data["task"]["status"] == "claimed"
    assert data["lease"]["holder"] == "codex"


def test_claim_conflict_returns_error(tmp_env, store):
    from tests.dispatcher.helpers import seed_tasks
    tasks = seed_tasks(store)
    ready = next(t for t in tasks if t.status == "ready")

    _run(["claim", ready.task_id, "--agent", "codex", "--json"])
    code, data = _run(["claim", ready.task_id, "--agent", "other-agent", "--json"])
    assert code == 1
    assert data["ok"] is False
    assert "error" in data


def test_claim_verb_takeover_stale_flag(tmp_env, store):
    from datetime import datetime, timedelta, timezone

    from app.dispatcher.leases import claim
    from tests.dispatcher.helpers import seed_tasks

    tasks = seed_tasks(store)
    ready = next(t for t in tasks if t.status == "ready")
    _, lease = claim(store, ready.task_id, "departed-agent")
    old_lease = store.get_lease(lease.lease_id)
    assert old_lease is not None
    past_time = (datetime.now(timezone.utc) - timedelta(hours=1)).isoformat()
    old_lease.acquired_at = past_time
    old_lease.expires_at = past_time
    old_lease.heartbeat_at = past_time
    store.upsert_lease(old_lease)

    code, data = _run(
        [
            "claim", ready.task_id, "--agent", "replacement-agent",
            "--takeover-stale", "--json",
        ],
    )

    assert code == 0
    assert data["ok"] is True
    assert data["lease"]["holder"] == "replacement-agent"


# ---------------------------------------------------------------------------
# AC: heartbeat --json returns updated lease state or explicit no-active-lease error
# Verify: test_heartbeat_json_output
# ---------------------------------------------------------------------------

def test_heartbeat_json_output(tmp_env, store):
    from tests.dispatcher.helpers import seed_tasks
    tasks = seed_tasks(store)
    ready = next(t for t in tasks if t.status == "ready")

    _run(["claim", ready.task_id, "--agent", "codex", "--json"])
    code, data = _run(["heartbeat", ready.task_id, "--agent", "codex", "--json"])
    assert code == 0
    assert data["ok"] is True
    assert "lease" in data
    assert data["lease"]["holder"] == "codex"


def test_heartbeat_no_lease_error(tmp_env, store):
    from tests.dispatcher.helpers import seed_tasks
    tasks = seed_tasks(store)
    ready = next(t for t in tasks if t.status == "ready")

    code, data = _run(["heartbeat", ready.task_id, "--agent", "codex", "--json"])
    assert code == 1
    assert data["ok"] is False
    assert "error" in data


# ---------------------------------------------------------------------------
# AC: release --json returns updated task state
# Verify: test_release_json_output
# ---------------------------------------------------------------------------

def test_release_json_output(tmp_env, store):
    from tests.dispatcher.helpers import seed_tasks
    tasks = seed_tasks(store)
    ready = next(t for t in tasks if t.status == "ready")

    _run(["claim", ready.task_id, "--agent", "codex", "--json"])
    code, data = _run(["release", ready.task_id, "--agent", "codex", "--json"])
    assert code == 0
    assert data["ok"] is True
    assert data["task"]["status"] == "ready"
    assert data["task"]["claimed_by"] is None


# ---------------------------------------------------------------------------
# AC: block --json returns updated blocked task state
# Verify: test_block_json_output
# ---------------------------------------------------------------------------

def test_block_json_output(tmp_env, store):
    from tests.dispatcher.helpers import seed_tasks
    tasks = seed_tasks(store)
    ready = next(t for t in tasks if t.status == "ready")

    code, data = _run(
        ["block", ready.task_id, "--reason", "waiting for upstream", "--json"],
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
    from tests.dispatcher.helpers import seed_tasks
    tasks = seed_tasks(store)
    ready = next(t for t in tasks if t.status == "ready")
    _run(["claim", ready.task_id, "--agent", "codex", "--json"])

    code, data = _run(["events", "--tail", "20", "--json"])
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
# AC: JSON output avoids large blobs and full board dumps
# Verify: test_json_output_compact
# ---------------------------------------------------------------------------

def test_json_output_compact(tmp_env, store):
    from tests.dispatcher.helpers import seed_tasks
    seed_tasks(store)

    code, data = _run(["queue", "--json"])
    assert code == 0
    for task in data.get("tasks", []):
        assert "sync_state" not in task, "sync_state must not appear in compact output"

    code, data = _run(["next", "--agent", "codex", "--json"])
    assert code == 0
    if data.get("task"):
        assert "sync_state" not in data["task"]


# ---------------------------------------------------------------------------
# Supplemental: init, show, update, link-pr, status
# ---------------------------------------------------------------------------

def test_init_returns_paths(tmp_env):
    code, data = _run(["init", "--json"])
    assert code == 0
    assert data["ok"] is True
    assert "state_dir" in data
    assert "db_path" in data
    assert "events_path" in data


def test_show_returns_task(tmp_env, store):
    from tests.dispatcher.helpers import seed_tasks
    tasks = seed_tasks(store)
    code, data = _run(["show", tasks[0].task_id, "--json"])
    assert code == 0
    assert data["ok"] is True
    assert data["task"]["task_id"] == tasks[0].task_id


def test_show_not_found(tmp_env, store):
    code, data = _run(["show", "nonexistent-task-id", "--json"])
    assert code == 1
    assert data["ok"] is False


def test_update_status(tmp_env, store):
    from tests.dispatcher.helpers import seed_tasks
    tasks = seed_tasks(store)
    ready = next(t for t in tasks if t.status == "ready")
    code, data = _run(
        ["update", ready.task_id, "--status", "in_progress", "--json"],
    )
    assert code == 0
    assert data["ok"] is True
    assert data["task"]["status"] == "in_progress"


def test_update_clears_blocked_reason_on_non_blocked_status(tmp_env, store):
    from tests.dispatcher.helpers import seed_tasks
    tasks = seed_tasks(store)
    ready = next(t for t in tasks if t.status == "ready")
    _run(["block", ready.task_id, "--reason", "upstream dep", "--json"])

    code, data = _run(
        ["update", ready.task_id, "--status", "ready", "--json"],
    )
    assert code == 0
    assert data["task"]["status"] == "ready"
    assert data["task"]["blocked_reason"] is None

    next_code, next_data = _run(["next", "--agent", "codex", "--json"])
    assert next_code == 0
    assert next_data["task"] is not None
    assert next_data["task"]["task_id"] == ready.task_id


def test_move_command_sets_lifecycle_status_and_emits_event(tmp_env, store):
    from tests.dispatcher.helpers import seed_tasks
    tasks = seed_tasks(store)
    ready = next(t for t in tasks if t.status == "ready")

    code, data = _run(
        ["move", ready.task_id, "--status", "Review", "--agent", "codex", "--json"],
    )
    assert code == 0
    assert data["ok"] is True
    assert data["task"]["status"] == "review"

    events_code, events_data = _run(["events", "--tail", "20", "--json"])
    assert events_code == 0
    moved = [e for e in events_data["events"] if e["event_type"] == "task.moved"]
    assert moved
    assert moved[-1]["payload"]["from_status"] == "ready"
    assert moved[-1]["payload"]["to_status"] == "review"


def test_move_done_normalizes_to_completed(tmp_env, store):
    from tests.dispatcher.helpers import seed_tasks
    tasks = seed_tasks(store)
    ready = next(t for t in tasks if t.status == "ready")

    code, data = _run(
        ["move", ready.task_id, "--status", "Done", "--agent", "codex", "--json"],
    )
    assert code == 0
    assert data["task"]["status"] == "completed"


def test_move_rejects_unknown_status(tmp_env, store):
    from tests.dispatcher.helpers import seed_tasks
    tasks = seed_tasks(store)
    ready = next(t for t in tasks if t.status == "ready")

    code, data = _run(
        ["move", ready.task_id, "--status", "revieew", "--agent", "codex", "--json"],
    )
    assert code == 1
    assert data["ok"] is False
    assert "Unknown dispatcher status" in data["error"]


def test_move_completed_rejects_active_lease(tmp_env, store):
    from tests.dispatcher.helpers import seed_tasks
    tasks = seed_tasks(store)
    ready = next(t for t in tasks if t.status == "ready")
    _run(["claim", ready.task_id, "--agent", "codex", "--json"])

    code, data = _run(
        ["move", ready.task_id, "--status", "completed", "--agent", "codex", "--json"],
    )
    assert code == 1
    assert data["ok"] is False
    assert "use complete instead" in data["error"]

    stored = store.get_task(ready.task_id)
    assert stored is not None
    assert stored.status == "claimed"
    assert stored.lease_id is not None
    assert stored.claimed_by == "codex"


def test_export_signboard_writes_markdown_columns(tmp_env, store, tmp_path: Path):
    from tests.dispatcher.helpers import seed_tasks
    tasks = seed_tasks(store)
    ready = next(t for t in tasks if t.status == "ready")
    _run(["move", ready.task_id, "--status", "Review", "--agent", "codex", "--json"])

    board = tmp_path / "BuilderOpsVault" / "agent-delivery"
    code, data = _run(["export-signboard", str(board), "--json"])
    assert code == 0
    assert data["ok"] is True
    assert data["count"] == len(tasks)
    assert (board / "Backlog").is_dir()
    assert (board / "Review").is_dir()

    review_cards = list((board / "Review").glob(f"{ready.task_id}--*.md"))
    assert len(review_cards) == 1
    content = review_cards[0].read_text(encoding="utf-8")
    assert "generated_by: dispatcher.signboard" in content
    assert 'status: "review"' in content
    assert f"issue_number: {ready.issue_number}" in content


def test_export_signboard_removes_stale_generated_card_after_title_change(
    tmp_env,
    store,
    tmp_path: Path,
):
    from tests.dispatcher.helpers import seed_tasks
    tasks = seed_tasks(store)
    ready = next(t for t in tasks if t.status == "ready")
    board = tmp_path / "BuilderOpsVault" / "agent-delivery"

    code, data = _run(["export-signboard", str(board), "--json"])
    assert code == 0
    first_cards = list(board.glob(f"**/{ready.task_id}--*.md"))
    assert len(first_cards) == 1

    ready.title = "Test: renamed feature A"
    store.upsert_task(ready)
    code, data = _run(["export-signboard", str(board), "--json"])
    assert code == 0

    cards = list(board.glob(f"**/{ready.task_id}--*.md"))
    assert len(cards) == 1
    assert "renamed-feature-A" in cards[0].name


def test_status_command(tmp_env):
    _run(["init", "--json"])
    code, data = _run(["status", "--json"])
    assert code == 0
    assert data["ok"] is True
    assert "db_path" in data
    assert "singleton" in data
    assert data["singleton"]["state"] == "active"


def test_status_reports_missing_singleton_without_initializing(tmp_env):
    code, data = _run(["status", "--json"])
    assert code == 0
    assert data["ok"] is True
    assert data["db_exists"] is False
    assert data["singleton"]["exists"] is False
    assert data["singleton"]["state"] == "missing"


def test_start_initializes_absent_dispatcher_state(tmp_env):
    code, data = _run(
        ["start", "--agent", "codex", "--ttl-seconds", "600", "--json"],
    )
    assert code == 0
    assert data["ok"] is True
    assert data["started"] is True
    assert data["recovered_stale"] is False
    assert data["db_exists"] is True
    assert data["singleton"]["state"] == "active"
    assert data["singleton"]["holder"] == "codex"
    assert data["singleton"]["ttl_seconds"] == 600

    paths = load_paths(tmp_env)
    assert paths.db_path.exists()
    assert singleton_paths(paths).record_path.exists()


def test_start_existing_dispatcher_is_noop_status_refresh(tmp_env):
    first_code, first = _run(
        ["start", "--agent", "codex", "--ttl-seconds", "600", "--json"],
    )
    second_code, second = _run(
        ["start", "--agent", "other-agent", "--ttl-seconds", "600", "--json"],
    )

    assert first_code == 0
    assert second_code == 0
    assert first["started"] is True
    assert second["started"] is False
    assert second["recovered_stale"] is False
    assert second["db_path"] == first["db_path"]
    assert second["events_path"] == first["events_path"]
    assert second["singleton"]["state"] == "active"
    assert second["singleton"]["holder"] == "codex"


def test_start_recovers_stale_singleton_record(tmp_env):
    paths = load_paths(tmp_env)
    paths.ensure()
    record_path = singleton_paths(paths).record_path
    record_path.write_text(
        json.dumps(
            {
                "version": 1,
                "holder": "stale-agent",
                "pid": 12345,
                "state_dir": str(paths.state_dir),
                "db_path": str(paths.db_path),
                "events_path": str(paths.events_path),
                "acquired_at": "2026-01-01T00:00:00Z",
                "heartbeat_at": "2026-01-01T00:00:00Z",
                "expires_at": "2026-01-01T00:00:01Z",
                "ttl_seconds": 1,
            },
            sort_keys=True,
        ),
        encoding="utf-8",
    )

    status_code, status = _run(["status", "--json"])
    assert status_code == 0
    assert status["singleton"]["state"] == "stale"

    code, data = _run(
        ["start", "--agent", "codex", "--ttl-seconds", "600", "--json"],
    )

    assert code == 0
    assert data["started"] is True
    assert data["recovered_stale"] is True
    assert data["singleton"]["state"] == "active"
    assert data["singleton"]["holder"] == "codex"
    assert data["db_exists"] is True


def test_start_lock_contention_returns_error(tmp_env):
    if fcntl is None:
        pytest.skip("fcntl lock contention is POSIX-only")

    paths = load_paths(tmp_env)
    paths.ensure()
    guard_path = singleton_paths(paths).guard_path
    with guard_path.open("a+", encoding="utf-8") as guard_file:
        fcntl.flock(guard_file.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        try:
            code, data = _run(["start", "--agent", "codex", "--json"])
        finally:
            fcntl.flock(guard_file.fileno(), fcntl.LOCK_UN)

    assert code == 1
    assert data["ok"] is False
    assert "already in progress" in data["error"]
    assert not paths.db_path.exists()


# ---------------------------------------------------------------------------
# AC: dispatcher complete <task_id> --agent <id> sets status to completed,
#     releases the lease, and emits task.completed
# Verify: test_complete_command
# ---------------------------------------------------------------------------

def test_complete_command(tmp_env, store):
    from tests.dispatcher.helpers import seed_tasks
    tasks = seed_tasks(store)
    ready = next(t for t in tasks if t.status == "ready")

    _run(["claim", ready.task_id, "--agent", "codex", "--json"])
    code, data = _run(["complete", ready.task_id, "--agent", "codex", "--json"])
    assert code == 0
    assert data["ok"] is True
    assert data["task"]["status"] == "completed"
    assert data["task"]["lease_id"] is None
    assert data["task"]["claimed_by"] is None


# ---------------------------------------------------------------------------
# AC: Completing a task by a non-holder agent exits 1 with
#     {"ok": false, "error": "..."}
# Verify: test_complete_wrong_holder
# ---------------------------------------------------------------------------

def test_complete_wrong_holder(tmp_env, store):
    from tests.dispatcher.helpers import seed_tasks
    tasks = seed_tasks(store)
    ready = next(t for t in tasks if t.status == "ready")

    _run(["claim", ready.task_id, "--agent", "codex", "--json"])
    code, data = _run(["complete", ready.task_id, "--agent", "other-agent", "--json"])
    assert code == 1
    assert data["ok"] is False
    assert "error" in data


# ---------------------------------------------------------------------------
# AC: dispatcher next does not return a completed task
# Verify: test_next_skips_completed
# ---------------------------------------------------------------------------

def test_next_skips_completed(tmp_env, store):
    from tests.dispatcher.helpers import seed_tasks
    tasks = seed_tasks(store)
    ready = next(t for t in tasks if t.status == "ready")

    _run(["claim", ready.task_id, "--agent", "codex", "--json"])
    _run(["complete", ready.task_id, "--agent", "codex", "--json"])

    code, data = _run(["next", "--agent", "codex", "--json"])
    assert code == 0
    assert data["ok"] is True
    if data.get("task"):
        assert data["task"]["task_id"] != ready.task_id


# ---------------------------------------------------------------------------
# AC: task.completed event appears in dispatcher events --json
# Verify: test_complete_event_emitted
# ---------------------------------------------------------------------------

def test_complete_event_emitted(tmp_env, store):
    from tests.dispatcher.helpers import seed_tasks
    tasks = seed_tasks(store)
    ready = next(t for t in tasks if t.status == "ready")

    _run(["claim", ready.task_id, "--agent", "codex", "--json"])
    _run(["complete", ready.task_id, "--agent", "codex", "--json"])

    code, data = _run(["events", "--tail", "20", "--json"])
    assert code == 0
    assert data["ok"] is True
    events = data.get("events", [])
    completed_events = [e for e in events if e.get("event_type") == "task.completed"]
    assert len(completed_events) > 0
    assert completed_events[0]["task_id"] == ready.task_id


# ---------------------------------------------------------------------------
# AC: python -m app.dispatcher pull --repo <repo> --json upserts open
#     agent:ready issues and prints a sync receipt.
# Verify: test_pull_command_upserts_issues
# ---------------------------------------------------------------------------

def test_pull_command_upserts_issues(tmp_env):
    """pull command uses gh-backed source to upsert issues into the queue."""
    from unittest.mock import MagicMock, patch
    from app.dispatcher.sync_github import GitHubIssueSource

    _run(["init", "--json"])

    # Mock the GitHub source to avoid real API calls
    mock_source = MagicMock(spec=GitHubIssueSource)
    mock_source.list_issues.return_value = [
        {
            "number": 101,
            "title": "Test issue 1",
            "state": "open",
            "labels": [{"name": "prio:high"}, {"name": "agent:ready"}],
            "createdAt": "2026-04-20T10:00:00Z",
            "updatedAt": "2026-04-21T12:00:00Z",
            "body": VALID_READY_BODY,
        },
        {
            "number": 102,
            "title": "Test issue 2",
            "state": "open",
            "labels": [{"name": "prio:med"}],
            "createdAt": "2026-04-20T10:00:00Z",
            "updatedAt": "2026-04-21T12:00:00Z",
        },
    ]
    mock_source.get_rate_limit.return_value = {"remaining": 5000, "reset": "2026-04-25T10:00:00Z"}

    with patch("app.dispatcher.cli.GhCliIssueSource", return_value=mock_source):
        code, data = _run(["pull", "--repo", "test/repo", "--json"])

    assert code == 0
    assert data["ok"] is True
    assert data["upserted"] == 2
    assert data["provider"] == "github"

    # Verify tasks were actually stored (2 real issues + 1 sync metadata record)
    code, queue_data = _run(["queue", "--json"])
    assert code == 0
    assert len(queue_data["tasks"]) >= 2
    # Verify at least the expected issues are there
    task_ids = {t["issue_number"] for t in queue_data["tasks"]}
    assert 101 in task_ids
    assert 102 in task_ids


def test_pull_command_multi_repo_aggregates_and_qualifies_ids(tmp_env):
    """pull --repo A --repo B pulls both repos and repo-qualifies task ids."""
    from unittest.mock import MagicMock, patch
    from app.dispatcher.sync_github import GitHubIssueSource

    _run(["init", "--json"])

    def _issue(number: int, title: str) -> dict:
        return {
            "number": number,
            "title": title,
            "state": "open",
            "labels": [{"name": "prio:high"}, {"name": "agent:ready"}],
            "createdAt": "2026-04-20T10:00:00Z",
            "updatedAt": "2026-04-21T12:00:00Z",
            "body": VALID_READY_BODY,
        }

    # Both repos expose an issue #21 — the collision case.
    per_repo = {
        "RasmusTho/agentic-pkm-mvp": [_issue(21, "apkm twenty-one")],
        "RasmusTho/bifrost": [_issue(21, "bifrost twenty-one")],
    }

    mock_source = MagicMock(spec=GitHubIssueSource)
    mock_source.list_issues.side_effect = lambda repo, **_k: per_repo[repo]
    mock_source.list_open_issues.side_effect = lambda repo, **_k: per_repo[repo]
    mock_source.get_rate_limit.return_value = {"remaining": 5000, "reset": None}

    with patch("app.dispatcher.cli.GhCliIssueSource", return_value=mock_source):
        code, data = _run([
            "pull",
            "--repo", "RasmusTho/agentic-pkm-mvp",
            "--repo", "RasmusTho/bifrost",
            "--json",
        ])

    assert code == 0, data
    assert data["ok"] is True
    assert data["upserted"] == 2
    assert set(data["repos"].keys()) == {
        "RasmusTho/agentic-pkm-mvp",
        "RasmusTho/bifrost",
    }

    # Both #21 tasks stored distinctly, neither clobbered.
    code, queue_data = _run(["queue", "--json"])
    assert code == 0
    task_ids = {t["task_id"] for t in queue_data["tasks"]}
    assert "github-RasmusTho--agentic-pkm-mvp-issue-21" in task_ids
    assert "github-RasmusTho--bifrost-issue-21" in task_ids


def test_pull_command_reports_sync_source_failure(tmp_env):
    """pull command surfaces adapter-recorded source failures in its receipt."""
    from unittest.mock import MagicMock, patch
    from app.dispatcher.sync_github import GitHubIssueSource

    _run(["init", "--json"])

    mock_source = MagicMock(spec=GitHubIssueSource)
    mock_source.list_issues.side_effect = RuntimeError("network error")
    mock_source.get_rate_limit.return_value = None

    with patch("app.dispatcher.cli.GhCliIssueSource", return_value=mock_source):
        code, data = _run(["pull", "--repo", "test/repo", "--json"])

    assert code == 1
    assert data["ok"] is False
    assert data["provider"] == "github"
    assert data["sync_result"] == "error"
    assert "network error" in data["error"]


# ---------------------------------------------------------------------------
# AC: dispatcher next --json on a missing DB exits 1 with
#     {"ok": false, "error": "...dispatcher not initialised..."}
# Verify: test_guard_missing_db
# ---------------------------------------------------------------------------

def test_guard_missing_db(tmp_env):
    """Commands requiring a DB exit 1 with clear error when DB is missing."""
    # Don't initialize, so DB is missing
    code, data = _run(["next", "--agent", "test-agent", "--json"])
    assert code == 1
    assert data["ok"] is False
    assert "not initialised" in data["error"]
    assert "dispatcher-init" in data["error"]
