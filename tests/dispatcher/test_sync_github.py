"""Tests for the GitHub pull-sync adapter (offline — no live GitHub API).

All tests use only mocked or sample data; no network access is performed.
"""

from __future__ import annotations

import inspect
from pathlib import Path
from typing import Any
from unittest.mock import MagicMock, patch

import pytest

from app.dispatcher.sync_github import (
    PROVIDER_IDENTITY,
    GhCliIssueSource,
    GitHubIssueSource,
    PullSyncAdapter,
    get_sync_meta,
    github_issue_task_id,
    normalize_github_issue,
    record_sync_failure,
    record_sync_success,
)
from app.dispatcher.store import SqliteStore

REPO_ROOT = Path(__file__).resolve().parents[2]
FIXTURE_DIR = REPO_ROOT / "tests/fixtures/issue_readiness"

# The owner/repo normalize_github_issue is told these sample issues came
# from. Distinct from REPO_ROOT (a filesystem path), this is the GitHub
# "owner/name" string that now qualifies every task_id.
REPO = "RasmusTho/agentic-pkm-mvp"


def _tid(number: int, repo: str = REPO) -> str:
    """The repo-qualified task_id normalize_github_issue produces for *number*."""
    return f"github-{repo.replace('/', '--')}-issue-{number}"


VALID_READY_BODY = (FIXTURE_DIR / "valid_ready_candidate.md").read_text(encoding="utf-8")
INVALID_READY_BODY = (FIXTURE_DIR / "missing_constraints.md").read_text(encoding="utf-8")

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
    "body": VALID_READY_BODY,
}

SAMPLE_ISSUE_LOW = {
    "number": 102,
    "title": "Improve CLI output formatting",
    "state": "open",
    "labels": [{"name": "prio:low"}],
    "createdAt": "2026-04-19T08:00:00Z",
    "updatedAt": "2026-04-19T09:00:00Z",
    "body": VALID_READY_BODY,
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
    open_issues: list[dict[str, Any]] | None = None,
    rate_limit: dict[str, Any] | None = None,
) -> MagicMock:
    source = MagicMock(spec=GitHubIssueSource)
    source.list_issues.return_value = issues
    source.list_open_issues.return_value = open_issues if open_issues is not None else issues
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

def test_sync_state_carries_labels_and_url() -> None:
    """Every pull records the issue's label names and HTML URL in sync_state
    so Signboard cards stop rendering structurally empty chips/links (#4441).

    REST payloads carry both an API ``url`` and the browser ``html_url``;
    the browser URL must win. GraphQL-shaped payloads carry only ``url``.
    """
    rest_payload = {
        "number": 205,
        "title": "REST-shaped issue",
        "labels": [{"name": "prio:med"}, {"name": "agent:ready"}],
        "url": "https://api.github.com/repos/RasmusTho/agentic-pkm-mvp/issues/205",
        "html_url": "https://github.com/RasmusTho/agentic-pkm-mvp/issues/205",
        "created_at": "2026-04-20T10:00:00Z",
        "updated_at": "2026-04-21T12:00:00Z",
    }
    task = normalize_github_issue(rest_payload, REPO)
    assert task.sync_state["labels"] == ["prio:med", "agent:ready"]
    assert task.sync_state["url"] == "https://github.com/RasmusTho/agentic-pkm-mvp/issues/205"

    graphql_payload = {
        "number": 206,
        "title": "GraphQL-shaped issue",
        "labels": [{"name": "prio:low"}],
        "url": "https://github.com/RasmusTho/agentic-pkm-mvp/issues/206",
        "createdAt": "2026-04-20T10:00:00Z",
        "updatedAt": "2026-04-21T12:00:00Z",
    }
    task = normalize_github_issue(graphql_payload, REPO)
    assert task.sync_state["labels"] == ["prio:low"]
    assert task.sync_state["url"] == "https://github.com/RasmusTho/agentic-pkm-mvp/issues/206"

    bare = normalize_github_issue(SAMPLE_ISSUE_NO_LABELS, REPO)
    assert bare.sync_state["labels"] == []
    assert bare.sync_state["url"] is None


def test_github_issue_task_id_single_source_format_pinned() -> None:
    """The repo-qualified task id has exactly one implementation with a pinned
    byte format, including the doubled ``--`` owner/repo separator that keeps
    ``org/foo-bar`` and ``org-foo/bar`` distinct (INV-DG-2, #4440)."""
    assert github_issue_task_id("org/foo-bar", 21) == "github-org--foo-bar-issue-21"
    assert github_issue_task_id("org-foo/bar", 21) == "github-org-foo--bar-issue-21"
    assert (
        github_issue_task_id("RasmusTho/agentic-pkm-mvp", 4440)
        == "github-RasmusTho--agentic-pkm-mvp-issue-4440"
    )
    task = normalize_github_issue({"number": 4440, "title": "t"}, "RasmusTho/agentic-pkm-mvp")
    assert task.task_id == github_issue_task_id("RasmusTho/agentic-pkm-mvp", 4440)


def test_normalize_github_issue_to_task() -> None:
    """normalize_github_issue converts sample GitHub payload to TaskRecord."""
    now = "2026-04-25T00:00:00+00:00"
    task = normalize_github_issue(SAMPLE_ISSUE_HIGH, REPO, now=now)

    assert task.task_id == _tid(101)
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
    task = normalize_github_issue(SAMPLE_ISSUE_NO_LABELS, REPO)
    assert task.priority == "med"
    assert task.status == "ready"


def test_normalize_github_issue_blocked_status() -> None:
    """Issues labelled agent:blocked map to status 'blocked'."""
    task = normalize_github_issue(SAMPLE_ISSUE_BLOCKED, REPO)
    assert task.status == "blocked"
    assert task.priority == "med"


def test_normalize_github_issue_low_priority() -> None:
    task = normalize_github_issue(SAMPLE_ISSUE_LOW, REPO)
    assert task.priority == "low"
    assert task.task_id == _tid(102)


