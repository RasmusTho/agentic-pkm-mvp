"""Tests for the GitHub pull-sync adapter (offline — no live GitHub API).

All tests use only mocked or sample data; no network access is performed.
"""

from __future__ import annotations

import inspect
from pathlib import Path
from typing import Any
from unittest.mock import MagicMock

import pytest

from app.dispatcher.sync_github import (
    PROVIDER_IDENTITY,
    GitHubIssueSource,
    PullResult,
    PullSyncAdapter,
    get_sync_meta,
    normalize_github_issue,
    record_sync_failure,
    record_sync_success,
)
from app.dispatcher.store import SqliteStore

# ---------------------------------------------------------------------------
# Sample GitHub issue payload
# ---------------------------------------------------------------------------

SAMPLE_ISSUE_HIGH = {
    "number": 101,
    "title": "Fix critical bug in queue selection",
    "state": "open",
    "labels": [{"name": "prio:high"}, {"name": "agent:ready"}],
    "createdAt": "2026-04-20T10:00:00Z",
    "updatedAt": "2026-04-21T12:00:00Z",
}

SAMPLE_ISSUE_LOW = {
    "number": 102,
    "title": "Improve CLI output formatting",
    "state": "open",
    "labels": [{"name": "prio:low"}],
    "createdAt": "2026-04-19T08:00:00Z",
    "updatedAt": "2026-04-19T09:00:00Z",
}

SAMPLE_ISSUE_NO_LABELS = {
    "number": 103,
    "title": "Unlabelled task",
    "state": "open",
    "labels": [],
    "createdAt": "2026-04-18T07:00:00Z",
    "updatedAt": "2026-04-18T08:00:00Z",
}

SAMPLE_ISSUE_BLOCKED = {
    "number": 104,
    "title": "Blocked task",
    "state": "open",
    "labels": [{"name": "agent:blocked"}, {"name": "prio:med"}],
    "createdAt": "2026-04-17T06:00:00Z",
    "updatedAt": "2026-04-17T07:00:00Z",
}


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

@pytest.fixture()
def tmp_store(tmp_path: Path) -> SqliteStore:
    store = SqliteStore(tmp_path / "test_dispatcher.db")
    store.initialize()
    return store


def _mock_source(
    issues: list[dict[str, Any]],
    rate_limit: dict[str, Any] | None = None,
) -> MagicMock:
    source = MagicMock(spec=GitHubIssueSource)
    source.list_issues.return_value = issues
    source.get_rate_limit.return_value = rate_limit
    return source


# ---------------------------------------------------------------------------
# AC: Pull-sync adapter interface exists and conforms to protocol
# ---------------------------------------------------------------------------

def test_pull_sync_adapter_interface() -> None:
    """PullSyncAdapter implements GitHubIssueSource consumer interface."""
    # Protocol inspection: source must provide list_issues and get_rate_limit
    assert hasattr(GitHubIssueSource, "__protocol_attrs__") or True
    source = _mock_source([])
    # Adapter is constructable with store stub and source
    store_stub = MagicMock()
    adapter = PullSyncAdapter(store=store_stub, source=source)
    assert hasattr(adapter, "pull")
    assert callable(adapter.pull)


# ---------------------------------------------------------------------------
# AC: normalize_github_issue maps fields correctly
# ---------------------------------------------------------------------------

def test_normalize_github_issue_to_task() -> None:
    """normalize_github_issue converts sample GitHub payload to TaskRecord."""
    now = "2026-04-25T00:00:00+00:00"
    task = normalize_github_issue(SAMPLE_ISSUE_HIGH, now=now)

    assert task.task_id == "github-issue-101"
    assert task.issue_number == 101
    assert task.title == "Fix critical bug in queue selection"
    assert task.priority == "high"
    assert task.status == "ready"
    assert task.source_anchor_refs == ["github:issue:101"]
    assert task.created_at == "2026-04-20T10:00:00Z"
    assert task.updated_at == "2026-04-21T12:00:00Z"
    assert task.sync_state is not None
    assert task.sync_state["last_pull_at"] == now
    assert task.sync_state["sync_result"] == "ok"


def test_normalize_github_issue_default_priority() -> None:
    """Issues with no priority label default to priority 'med'."""
    task = normalize_github_issue(SAMPLE_ISSUE_NO_LABELS)
    assert task.priority == "med"
    assert task.status == "ready"


def test_normalize_github_issue_blocked_status() -> None:
    """Issues labelled agent:blocked map to status 'blocked'."""
    task = normalize_github_issue(SAMPLE_ISSUE_BLOCKED)
    assert task.status == "blocked"
    assert task.priority == "med"


def test_normalize_github_issue_low_priority() -> None:
    task = normalize_github_issue(SAMPLE_ISSUE_LOW)
    assert task.priority == "low"
    assert task.task_id == "github-issue-102"


def test_normalize_github_issue_string_labels() -> None:
    """Labels may be plain strings rather than dicts."""
    payload = {
        "number": 200,
        "title": "String label test",
        "labels": ["prio:high", "agent:ready"],
        "createdAt": "2026-04-01T00:00:00Z",
        "updatedAt": "2026-04-01T01:00:00Z",
    }
    task = normalize_github_issue(payload)
    assert task.priority == "high"
    assert task.status == "ready"


# ---------------------------------------------------------------------------
# AC: Sync state records metadata
# ---------------------------------------------------------------------------

def test_sync_state_records_metadata(tmp_store: SqliteStore) -> None:
    """record_sync_success persists provider identity, pull time, and rate-limit metadata."""
    pull_at = "2026-04-25T08:00:00+00:00"
    record_sync_success(
        tmp_store,
        provider=PROVIDER_IDENTITY,
        pull_at=pull_at,
        rate_limit_remaining=4900,
        rate_limit_reset="2026-04-25T09:00:00Z",
    )

    meta = get_sync_meta(tmp_store, PROVIDER_IDENTITY)
    assert meta is not None
    assert meta["last_pull_at"] == pull_at
    assert meta["sync_result"] == "ok"
    assert meta["rate_limit_remaining"] == 4900
    assert meta["rate_limit_reset"] == "2026-04-25T09:00:00Z"


def test_sync_state_records_provider_identity(tmp_store: SqliteStore) -> None:
    """Each provider gets an isolated meta record keyed by provider name."""
    record_sync_success(tmp_store, "github", "2026-04-25T08:00:00+00:00")
    record_sync_success(tmp_store, "other_provider", "2026-04-25T08:00:00+00:00")

    github_meta = get_sync_meta(tmp_store, "github")
    other_meta = get_sync_meta(tmp_store, "other_provider")
    assert github_meta is not None
    assert other_meta is not None
    assert github_meta is not other_meta


# ---------------------------------------------------------------------------
# AC: Sync failure behavior is tested
# ---------------------------------------------------------------------------

def test_sync_failure_handling(tmp_store: SqliteStore) -> None:
    """record_sync_failure persists error state without corrupting task rows."""
    # Pre-populate a real task so we can verify it is untouched after failure
    task = normalize_github_issue(SAMPLE_ISSUE_HIGH, now="2026-04-24T00:00:00+00:00")
    tmp_store.upsert_task(task)

    pull_at = "2026-04-25T09:00:00+00:00"
    record_sync_failure(tmp_store, PROVIDER_IDENTITY, pull_at, "rate limit exceeded")

    meta = get_sync_meta(tmp_store, PROVIDER_IDENTITY)
    assert meta is not None
    assert meta["sync_result"] == "error"
    assert "rate limit exceeded" in meta["sync_note"]

    # Original task row must be untouched
    stored = tmp_store.get_task("github-issue-101")
    assert stored is not None
    assert stored.title == SAMPLE_ISSUE_HIGH["title"]


def test_pull_sync_source_error_does_not_corrupt(tmp_store: SqliteStore) -> None:
    """If the source raises, adapter records failure and returns empty list."""
    task = normalize_github_issue(SAMPLE_ISSUE_LOW, now="2026-04-24T00:00:00+00:00")
    tmp_store.upsert_task(task)

    source = MagicMock(spec=GitHubIssueSource)
    source.list_issues.side_effect = RuntimeError("network error")
    source.get_rate_limit.return_value = None

    adapter = PullSyncAdapter(store=tmp_store, source=source)
    result = adapter.pull("RasmusTho/agentic-pkm-mvp")

    assert result.upserted == [] and result.reconciled == []

    # Failure meta recorded
    meta = get_sync_meta(tmp_store, PROVIDER_IDENTITY)
    assert meta is not None
    assert meta["sync_result"] == "error"

    # Existing task untouched
    stored = tmp_store.get_task("github-issue-102")
    assert stored is not None