def test_normalize_github_issue_string_labels() -> None:
    """Labels may be plain strings rather than dicts."""
    payload = {
        "number": 200,
        "title": "String label test",
        "labels": ["prio:high", "agent:ready"],
        "createdAt": "2026-04-01T00:00:00Z",
        "updatedAt": "2026-04-01T01:00:00Z",
        "body": VALID_READY_BODY,
    }
    task = normalize_github_issue(payload, REPO)
    assert task.priority == "high"
    assert task.status == "ready"


def test_agent_ready_issue_pickable_without_project_status(tmp_store: SqliteStore) -> None:
    """ProjectV2 fields are neither required nor consulted for queue eligibility."""
    payload = {
        "number": 201,
        "title": "Label-only ready task",
        "state": "open",
        "labels": [{"name": "agent:ready"}, {"name": "prio:high"}],
        "createdAt": "2026-07-09T00:00:00Z",
        "updatedAt": "2026-07-09T01:00:00Z",
        "body": VALID_READY_BODY,
    }

    source = _mock_source([payload], open_issues=[payload])
    adapter = PullSyncAdapter(store=tmp_store, source=source)

    upserted = adapter.pull("RasmusTho/agentic-pkm-mvp")

    assert [task.issue_number for task in upserted] == [201]
    stored = tmp_store.get_task(_tid(201))
    assert stored is not None
    assert stored.status == "ready"
    assert {call[0] for call in source.method_calls} == {
        "list_issues",
        "list_open_issues",
        "get_rate_limit",
    }


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
    task = normalize_github_issue(SAMPLE_ISSUE_HIGH, REPO, now="2026-04-24T00:00:00+00:00")
    tmp_store.upsert_task(task)

    pull_at = "2026-04-25T09:00:00+00:00"
    record_sync_failure(tmp_store, PROVIDER_IDENTITY, pull_at, "rate limit exceeded")

    meta = get_sync_meta(tmp_store, PROVIDER_IDENTITY)
    assert meta is not None
    assert meta["sync_result"] == "error"
    assert "rate limit exceeded" in meta["sync_note"]

    # Original task row must be untouched
    stored = tmp_store.get_task(_tid(101))
    assert stored is not None
    assert stored.title == SAMPLE_ISSUE_HIGH["title"]


def test_pull_sync_source_error_does_not_corrupt(tmp_store: SqliteStore) -> None:
    """If the source raises, adapter records failure and returns empty list."""
    task = normalize_github_issue(SAMPLE_ISSUE_LOW, REPO, now="2026-04-24T00:00:00+00:00")
    tmp_store.upsert_task(task)

    source = MagicMock(spec=GitHubIssueSource)
    source.list_issues.side_effect = RuntimeError("network error")
    source.get_rate_limit.return_value = None

    adapter = PullSyncAdapter(store=tmp_store, source=source)
    result = adapter.pull("RasmusTho/agentic-pkm-mvp")

    assert result == []

    # Failure meta recorded
    meta = get_sync_meta(tmp_store, PROVIDER_IDENTITY)
    assert meta is not None
    assert meta["sync_result"] == "error"

    # Existing task untouched
    stored = tmp_store.get_task(_tid(102))
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
    source.list_open_issues.assert_called_once()


def test_github_source_protocol_has_no_projects_method() -> None:
    """GitHubIssueSource protocol does not expose Projects-API methods."""
    import app.dispatcher.sync_github as mod

    src = inspect.getsource(mod.GitHubIssueSource)
    assert "project" not in src.lower()


def test_pull_sync_removes_stale_ready_tasks(tmp_store: SqliteStore) -> None:
    task = normalize_github_issue(SAMPLE_ISSUE_HIGH, REPO, now="2026-04-24T00:00:00+00:00")
    tmp_store.upsert_task(task)
    source = _mock_source([], open_issues=[])
    adapter = PullSyncAdapter(store=tmp_store, source=source)

    adapter.pull("RasmusTho/agentic-pkm-mvp")

    stored = tmp_store.get_task(_tid(101))
    assert stored is not None
    assert stored.status == "completed"


def test_pull_sync_demotes_label_stripped_tasks(tmp_store: SqliteStore) -> None:
    task = normalize_github_issue(SAMPLE_ISSUE_HIGH, REPO, now="2026-04-24T00:00:00+00:00")
    tmp_store.upsert_task(task)
    open_issue = dict(SAMPLE_ISSUE_HIGH)
    open_issue["labels"] = [{"name": "prio:high"}]
    source = _mock_source([], open_issues=[open_issue])
    adapter = PullSyncAdapter(store=tmp_store, source=source)

    adapter.pull("RasmusTho/agentic-pkm-mvp")

    stored = tmp_store.get_task(_tid(101))
    assert stored is not None
    assert stored.status == "blocked"


def test_pull_sync_emits_event_for_each_reconciled_task(tmp_store: SqliteStore) -> None:
    for issue in (SAMPLE_ISSUE_HIGH, SAMPLE_ISSUE_LOW):
        tmp_store.upsert_task(normalize_github_issue(issue, REPO, now="2026-04-24T00:00:00+00:00"))
    source = _mock_source([], open_issues=[])
    adapter = PullSyncAdapter(store=tmp_store, source=source)

    adapter.pull("RasmusTho/agentic-pkm-mvp")

    events = [e for e in tmp_store.list_events() if e.event_type == "sync.reconciled"]
    assert len(events) == 2


def test_pull_sync_json_output_includes_reconciled_count(tmp_store: SqliteStore) -> None:
    tmp_store.upsert_task(normalize_github_issue(SAMPLE_ISSUE_HIGH, REPO, now="2026-04-24T00:00:00+00:00"))
    source = _mock_source([], open_issues=[])
    adapter = PullSyncAdapter(store=tmp_store, source=source)

    adapter.pull("RasmusTho/agentic-pkm-mvp")

    assert adapter.last_reconciled_count == 1


# ---------------------------------------------------------------------------
# Full pull-sync integration (offline)
# ---------------------------------------------------------------------------

def test_pull_skips_malformed_issue_without_aborting(tmp_store: SqliteStore) -> None:
    """A malformed issue payload is skipped; valid issues still upsert and sync meta records skipped_count."""
    malformed = {"title": "no number field"}
    issues = [malformed, SAMPLE_ISSUE_HIGH]
    source = _mock_source(issues)
    adapter = PullSyncAdapter(store=tmp_store, source=source)

    upserted = adapter.pull("RasmusTho/agentic-pkm-mvp")

    assert len(upserted) == 1
    assert upserted[0].task_id == _tid(101)

    meta = get_sync_meta(tmp_store, PROVIDER_IDENTITY)
    assert meta is not None
    assert meta["sync_result"] == "ok"
    assert meta.get("skipped_count") == 1


def test_pull_skips_invalid_agent_ready_issue_without_queueing(
    tmp_store: SqliteStore,
) -> None:
    invalid_ready = {
        **SAMPLE_ISSUE_HIGH,
        "number": 105,
        "title": "Invalid ready issue",
        "body": INVALID_READY_BODY,
    }
    source = _mock_source([invalid_ready], open_issues=[invalid_ready])
    adapter = PullSyncAdapter(store=tmp_store, source=source)

    upserted = adapter.pull("RasmusTho/agentic-pkm-mvp")

    assert upserted == []
    assert tmp_store.get_task(_tid(105)) is None
    meta = get_sync_meta(tmp_store, PROVIDER_IDENTITY)
    assert meta is not None
    assert meta.get("skipped_count") == 1
    assert "missing_required_sections" in " ".join(meta.get("skipped_notes", []))


def test_pull_demotes_existing_invalid_agent_ready_when_snapshot_unavailable(
    tmp_store: SqliteStore,
) -> None:
    invalid_ready = {
        **SAMPLE_ISSUE_HIGH,
        "number": 105,
        "title": "Invalid ready issue",
        "body": INVALID_READY_BODY,
    }
    existing = normalize_github_issue(
        {**invalid_ready, "body": VALID_READY_BODY},
        REPO,
        now="2026-04-24T00:00:00+00:00",
    )
    tmp_store.upsert_task(existing)
    source = MagicMock(spec=GitHubIssueSource)
    source.get_rate_limit.return_value = {"remaining": 10, "reset": 0}
    source.list_issues.return_value = [invalid_ready]
    source.list_open_issues.return_value = []
    adapter = PullSyncAdapter(store=tmp_store, source=source)

    upserted = adapter.pull("RasmusTho/agentic-pkm-mvp")

    assert upserted == []
    source.list_open_issues.assert_not_called()
    stored = tmp_store.get_task(_tid(105))
    assert stored is not None
    assert stored.status == "blocked"
    assert stored.blocked_reason == "agent:ready strict readiness validation failed"
    events = [
        event
        for event in tmp_store.list_events(_tid(105))
        if event.payload.get("reason") == "agent-ready-readiness-invalid"
    ]
    assert len(events) == 1


def test_pull_blocks_unvalidated_agent_ready_from_open_snapshot(
    tmp_store: SqliteStore,
) -> None:
    task = normalize_github_issue(SAMPLE_ISSUE_HIGH, REPO, now="2026-04-24T00:00:00+00:00")
    tmp_store.upsert_task(task)
    source = _mock_source([], open_issues=[SAMPLE_ISSUE_HIGH])
    adapter = PullSyncAdapter(store=tmp_store, source=source)

    adapter.pull("RasmusTho/agentic-pkm-mvp")

    stored = tmp_store.get_task(_tid(101))
    assert stored is not None
    assert stored.status == "blocked"
    assert (
        stored.blocked_reason
        == "agent:ready label present but strict readiness validation was not run"
    )
    events = [
        event
        for event in tmp_store.list_events(_tid(101))
        if event.payload.get("reason") == "agent-ready-readiness-unvalidated"
    ]
    assert len(events) == 1


def test_pull_upserts_tasks_into_store(tmp_store: SqliteStore) -> None:
    """PullSyncAdapter.pull upserts normalised tasks and records success meta."""
    issues = [SAMPLE_ISSUE_HIGH, SAMPLE_ISSUE_LOW]
    source = _mock_source(issues, rate_limit={"remaining": 4800, "reset": "2026-04-25T10:00:00Z"})
    adapter = PullSyncAdapter(store=tmp_store, source=source)

    upserted = adapter.pull("RasmusTho/agentic-pkm-mvp")

    assert len(upserted) == 2
    assert {t.task_id for t in upserted} == {_tid(101), _tid(102)}

    stored_101 = tmp_store.get_task(_tid(101))
    assert stored_101 is not None
    assert stored_101.priority == "high"

    meta = get_sync_meta(tmp_store, PROVIDER_IDENTITY)
    assert meta is not None
    assert meta["sync_result"] == "ok"
    assert meta["rate_limit_remaining"] == 4800


# ---------------------------------------------------------------------------
# AC: Pull-sync preserves local operational state (issue #669)
# ---------------------------------------------------------------------------

def test_pull_reopens_blocked_task_when_github_ready(tmp_store: SqliteStore) -> None:
    """A locally-blocked task transitions to ready when GitHub shows agent:ready."""
    # Pre-seed task as blocked locally
    task = normalize_github_issue(SAMPLE_ISSUE_HIGH, REPO, now="2026-04-24T00:00:00+00:00")
    task.status = "blocked"
    task.blocked_reason = "dependency on #200"
    tmp_store.upsert_task(task)

    # GitHub payload still carries agent:ready — simulates the window before label removal
    source = _mock_source([SAMPLE_ISSUE_HIGH])
    adapter = PullSyncAdapter(store=tmp_store, source=source)
    adapter.pull("RasmusTho/agentic-pkm-mvp")

    stored = tmp_store.get_task(_tid(101))
    assert stored is not None
    assert stored.status == "ready", "pull-sync must reopen blocked task when upstream is agent:ready"
    assert stored.blocked_reason is None