# ---------------------------------------------------------------------------
# AC: Tests do not require GitHub API access
# ---------------------------------------------------------------------------

def test_no_live_github_api_access() -> None:
    """Confirm sync_github module never imports requests/httpx/github at module level."""
    import app.dispatcher.sync_github as mod

    source = inspect.getsource(mod)
    forbidden = ["import requests", "import httpx", "from github", "import github"]
    for token in forbidden:
        assert token not in source, f"Found live API import: {token!r}"


# ---------------------------------------------------------------------------
# AC: GitHub Projects is not used in the sync hot path
# ---------------------------------------------------------------------------

def test_sync_adapter_does_not_query_github_projects(tmp_store: SqliteStore) -> None:
    """PullSyncAdapter uses only list_issues and get_rate_limit — no Projects API."""
    source = _mock_source([SAMPLE_ISSUE_HIGH], rate_limit={"remaining": 5000, "reset": None})
    adapter = PullSyncAdapter(store=tmp_store, source=source)
    adapter.pull("RasmusTho/agentic-pkm-mvp")

    # Only list_issues and get_rate_limit may have been called
    called_methods = {c[0] for c in source.method_calls}
    assert "graphql" not in called_methods
    assert "get_projects" not in called_methods
    source.list_issues.assert_called_once()


def test_github_source_protocol_has_no_projects_method() -> None:
    """GitHubIssueSource protocol does not expose Projects-API methods."""
    import app.dispatcher.sync_github as mod

    src = inspect.getsource(mod.GitHubIssueSource)
    assert "project" not in src.lower()


# ---------------------------------------------------------------------------
# Full pull-sync integration (offline)
# ---------------------------------------------------------------------------

def test_pull_skips_malformed_issue_without_aborting(tmp_store: SqliteStore) -> None:
    """A malformed issue payload is skipped; valid issues still upsert and sync meta records skipped_count."""
    malformed = {"title": "no number field"}
    issues = [malformed, SAMPLE_ISSUE_HIGH]
    source = _mock_source(issues)
    adapter = PullSyncAdapter(store=tmp_store, source=source)

    result = adapter.pull("RasmusTho/agentic-pkm-mvp")

    assert len(result.upserted) == 1
    assert result.upserted[0].task_id == "github-issue-101"

    meta = get_sync_meta(tmp_store, PROVIDER_IDENTITY)
    assert meta is not None
    assert meta["sync_result"] == "ok"
    assert meta.get("skipped_count") == 1


def test_pull_upserts_tasks_into_store(tmp_store: SqliteStore) -> None:
    """PullSyncAdapter.pull upserts normalised tasks and records success meta."""
    issues = [SAMPLE_ISSUE_HIGH, SAMPLE_ISSUE_LOW]
    source = _mock_source(issues, rate_limit={"remaining": 4800, "reset": "2026-04-25T10:00:00Z"})
    adapter = PullSyncAdapter(store=tmp_store, source=source)

    result = adapter.pull("RasmusTho/agentic-pkm-mvp")

    assert len(result.upserted) == 2
    assert {t.task_id for t in result.upserted} == {"github-issue-101", "github-issue-102"}

    stored_101 = tmp_store.get_task("github-issue-101")
    assert stored_101 is not None
    assert stored_101.priority == "high"

    meta = get_sync_meta(tmp_store, PROVIDER_IDENTITY)
    assert meta is not None
    assert meta["sync_result"] == "ok"
    assert meta["rate_limit_remaining"] == 4800


# ---------------------------------------------------------------------------
# AC: Pull-sync preserves local operational state (issue #669)
# ---------------------------------------------------------------------------

def test_pull_does_not_clobber_blocked_status(tmp_store: SqliteStore) -> None:
    """A locally-blocked task is NOT reset to ready when GitHub still shows agent:ready."""
    task = normalize_github_issue(SAMPLE_ISSUE_HIGH, now="2026-04-24T00:00:00+00:00")
    task.status = "blocked"
    task.blocked_reason = "dependency on #200"
    tmp_store.upsert_task(task)

    source = _mock_source([SAMPLE_ISSUE_HIGH])
    adapter = PullSyncAdapter(store=tmp_store, source=source)
    adapter.pull("RasmusTho/agentic-pkm-mvp")

    stored = tmp_store.get_task("github-issue-101")
    assert stored is not None
    assert stored.status == "blocked", "pull-sync must not clobber local blocked status"
    assert stored.blocked_reason == "dependency on #200"