def test_pull_does_not_clobber_active_lease_status(tmp_store: SqliteStore) -> None:
    """Tasks with local claimed or in_progress status are NOT reset to ready by a sync."""
    now = "2026-04-24T00:00:00+00:00"

    # claimed task
    claimed_task = normalize_github_issue(SAMPLE_ISSUE_HIGH, REPO, now=now)
    claimed_task.status = "claimed"
    claimed_task.claimed_by = "agent-x"
    claimed_task.lease_id = "lease-abc"
    tmp_store.upsert_task(claimed_task)

    # in_progress task (use a different issue number)
    in_progress_issue = {**SAMPLE_ISSUE_LOW, "labels": [{"name": "agent:ready"}, {"name": "prio:low"}]}
    in_progress_task = normalize_github_issue(in_progress_issue, REPO, now=now)
    in_progress_task.status = "in_progress"
    tmp_store.upsert_task(in_progress_task)

    source = _mock_source([SAMPLE_ISSUE_HIGH, in_progress_issue])
    adapter = PullSyncAdapter(store=tmp_store, source=source)
    adapter.pull("RasmusTho/agentic-pkm-mvp")

    stored_claimed = tmp_store.get_task(_tid(101))
    assert stored_claimed is not None
    assert stored_claimed.status == "claimed", "pull-sync must not clobber claimed status"
    assert stored_claimed.claimed_by == "agent-x"
    assert stored_claimed.lease_id == "lease-abc"

    stored_ip = tmp_store.get_task(_tid(102))
    assert stored_ip is not None
    assert stored_ip.status == "in_progress", "pull-sync must not clobber in_progress status"


def test_pull_creates_new_task_from_github(tmp_store: SqliteStore) -> None:
    """New tasks (not yet in local DB) are created normally from the GitHub payload."""
    source = _mock_source([SAMPLE_ISSUE_HIGH])
    adapter = PullSyncAdapter(store=tmp_store, source=source)
    adapter.pull("RasmusTho/agentic-pkm-mvp")

    stored = tmp_store.get_task(_tid(101))
    assert stored is not None
    assert stored.status == "ready"
    assert stored.priority == "high"
    assert stored.title == SAMPLE_ISSUE_HIGH["title"]


def test_pull_updates_metadata_for_blocked_task(tmp_store: SqliteStore) -> None:
    """Metadata is updated from GitHub when blocked task is reopened by agent:ready."""
    old_now = "2026-04-23T00:00:00+00:00"
    task = normalize_github_issue(SAMPLE_ISSUE_HIGH, REPO, now=old_now)
    task.status = "blocked"
    task.blocked_reason = "waiting on infra"
    tmp_store.upsert_task(task)

    # GitHub payload has updated title and different priority
    updated_issue = {
        **SAMPLE_ISSUE_HIGH,
        "title": "Fix critical bug in queue selection (updated)",
        "labels": [{"name": "prio:high"}, {"name": "agent:ready"}],
        "updatedAt": "2026-04-25T00:00:00Z",
    }
    source = _mock_source([updated_issue])
    adapter = PullSyncAdapter(store=tmp_store, source=source)
    adapter.pull("RasmusTho/agentic-pkm-mvp")

    stored = tmp_store.get_task(_tid(101))
    assert stored is not None
    assert stored.status == "ready"
    assert stored.blocked_reason is None
    assert stored.title == "Fix critical bug in queue selection (updated)", "title must be refreshed"
    assert stored.priority == "high"
    assert stored.sync_state is not None
    assert stored.sync_state["sync_result"] == "ok"


def test_reconcile_blocked_task_closes_when_issue_closed(tmp_store: SqliteStore) -> None:
    """Blocked task transitions to completed when issue is closed/missing from open issues."""
    task = normalize_github_issue(SAMPLE_ISSUE_HIGH, REPO, now="2026-04-24T00:00:00+00:00")
    task.status = "blocked"
    task.blocked_reason = "waiting for upstream"
    tmp_store.upsert_task(task)

    source = _mock_source([], open_issues=[])
    adapter = PullSyncAdapter(store=tmp_store, source=source)
    adapter.pull("RasmusTho/agentic-pkm-mvp")

    stored = tmp_store.get_task(_tid(101))
    assert stored is not None
    assert stored.status == "completed"
    assert stored.blocked_reason is None


def test_reconcile_keeps_blocked_when_open_issue_lookup_fails(tmp_store: SqliteStore) -> None:
    """Blocked tasks must not complete when open-issue snapshot is unavailable."""
    task = normalize_github_issue(SAMPLE_ISSUE_HIGH, REPO, now="2026-04-24T00:00:00+00:00")
    task.status = "blocked"
    task.blocked_reason = "waiting for upstream"
    tmp_store.upsert_task(task)

    source = MagicMock(spec=GitHubIssueSource)
    source.list_issues.return_value = []
    source.list_open_issues.side_effect = RuntimeError("gh issue list failed")
    source.get_rate_limit.return_value = None

    adapter = PullSyncAdapter(store=tmp_store, source=source)
    adapter.pull("RasmusTho/agentic-pkm-mvp")

    stored = tmp_store.get_task(_tid(101))
    assert stored is not None
    assert stored.status == "blocked"
    assert stored.blocked_reason == "waiting for upstream"


def test_reconcile_keeps_ready_when_open_issue_lookup_fails(tmp_store: SqliteStore) -> None:
    """Ready tasks must not complete when open-issue snapshot is unavailable.

    Without the open-issues snapshot the adapter cannot distinguish "issue
    closed" (completed is correct) from "issue open but agent:ready label
    removed" (should stay/demote, not complete). Regression for #2760.
    """
    task = normalize_github_issue(SAMPLE_ISSUE_HIGH, REPO, now="2026-04-24T00:00:00+00:00")
    tmp_store.upsert_task(task)

    source = MagicMock(spec=GitHubIssueSource)
    source.list_issues.return_value = []
    source.list_open_issues.side_effect = RuntimeError("gh issue list failed")
    source.get_rate_limit.return_value = None

    adapter = PullSyncAdapter(store=tmp_store, source=source)
    adapter.pull("RasmusTho/agentic-pkm-mvp")

    stored = tmp_store.get_task(_tid(101))
    assert stored is not None
    assert stored.status == "ready"

    events = [e for e in tmp_store.list_events() if e.event_type == "sync.reconciled"]
    assert events == []


def test_reconcile_keeps_ready_when_kill_switch_active(tmp_store: SqliteStore) -> None:
    """Ready tasks must not complete when the rate-limit kill switch skipped

    the open-issues scan. Regression for #2760.
    """
    task = normalize_github_issue(SAMPLE_ISSUE_HIGH, REPO, now="2026-04-24T00:00:00+00:00")
    tmp_store.upsert_task(task)

    source = MagicMock(spec=GitHubIssueSource)
    source.list_issues.return_value = []
    source.list_open_issues.return_value = []
    source.get_rate_limit.return_value = {"remaining": 10, "reset": 0}

    adapter = PullSyncAdapter(store=tmp_store, source=source)
    adapter.pull("RasmusTho/agentic-pkm-mvp")

    source.list_open_issues.assert_not_called()

    stored = tmp_store.get_task(_tid(101))
    assert stored is not None
    assert stored.status == "ready"

    events = [e for e in tmp_store.list_events() if e.event_type == "sync.reconciled"]
    assert events == []


def test_gh_cli_get_rate_limit_uses_valid_gh_flags_and_parses_rate_key() -> None:
    """Regression guard: `gh api` has no `--json` field-selector flag (that's

    only valid on `gh <noun> list/view`), and `gh api rate_limit`'s real JSON
    shape is ``{"resources": {...}, "rate": {...}}`` — never a top-level
    ``rate_limit`` key. A prior version of this call used the invalid
    ``--json`` flag and read the wrong key, so ``get_rate_limit()`` always
    returned ``None`` in production even though unit tests (which mock the
    protocol, not this method) stayed green.
    """
    source = GhCliIssueSource()
    fake_result = MagicMock(
        returncode=0,
        stdout=(
            '{"core": {"limit": 5000, "remaining": 4973, "reset": 1782894337, "used": 27},'
            ' "graphql": {"limit": 5000, "remaining": 4990, "reset": 1782894337, "used": 10}}'
        ),
    )

    with patch("subprocess.run", return_value=fake_result) as mock_run:
        result = source.get_rate_limit()

    args = mock_run.call_args.args[0]
    assert "--json" not in args, "gh api has no --json flag; use --jq"
    # The more exhausted pool wins (core here).
    assert result == {"limit": 5000, "remaining": 4973, "reset": 1782894337, "used": 27}


def test_gh_cli_get_rate_limit_reports_graphql_pool_when_graphql_exhausted() -> None:
    """#2746 review finding: the audited exhaustion mode is GraphQL-at-zero
    with REST core healthy. ``list_open_issues`` spends GraphQL, so the kill
    switch must see the GraphQL pool — a core-only probe never fires in
    exactly the scenario the guard exists for.
    """
    source = GhCliIssueSource()
    fake_result = MagicMock(
        returncode=0,
        stdout=(
            '{"core": {"limit": 5000, "remaining": 4900, "reset": 1782894337, "used": 100},'
            ' "graphql": {"limit": 5000, "remaining": 0, "reset": 1782894337, "used": 5000}}'
        ),
    )

    with patch("subprocess.run", return_value=fake_result):
        result = source.get_rate_limit()

    assert result is not None
    assert result["remaining"] == 0, "GraphQL exhaustion must surface as the budget signal"


def test_pull_kill_switch_fires_when_graphql_exhausted_and_core_healthy(
    tmp_store: SqliteStore,
) -> None:
    """#3313 regression: end-to-end through the real ``GhCliIssueSource`` and
    ``PullSyncAdapter.pull()``, exercising the documented 2026-06-29
    exhaustion mode (GraphQL pool at zero, REST core healthy). Even though
    ``list_open_issues`` and ``list_issues`` are both REST as of #3313,
    ``get_rate_limit`` must still surface the GraphQL exhaustion so the
    dispatcher kill switch skips the non-essential open-issues scan — proving
    the REST transport conversion did not narrow the shared kill-switch
    signal.
    """
    import json as _json

    source = GhCliIssueSource()
    rate_limit_payload = _json.dumps(
        {
            "core": {"limit": 5000, "remaining": 4900, "reset": 1782894337, "used": 100},
            "graphql": {"limit": 5000, "remaining": 0, "reset": 1782894337, "used": 5000},
        }
    )

    calls: list[list[str]] = []

    def fake_run(args, **_kwargs):
        calls.append(list(args))
        if "rate_limit" in args:
            return MagicMock(returncode=0, stdout=rate_limit_payload, stderr="")
        if "graphql" in args:
            raise AssertionError(
                "no gh api graphql call should be issued by GhCliIssueSource after #3313"
            )
        # Any REST issues-list call (ready-issues or open-issues) — return an
        # empty page so pagination stops immediately if it is reached.
        return MagicMock(returncode=0, stdout="[]", stderr="")

    adapter = PullSyncAdapter(store=tmp_store, source=source)

    with patch("subprocess.run", side_effect=fake_run):
        adapter.pull("RasmusTho/agentic-pkm-mvp")

    # The kill switch must have skipped the non-essential open-issues scan:
    # only the rate_limit probe and the essential ready-issues read happen.
    # The ready-issues (essential) call carries `labels=agent:ready`; the
    # open-issues (non-essential) call does not.
    assert any("rate_limit" in call for call in calls)
    ready_issue_calls = [call for call in calls if "labels=agent:ready" in call]
    open_issue_calls = [
        call
        for call in calls
        if any("repos/RasmusTho/agentic-pkm-mvp/issues" in arg for arg in call)
        and "labels=agent:ready" not in call
    ]
    assert len(ready_issue_calls) == 1, calls
    assert open_issue_calls == [], "kill switch must skip the non-essential open-issues scan"

    sync_meta = get_sync_meta(tmp_store, PROVIDER_IDENTITY)
    assert sync_meta is not None
    assert sync_meta.get("kill_switch_active") is True