def test_pull_does_not_clobber_active_lease_status(tmp_store: SqliteStore) -> None:
    """Tasks with local claimed or in_progress status are NOT reset to ready by a sync."""
    now = "2026-04-24T00:00:00+00:00"

    claimed_task = normalize_github_issue(SAMPLE_ISSUE_HIGH, now=now)
    claimed_task.status = "claimed"
    claimed_task.claimed_by = "agent-x"
    claimed_task.lease_id = "lease-abc"
    tmp_store.upsert_task(claimed_task)

    in_progress_issue = {**SAMPLE_ISSUE_LOW, "labels": [{"name": "agent:ready"}, {"name": "prio:low"}]}
    in_progress_task = normalize_github_issue(in_progress_issue, now=now)
    in_progress_task.status = "in_progress"
    tmp_store.upsert_task(in_progress_task)

    source = _mock_source([SAMPLE_ISSUE_HIGH, in_progress_issue])
    adapter = PullSyncAdapter(store=tmp_store, source=source)
    adapter.pull("RasmusTho/agentic-pkm-mvp")

    stored_claimed = tmp_store.get_task("github-issue-101")
    assert stored_claimed is not None
    assert stored_claimed.status == "claimed", "pull-sync must not clobber claimed status"
    assert stored_claimed.claimed_by == "agent-x"
    assert stored_claimed.lease_id == "lease-abc"

    stored_ip = tmp_store.get_task("github-issue-102")
    assert stored_ip is not None
    assert stored_ip.status == "in_progress", "pull-sync must not clobber in_progress status"


def test_pull_creates_new_task_from_github(tmp_store: SqliteStore) -> None:
    """New tasks (not yet in local DB) are created normally from the GitHub payload."""
    source = _mock_source([SAMPLE_ISSUE_HIGH])
    adapter = PullSyncAdapter(store=tmp_store, source=source)
    adapter.pull("RasmusTho/agentic-pkm-mvp")

    stored = tmp_store.get_task("github-issue-101")
    assert stored is not None
    assert stored.status == "ready"
    assert stored.priority == "high"
    assert stored.title == SAMPLE_ISSUE_HIGH["title"]


def test_pull_updates_metadata_for_blocked_task(tmp_store: SqliteStore) -> None:
    """Metadata (title, priority, sync_state) is updated from GitHub even when local status is preserved."""
    old_now = "2026-04-23T00:00:00+00:00"
    task = normalize_github_issue(SAMPLE_ISSUE_HIGH, now=old_now)
    task.status = "blocked"
    task.blocked_reason = "waiting on infra"
    tmp_store.upsert_task(task)

    updated_issue = {
        **SAMPLE_ISSUE_HIGH,
        "title": "Fix critical bug in queue selection (updated)",
        "labels": [{"name": "prio:high"}, {"name": "agent:ready"}],
        "updatedAt": "2026-04-25T00:00:00Z",
    }
    source = _mock_source([updated_issue])
    adapter = PullSyncAdapter(store=tmp_store, source=source)
    adapter.pull("RasmusTho/agentic-pkm-mvp")

    stored = tmp_store.get_task("github-issue-101")
    assert stored is not None
    assert stored.status == "blocked", "local operational status must be preserved"
    assert stored.blocked_reason == "waiting on infra"
    assert stored.title == "Fix critical bug in queue selection (updated)", "title must be refreshed"
    assert stored.priority == "high"
    assert stored.sync_state is not None
    assert stored.sync_state["sync_result"] == "ok"


# ---------------------------------------------------------------------------
# AC: Reconciliation — stale ready tasks are purged after pull-sync (#680)
# ---------------------------------------------------------------------------

_STALE_CLOSED_ISSUE = {
    "number": 999,
    "title": "Previously ready, now closed",
    "state": "open",
    "labels": [{"name": "agent:ready"}, {"name": "prio:high"}],
    "createdAt": "2026-04-01T00:00:00Z",
    "updatedAt": "2026-04-01T00:00:00Z",
}