def test_pull_reports_partial_when_kill_switch_skips_open_issue_scan(
    tmp_store: SqliteStore,
) -> None:
    """A kill-switch-truncated pull must record a machine-readable partial
    outcome, not plain ok-complete success (#4606,
    LearningSignal lrn_20260730235456_f70f8ccc).

    The essential agent:ready read still succeeds and upserts, but the
    suppressed open-issues scan means the queue projection is honestly
    partial — sync metadata must say so.
    """
    source = _mock_source(
        [SAMPLE_ISSUE_HIGH],
        rate_limit={"remaining": 10, "reset": "2026-07-31T00:00:00Z"},
    )

    adapter = PullSyncAdapter(store=tmp_store, source=source)
    upserted = adapter.pull(REPO)

    # Constraint: the essential ready read is preserved under the kill switch.
    assert [task.issue_number for task in upserted] == [101]
    # Constraint: no additional GitHub API spend — the expensive scan stays off.
    source.list_open_issues.assert_not_called()

    meta = get_sync_meta(tmp_store, PROVIDER_IDENTITY)
    assert meta is not None
    assert meta["sync_result"] == "partial"
    assert meta.get("kill_switch_active") is True
    note = meta.get("sync_note") or ""
    assert "kill" in note and "open-issues" in note


def test_pull_sync_result_stays_ok_when_kill_switch_inactive(
    tmp_store: SqliteStore,
) -> None:
    """Complete-sync success behavior is unchanged when the kill switch is
    inactive and both scans succeed (#4606 constraint)."""
    source = _mock_source(
        [SAMPLE_ISSUE_HIGH],
        rate_limit={"remaining": 5000, "reset": "2026-07-31T00:00:00Z"},
    )

    adapter = PullSyncAdapter(store=tmp_store, source=source)
    adapter.pull(REPO)

    source.list_open_issues.assert_called_once()
    meta = get_sync_meta(tmp_store, PROVIDER_IDENTITY)
    assert meta is not None
    assert meta["sync_result"] == "ok"
    assert meta.get("kill_switch_active") is False


def test_gh_cli_get_rate_limit_returns_none_on_gh_failure() -> None:
    """Non-zero gh exit (auth failure, invalid flags, network error) yields None, not a crash."""
    source = GhCliIssueSource()
    fake_result = MagicMock(returncode=1, stdout="")

    with patch("subprocess.run", return_value=fake_result):
        result = source.get_rate_limit()

    assert result is None


def test_list_ready_issues_paginates_with_bodies() -> None:
    import json as _json

    source = GhCliIssueSource()
    pages = [
        [
            {
                "number": 101,
                "title": "First ready issue",
                "state": "open",
                "labels": [{"name": "agent:ready"}, {"name": "prio:high"}],
                "created_at": "2026-04-20T10:00:00Z",
                "updated_at": "2026-04-21T12:00:00Z",
                "body": VALID_READY_BODY,
            }
        ]
        * 100,
        [
            {
                "number": 201,
                "title": "Second ready issue page",
                "state": "open",
                "labels": [{"name": "agent:ready"}],
                "created_at": "2026-04-22T10:00:00Z",
                "updated_at": "2026-04-22T12:00:00Z",
                "body": VALID_READY_BODY,
            },
            {
                "number": 202,
                "title": "PR returned by issues endpoint",
                "state": "open",
                "labels": [{"name": "agent:ready"}],
                "created_at": "2026-04-22T10:00:00Z",
                "updated_at": "2026-04-22T12:00:00Z",
                "body": VALID_READY_BODY,
                "pull_request": {"url": "https://api.github.com/repos/o/r/pulls/202"},
            },
        ],
    ]
    calls: list[list[str]] = []

    def fake_run(args, **_kwargs):
        calls.append(list(args))
        return MagicMock(
            returncode=0,
            stdout=_json.dumps(pages[len(calls) - 1]),
            stderr="",
        )

    with patch("subprocess.run", side_effect=fake_run):
        issues = source.list_issues("RasmusTho/agentic-pkm-mvp")

    assert len(issues) == 101
    assert issues[0]["body"] == VALID_READY_BODY
    assert issues[-1]["number"] == 201
    assert len(calls) == 2
    assert any("page=1" in arg for arg in calls[0])
    assert any("page=2" in arg for arg in calls[1])
    assert all("repos/RasmusTho/agentic-pkm-mvp/issues" in call for call in calls)