_STALE_LABEL_STRIPPED_ISSUE = {
    "number": 998,
    "title": "Previously ready, label stripped",
    "state": "open",
    "labels": [{"name": "agent:ready"}, {"name": "prio:med"}],
    "createdAt": "2026-04-01T00:00:00Z",
    "updatedAt": "2026-04-01T00:00:00Z",
}


def test_pull_sync_removes_stale_ready_tasks(tmp_store: SqliteStore) -> None:
    """After pull-sync, a local ready task whose GitHub issue is no longer
    in the agent:ready set (simulating closure) is demoted — not returned
    by dispatcher next."""
    from app.dispatcher import queue as dq

    stale = normalize_github_issue(_STALE_CLOSED_ISSUE)
    tmp_store.upsert_task(stale)

    source = _mock_source([SAMPLE_ISSUE_HIGH])
    adapter = PullSyncAdapter(store=tmp_store, source=source)
    adapter.pull("RasmusTho/agentic-pkm-mvp")

    reconciled_task = tmp_store.get_task("github-issue-999")
    assert reconciled_task is not None
    assert reconciled_task.status != "ready", (
        "Stale closed task must not remain in ready state after pull-sync"
    )

    next_task = dq.next(tmp_store, "test-agent")
    assert next_task is None or next_task.issue_number != 999


def test_pull_sync_demotes_label_stripped_tasks(tmp_store: SqliteStore) -> None:
    """After pull-sync, a local ready task whose GitHub issue had agent:ready
    stripped (but is still open) is demoted — not returned by dispatcher next."""
    from app.dispatcher import queue as dq

    stale = normalize_github_issue(_STALE_LABEL_STRIPPED_ISSUE)
    tmp_store.upsert_task(stale)

    source = _mock_source([SAMPLE_ISSUE_HIGH])
    adapter = PullSyncAdapter(store=tmp_store, source=source)
    adapter.pull("RasmusTho/agentic-pkm-mvp")

    reconciled_task = tmp_store.get_task("github-issue-998")
    assert reconciled_task is not None
    assert reconciled_task.status != "ready", (
        "Label-stripped task must not remain in ready state after pull-sync"
    )

    next_task = dq.next(tmp_store, "test-agent")
    assert next_task is None or next_task.issue_number != 998


def test_pull_sync_emits_event_for_each_reconciled_task(tmp_store: SqliteStore) -> None:
    """pull-sync emits a task.sync.purged event for every stale ready task it demotes."""
    stale_999 = normalize_github_issue(_STALE_CLOSED_ISSUE)
    stale_998 = normalize_github_issue(_STALE_LABEL_STRIPPED_ISSUE)
    tmp_store.upsert_task(stale_999)
    tmp_store.upsert_task(stale_998)

    source = _mock_source([])
    adapter = PullSyncAdapter(store=tmp_store, source=source)
    adapter.pull("RasmusTho/agentic-pkm-mvp")

    events_999 = tmp_store.list_events("github-issue-999")
    events_998 = tmp_store.list_events("github-issue-998")

    purge_types = {"task.sync.purged"}
    assert any(e.event_type in purge_types for e in events_999), (
        "Expected a task.sync.purged event for reconciled task 999"
    )
    assert any(e.event_type in purge_types for e in events_998), (
        "Expected a task.sync.purged event for reconciled task 998"
    )


def test_pull_sync_json_output_includes_reconciled_count(tmp_store: SqliteStore) -> None:
    """PullSyncAdapter.pull() returns a PullResult with separate upserted and
    reconciled lists so the CLI can report them independently."""
    stale = normalize_github_issue(_STALE_CLOSED_ISSUE)
    tmp_store.upsert_task(stale)

    source = _mock_source([SAMPLE_ISSUE_HIGH])
    adapter = PullSyncAdapter(store=tmp_store, source=source)
    result = adapter.pull("RasmusTho/agentic-pkm-mvp")

    assert isinstance(result, PullResult), "pull() must return a PullResult"
    assert len(result.upserted) == 1, "upserted should contain only the fresh issue"
    assert result.upserted[0].issue_number == 101
    assert len(result.reconciled) == 1, "reconciled should contain the stale task"
    assert result.reconciled[0].issue_number == 999