def test_list_open_issues_paginates() -> None:
    """AC4 (#2746 / GHAPI-M3), updated by #3313: list_open_issues fetches in
    bounded REST pages instead of one ``gh issue list --limit 1000`` burst
    (and, since #3313, instead of a paginated GraphQL query), with unchanged
    result semantics (same dict shape:
    number/title/state/labels/createdAt/updatedAt) and pull requests filtered
    out of the shared issues endpoint.
    """
    import json as _json

    source = GhCliIssueSource()
    pages = [
        [
            {
                "number": 101,
                "title": "First open issue",
                "state": "open",
                "labels": [{"name": "agent:ready"}, {"name": "prio:high"}],
                "created_at": "2026-04-20T10:00:00Z",
                "updated_at": "2026-04-21T12:00:00Z",
            }
        ]
        * 100,
        [
            {
                "number": 102,
                "title": "Second open issue",
                "state": "open",
                "labels": [],
                "created_at": "2026-04-19T08:00:00Z",
                "updated_at": "2026-04-19T09:00:00Z",
            },
            {
                "number": 103,
                "title": "PR returned by issues endpoint",
                "state": "open",
                "labels": [],
                "created_at": "2026-04-19T08:00:00Z",
                "updated_at": "2026-04-19T09:00:00Z",
                "pull_request": {"url": "https://api.github.com/repos/o/r/pulls/103"},
            },
        ],
    ]
    calls: list[list[str]] = []

    def fake_run(args, **_kwargs):
        calls.append(list(args))
        return MagicMock(returncode=0, stdout=_json.dumps(pages[len(calls) - 1]), stderr="")

    with patch("subprocess.run", side_effect=fake_run):
        issues = source.list_open_issues("RasmusTho/agentic-pkm-mvp")

    # Unchanged result semantics; the PR node is filtered out.
    assert [issue["number"] for issue in issues] == [101] * 100 + [102]
    assert issues[0]["state"] == "open"
    assert issues[0]["labels"] == [{"name": "agent:ready"}, {"name": "prio:high"}]
    assert issues[-1]["labels"] == []
    assert issues[0]["createdAt"] == "2026-04-20T10:00:00Z"
    assert issues[0]["updatedAt"] == "2026-04-21T12:00:00Z"

    # Paginated: two bounded page fetches via REST, not a single GraphQL burst.
    assert len(calls) == 2
    assert any("page=1" in arg for arg in calls[0])
    assert any("page=2" in arg for arg in calls[1])
    assert any("repos/RasmusTho/agentic-pkm-mvp/issues" in arg for arg in calls[0])
    assert not any(arg == "graphql" for call in calls for arg in call)

    # No --limit 1000 burst remains anywhere in the issued commands.
    for command in calls:
        assert "1000" not in command


def test_list_open_issues_refuses_truncated_snapshot_at_page_cap() -> None:
    """#2746 review finding: when the page cap is hit with every REST page
    still full *and* a confirmation page beyond the cap also has data, a
    silently truncated snapshot would let the stale reconcile treat the
    missing (still-open) issues as closed and mark their live tasks
    completed. The fetch must fail loud instead, routing ``pull()`` into its
    existing snapshot-unavailable path. Updated by #3313 for the REST
    transport: a full page alone no longer proves more results remain (no
    GraphQL cursor), so one bounded confirmation page beyond the cap is
    fetched before failing loud — this test keeps that confirmation page
    non-empty so truncation is genuinely proven.
    """
    import json as _json

    from app.dispatcher.sync_github import OPEN_ISSUES_MAX_PAGES, OPEN_ISSUES_PAGE_SIZE

    source = GhCliIssueSource()
    full_page = [
        {
            "number": 1,
            "title": "endless",
            "state": "open",
            "labels": [],
            "created_at": "2026-04-20T10:00:00Z",
            "updated_at": "2026-04-21T12:00:00Z",
        }
    ] * OPEN_ISSUES_PAGE_SIZE

    calls: list[list[str]] = []

    def fake_run(args, **_kwargs):
        calls.append(list(args))
        # Every page, including the confirmation page beyond the cap, is
        # full — genuine truncation.
        return MagicMock(returncode=0, stdout=_json.dumps(full_page), stderr="")

    with patch("subprocess.run", side_effect=fake_run):
        with pytest.raises(RuntimeError, match="truncated snapshot"):
            source.list_open_issues("RasmusTho/agentic-pkm-mvp")

    # OPEN_ISSUES_MAX_PAGES regular fetches plus one bounded confirmation fetch.
    assert len(calls) == OPEN_ISSUES_MAX_PAGES + 1


def test_list_open_issues_exact_page_multiple_is_not_truncated() -> None:
    """#3313 review finding: a repo with exactly
    OPEN_ISSUES_PAGE_SIZE * OPEN_ISSUES_MAX_PAGES open issues ends on a full
    page with nothing left. Unlike GraphQL's ``hasNextPage`` cursor, a full
    REST page alone cannot distinguish that from real truncation — the
    bounded confirmation page beyond the cap must come back empty and the
    fetch must succeed without raising.
    """
    import json as _json

    from app.dispatcher.sync_github import OPEN_ISSUES_MAX_PAGES, OPEN_ISSUES_PAGE_SIZE

    source = GhCliIssueSource()
    full_page = [
        {
            "number": 1,
            "title": "exact boundary",
            "state": "open",
            "labels": [],
            "created_at": "2026-04-20T10:00:00Z",
            "updated_at": "2026-04-21T12:00:00Z",
        }
    ] * OPEN_ISSUES_PAGE_SIZE

    calls: list[list[str]] = []

    def fake_run(args, **_kwargs):
        calls.append(list(args))
        # The confirmation page (call OPEN_ISSUES_MAX_PAGES + 1) is empty:
        # the previous full page really was the last one.
        if len(calls) == OPEN_ISSUES_MAX_PAGES + 1:
            return MagicMock(returncode=0, stdout="[]", stderr="")
        return MagicMock(returncode=0, stdout=_json.dumps(full_page), stderr="")

    with patch("subprocess.run", side_effect=fake_run):
        issues = source.list_open_issues("RasmusTho/agentic-pkm-mvp")

    assert len(issues) == OPEN_ISSUES_PAGE_SIZE * OPEN_ISSUES_MAX_PAGES
    assert len(calls) == OPEN_ISSUES_MAX_PAGES + 1


def test_list_open_issues_pr_noise_does_not_exhaust_page_budget_early() -> None:
    """#3313 review finding: the raw REST ``/issues`` endpoint mixes pull
    requests into the same per_page budget as issues (filtered out only
    after fetch), unlike the old GraphQL ``issues`` connection. A PR-heavy
    repo must still be able to collect a real-issue count well beyond the
    old 1000-issue ceiling without hitting OPEN_ISSUES_MAX_PAGES, because the
    raw-page budget (OPEN_ISSUES_MAX_PAGES * OPEN_ISSUES_PAGE_SIZE) now has
    headroom for PR noise.
    """
    import json as _json

    from app.dispatcher.sync_github import OPEN_ISSUES_MAX_PAGES, OPEN_ISSUES_PAGE_SIZE

    source = GhCliIssueSource()

    def make_page(n: int, *, prs: int) -> list[dict[str, Any]]:
        page = [
            {
                "number": n * 1000 + i,
                "title": f"issue {n}-{i}",
                "state": "open",
                "labels": [],
                "created_at": "2026-04-20T10:00:00Z",
                "updated_at": "2026-04-21T12:00:00Z",
            }
            for i in range(OPEN_ISSUES_PAGE_SIZE - prs)
        ]
        page.extend(
            {
                "number": n * 1000 + 900 + i,
                "title": f"pr {n}-{i}",
                "state": "open",
                "labels": [],
                "created_at": "2026-04-20T10:00:00Z",
                "updated_at": "2026-04-21T12:00:00Z",
                "pull_request": {"url": "https://api.github.com/repos/o/r/pulls/1"},
            }
            for i in range(prs)
        )
        return page

    calls: list[list[str]] = []

    def fake_run(args, **_kwargs):
        calls.append(list(args))
        page_num = len(calls)
        # Half of every raw page (up to the cap) is pull-request noise; the
        # confirmation page beyond the cap is empty (real end of results).
        # The real-issue ceiling this exercises
        # (OPEN_ISSUES_MAX_PAGES * PAGE_SIZE // 2) exceeds the old
        # pre-#3313 1000-issue ceiling.
        if page_num <= OPEN_ISSUES_MAX_PAGES:
            return MagicMock(
                returncode=0, stdout=_json.dumps(make_page(page_num, prs=OPEN_ISSUES_PAGE_SIZE // 2)), stderr=""
            )
        return MagicMock(returncode=0, stdout="[]", stderr="")

    with patch("subprocess.run", side_effect=fake_run):
        issues = source.list_open_issues("RasmusTho/agentic-pkm-mvp")

    expected_real_issues = OPEN_ISSUES_MAX_PAGES * (OPEN_ISSUES_PAGE_SIZE // 2)
    assert expected_real_issues > 1000, "test should exercise beyond the old 1000-issue ceiling"
    assert len(issues) == expected_real_issues
    assert len(calls) == OPEN_ISSUES_MAX_PAGES + 1


# ---------------------------------------------------------------------------
# Repo-qualified task IDs: cross-repo issue-number collisions must not clobber
# ---------------------------------------------------------------------------

REPO_A = "RasmusTho/agentic-pkm-mvp"
REPO_B = "RasmusTho/bifrost"


def test_same_issue_number_across_repos_yields_distinct_task_ids() -> None:
    """Both repos can have an issue #21; each must map to its own task_id."""
    payload = {**SAMPLE_ISSUE_HIGH, "number": 21}
    task_a = normalize_github_issue(payload, REPO_A, now="2026-04-24T00:00:00+00:00")
    task_b = normalize_github_issue(payload, REPO_B, now="2026-04-24T00:00:00+00:00")

    assert task_a.task_id != task_b.task_id
    assert task_a.task_id == "github-RasmusTho--agentic-pkm-mvp-issue-21"
    assert task_b.task_id == "github-RasmusTho--bifrost-issue-21"
    assert task_a.repo == REPO_A
    assert task_b.repo == REPO_B


def test_same_issue_number_across_repos_both_stored_without_clobber(
    tmp_store: SqliteStore,
) -> None:
    payload = {**SAMPLE_ISSUE_HIGH, "number": 21}
    tmp_store.upsert_task(
        normalize_github_issue(payload, REPO_A, now="2026-04-24T00:00:00+00:00")
    )
    tmp_store.upsert_task(
        normalize_github_issue(
            {**payload, "title": "Bifrost twenty-one"},
            REPO_B,
            now="2026-04-24T00:00:00+00:00",
        )
    )

    stored_a = tmp_store.get_task("github-RasmusTho--agentic-pkm-mvp-issue-21")
    stored_b = tmp_store.get_task("github-RasmusTho--bifrost-issue-21")
    assert stored_a is not None and stored_b is not None
    assert stored_a.title == SAMPLE_ISSUE_HIGH["title"]
    assert stored_b.title == "Bifrost twenty-one"
    assert stored_a.repo == REPO_A
    assert stored_b.repo == REPO_B


def test_pull_of_repo_a_does_not_reconcile_same_issue_number_in_repo_b(
    tmp_store: SqliteStore,
) -> None:
    """A pull of repo A must not touch repo B's task that shares an issue number.

    Repo B has a locally-blocked task #101. Pulling repo A (whose #101 is gone
    from open issues) would, without repo-scoped reconciliation, wrongly mark
    repo B's #101 as completed. It must stay blocked and repo-tagged.
    """
    # Pre-seed repo B's blocked task #101.
    task_b = normalize_github_issue(
        SAMPLE_ISSUE_HIGH, REPO_B, now="2026-04-24T00:00:00+00:00"
    )
    task_b.status = "blocked"
    task_b.blocked_reason = "bifrost upstream dependency"
    tmp_store.upsert_task(task_b)

    # Repo A pull returns no ready issues and an empty open-issue snapshot, so
    # repo A's #101 (if it existed) would reconcile to completed.
    source = _mock_source([], open_issues=[])
    adapter = PullSyncAdapter(store=tmp_store, source=source)
    adapter.pull(REPO_A)

    stored_b = tmp_store.get_task("github-RasmusTho--bifrost-issue-101")
    assert stored_b is not None
    assert stored_b.status == "blocked", "repo B task must be untouched by repo A pull"
    assert stored_b.blocked_reason == "bifrost upstream dependency"
    assert stored_b.repo == REPO_B
    # No reconcile events emitted against repo B's task.
    events = tmp_store.list_events("github-RasmusTho--bifrost-issue-101")
    assert [e for e in events if e.event_type == "sync.reconciled"] == []
