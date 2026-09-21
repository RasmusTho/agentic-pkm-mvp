"""Fresh exact-task refreshes before dispatcher-backed pickup."""

from __future__ import annotations

import io
import json
from contextlib import redirect_stdout
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

import pytest

from app.dispatcher.cli import main
from app.dispatcher.config import load_paths
from app.dispatcher.events import JsonlEventWriter
from app.dispatcher.models import TaskRecord
from app.dispatcher.pickup_refresh import pickup_refresh_reason, repository_coverage
from app.dispatcher.repositories import (
    DEFAULT_REPOS,
    EXTRA_REPOS_ENV,
    LEGACY_EXTRA_REPOS_ENV,
)
from app.dispatcher.store import SqliteStore
from app.dispatcher.sync_github import (
    GitHubIssueSource,
    PullSyncAdapter,
    PROVIDER_IDENTITY,
    github_issue_task_id,
    record_sync_batch_summary,
)

REPO_ROOT = Path(__file__).resolve().parents[2]
VALID_READY_BODY = (
    REPO_ROOT / "tests/fixtures/issue_readiness/valid_ready_candidate.md"
).read_text(encoding="utf-8")


@pytest.fixture()
def pickup_store(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> SqliteStore:
    state_dir = tmp_path / "dispatcher"
    monkeypatch.setenv("DISPATCHER_STATE_DIR", str(state_dir))
    monkeypatch.setenv("DISPATCHER_DB_PATH", str(state_dir / "dispatcher.sqlite3"))
    monkeypatch.setenv("DISPATCHER_EVENTS_PATH", str(state_dir / "events.jsonl"))
    monkeypatch.delenv(EXTRA_REPOS_ENV, raising=False)
    monkeypatch.delenv(LEGACY_EXTRA_REPOS_ENV, raising=False)
    paths = load_paths()
    store = SqliteStore(
        db_path=paths.db_path,
        event_writer=JsonlEventWriter(paths.events_path),
    )
    store.initialize()
    return store


def _run(argv: list[str]) -> tuple[int, dict[str, Any]]:
    output = io.StringIO()
    with redirect_stdout(output):
        exit_code = main(argv)
    text = output.getvalue().strip()
    return exit_code, json.loads(text) if text else {}


def _ready_issue(number: int) -> dict[str, Any]:
    return {
        "number": number,
        "title": f"Fresh ready issue {number}",
        "body": VALID_READY_BODY,
        "state": "open",
        "labels": [{"name": "prio:high"}, {"name": "agent:ready"}],
        "createdAt": "2026-09-20T10:00:00Z",
        "updatedAt": "2026-09-20T10:00:00Z",
    }


def test_repository_coverage_preserves_fractional_freshness_age() -> None:
    now = datetime(2026, 9, 21, 12, 0, 0, 500000, tzinfo=timezone.utc)
    repository = DEFAULT_REPOS[0]
    common = {"sync_result": "ok", "ready_issue_scan": True}

    stale = repository_coverage(
        {
            repository: {
                **common,
                "last_pull_at": (now - timedelta(seconds=900.5)).isoformat(),
            }
        },
        (repository,),
        now=now,
    )
    fresh = repository_coverage(
        {
            repository: {
                **common,
                "last_pull_at": (now - timedelta(seconds=900)).isoformat(),
            }
        },
        (repository,),
        now=now,
    )

    assert stale["age_seconds_by_repository"][repository] == pytest.approx(900.5)
    assert stale["stale_repositories"] == [repository]
    assert stale["state"] == "stale"
    assert fresh["age_seconds_by_repository"][repository] == pytest.approx(900)
    assert fresh["fresh_repositories"] == [repository]


@pytest.mark.parametrize(
    ("pull_at", "now"),
    [
        (
            "2026-09-21",
            datetime(2026, 9, 21, 0, 5, tzinfo=timezone.utc),
        ),
        (
            "2026-09-21T12:00:00",
            datetime(2026, 9, 21, 12, 5, tzinfo=timezone.utc),
        ),
    ],
    ids=["date-only-pull", "timezone-free-pull"],
)
def test_pickup_refresh_rejects_timezone_free_persisted_evidence(
    pull_at: str,
    now: datetime,
) -> None:
    repository = DEFAULT_REPOS[0]
    task = TaskRecord(
        task_id=github_issue_task_id(repository, 5491),
        issue_number=5491,
        title="Timezone-free sync evidence",
        status="ready",
        priority="high",
        source_anchor_refs=["github:issue:5491"],
        created_at=pull_at,
        updated_at=pull_at,
        repo=repository,
        sync_state={"last_pull_at": pull_at},
    )
    sync_meta = {
        "repo_results": {
            repository: {"sync_result": "ok", "last_pull_at": pull_at}
        }
    }

    assert (
        pickup_refresh_reason(task, sync_meta, repository, now=now)
        == "target_repository_sync_stale"
    )


def test_pickup_refresh_does_not_claim_from_timezone_free_cached_evidence(
    pickup_store: SqliteStore,
) -> None:
    from unittest.mock import MagicMock, patch

    target_repo = DEFAULT_REPOS[0]
    task_id = github_issue_task_id(target_repo, 5491)
    pull_at = "2026-09-21T12:00:00"
    pickup_store.upsert_task(
        TaskRecord(
            task_id=task_id,
            issue_number=5491,
            title="Timezone-free sync evidence",
            status="ready",
            priority="high",
            source_anchor_refs=["github:issue:5491"],
            created_at=pull_at,
            updated_at=pull_at,
            repo=target_repo,
            sync_state={"last_pull_at": pull_at},
        )
    )
    record_sync_batch_summary(
        pickup_store,
        PROVIDER_IDENTITY,
        pull_at,
        sync_result="ok",
        sync_note=None,
        extra={
            "repo_results": {
                target_repo: {
                    "last_pull_at": pull_at,
                    "sync_result": "ok",
                    "ready_issue_scan": True,
                }
            }
        },
    )

    source = MagicMock(spec=GitHubIssueSource)
    source.get_rate_limit.return_value = {"remaining": 5000, "reset": None}
    source.list_issues.side_effect = RuntimeError("GitHub read unavailable")
    source.list_open_issues.return_value = []
    with patch("app.dispatcher.cli.GhCliIssueSource", return_value=source):
        code, data = _run(
            ["pickup-refresh", task_id, "--repo", target_repo, "--json"]
        )

    assert code == 1
    assert data["ok"] is False
    assert data["ready"] is False
    assert data["action"] == "refuse"
    assert data["refresh_reason"] == "target_repository_sync_stale"
    assert data["reason"] == "target_repository_sync_failed"
    stored = pickup_store.get_task(task_id)
    assert stored is not None
    assert stored.status == "ready"
    assert stored.lease_id is None


def test_missing_task_triggers_bounded_multi_repo_refresh(
    pickup_store: SqliteStore,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from unittest.mock import MagicMock, patch

    extra_repo = "RasmusTho/extra-builder"
    monkeypatch.setenv(EXTRA_REPOS_ENV, extra_repo)
    target_repo = DEFAULT_REPOS[1]
    issue = _ready_issue(5491)
    source = MagicMock(spec=GitHubIssueSource)
    source.get_rate_limit.return_value = {"remaining": 5000, "reset": None}
    source.list_issues.side_effect = lambda repo, **_kwargs: (
        [issue] if repo == target_repo else []
    )
    source.list_open_issues.side_effect = lambda repo, **_kwargs: (
        [issue] if repo == target_repo else []
    )
    task_id = github_issue_task_id(target_repo, issue["number"])

    with patch("app.dispatcher.cli.GhCliIssueSource", return_value=source):
        code, data = _run(
            ["pickup-refresh", task_id, "--repo", target_repo, "--json"]
        )

    configured_repos = [*DEFAULT_REPOS, extra_repo]
    assert code == 0, data
    assert data["ok"] is True
    assert data["ready"] is True
    assert data["action"] == "claim"
    assert data["reason"] == "refreshed_and_observed_ready"
    assert data["refreshed"] is True
    assert data["observed_ready"] is True
    assert [call.args[0] for call in source.list_issues.call_args_list] == configured_repos
    assert len(source.list_issues.call_args_list) == len(configured_repos)
    assert data["repository_coverage"]["configured_repositories"] == configured_repos
    assert data["repository_coverage"]["ready_scan_complete"] is True

    # The normal exact-task lease command can now acquire the freshly observed row.
    claim_code, claim_data = _run(["claim", task_id, "--agent", "test-agent", "--json"])
    assert claim_code == 0, claim_data
    assert claim_data["ok"] is True
    assert claim_data["task"]["status"] == "claimed"


def test_failed_refresh_preserves_truthful_fallback(
    pickup_store: SqliteStore,
) -> None:
    from unittest.mock import MagicMock, patch

    target_repo = DEFAULT_REPOS[0]
    task_id = github_issue_task_id(target_repo, 5491)
    old_pull_at = (datetime.now(timezone.utc) - timedelta(hours=4)).isoformat()
    stale_task = TaskRecord(
        task_id=task_id,
        issue_number=5491,
        title="Previously cached ready issue",
        status="ready",
        priority="high",
        source_anchor_refs=["github:issue:5491"],
        created_at=old_pull_at,
        updated_at=old_pull_at,
        repo=target_repo,
        sync_state={"last_pull_at": old_pull_at},
    )
    pickup_store.upsert_task(stale_task)

    source = MagicMock(spec=GitHubIssueSource)
    source.get_rate_limit.return_value = {"remaining": 5000, "reset": None}
    source.list_open_issues.return_value = []

    def fail_target(repo: str, **_kwargs: Any) -> list[dict[str, Any]]:
        if repo == target_repo:
            raise RuntimeError("GitHub read unavailable")
        return []

    source.list_issues.side_effect = fail_target
    with patch("app.dispatcher.cli.GhCliIssueSource", return_value=source):
        code, data = _run(["pickup-refresh", task_id, "--repo", target_repo, "--json"])

    assert code == 1
    assert data["ok"] is False
    assert data["ready"] is False
    assert data["action"] == "refuse"
    assert data["reason"] == "target_repository_sync_failed"
    assert "fallback_allowed" not in data
    assert data["observed_ready"] is False
    task_after = pickup_store.get_task(task_id)
    assert task_after is not None
    assert task_after.status == "ready"
    assert task_after.lease_id is None
    assert task_after.sync_state == {"last_pull_at": old_pull_at}
    assert data["repository_sync"]["sync_result"] == "error"
    assert "GitHub read unavailable" in data["repository_sync"]["sync_note"]


def test_release_invalidates_ready_scan_evidence_before_next_pickup(
    pickup_store: SqliteStore,
) -> None:
    from unittest.mock import MagicMock, patch

    target_repo = DEFAULT_REPOS[0]
    issue = _ready_issue(5491)
    in_progress_issue = {
        **issue,
        "labels": [{"name": "prio:high"}, {"name": "agent:in-progress"}],
    }
    ready_on_github = {"value": True}
    source = MagicMock(spec=GitHubIssueSource)
    source.get_rate_limit.return_value = {"remaining": 5000, "reset": None}
    source.list_issues.side_effect = lambda repo, **_kwargs: (
        [issue] if ready_on_github["value"] and repo == target_repo else []
    )
    source.list_open_issues.side_effect = lambda repo, **_kwargs: (
        [issue if ready_on_github["value"] else in_progress_issue]
        if repo == target_repo
        else []
    )
    task_id = github_issue_task_id(target_repo, issue["number"])

    with patch("app.dispatcher.cli.GhCliIssueSource", return_value=source):
        initial_code, initial = _run(
            ["pickup-refresh", task_id, "--repo", target_repo, "--json"]
        )
        assert initial_code == 0, initial
        assert initial["ready"] is True

        claim_code, claim_data = _run(
            ["claim", task_id, "--agent", "test-agent", "--json"]
        )
        assert claim_code == 0, claim_data
        ready_on_github["value"] = False

        release_code, release_data = _run(
            ["release", task_id, "--agent", "test-agent", "--json"]
        )
        assert release_code == 0, release_data

        released = pickup_store.get_task(task_id)
        assert released is not None
        assert released.status == "ready"
        assert released.sync_state is not None
        assert "last_pull_at" not in released.sync_state
        claims_before_refresh = sum(
            event.event_type == "task.claimed"
            for event in pickup_store.list_events(task_id=task_id)
        )

        refresh_code, refresh = _run(
            ["pickup-refresh", task_id, "--repo", target_repo, "--json"]
        )

    assert refresh_code == 1, refresh
    assert refresh["ok"] is False
    assert refresh["ready"] is False
    assert refresh["action"] == "refuse"
    assert refresh["reason"] == "task_not_in_observed_ready_set"
    target_reads = [
        call for call in source.list_issues.call_args_list if call.args[0] == target_repo
    ]
    assert len(target_reads) == 2

    ready_on_github["value"] = True
    with patch("app.dispatcher.cli.GhCliIssueSource", return_value=source):
        ready_code, ready_refresh = _run(
            ["pickup-refresh", task_id, "--repo", target_repo, "--json"]
        )

    assert ready_code == 0, ready_refresh
    assert ready_refresh["ready"] is True
    assert ready_refresh["action"] == "claim"
    refreshed = pickup_store.get_task(task_id)
    assert refreshed is not None and refreshed.sync_state is not None
    assert "ready_scan_invalidated_at" not in refreshed.sync_state
    assert refreshed.sync_state["last_pull_at"]
    target_reads = [
        call for call in source.list_issues.call_args_list if call.args[0] == target_repo
    ]
    assert len(target_reads) == 3
    claims_after_refresh = sum(
        event.event_type == "task.claimed"
        for event in pickup_store.list_events(task_id=task_id)
    )
    assert claims_after_refresh == claims_before_refresh == 1


def test_inflight_pre_release_pull_cannot_restore_ready_scan_evidence(
    pickup_store: SqliteStore,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from unittest.mock import MagicMock, patch

    from app.dispatcher.leases import claim, release

    target_repo = DEFAULT_REPOS[0]
    issue = _ready_issue(5491)
    in_progress_issue = {
        **issue,
        "labels": [{"name": "prio:high"}, {"name": "agent:in-progress"}],
    }
    task_id = github_issue_task_id(target_repo, issue["number"])
    old_pull_at = datetime.now(timezone.utc).isoformat()
    pickup_store.upsert_task(
        TaskRecord(
            task_id=task_id,
            issue_number=issue["number"],
            title=issue["title"],
            status="ready",
            priority="high",
            source_anchor_refs=["github:issue:5491"],
            created_at=old_pull_at,
            updated_at=old_pull_at,
            repo=target_repo,
            sync_state={"last_pull_at": old_pull_at},
        )
    )
    claim(pickup_store, task_id, "test-agent")

    ready_on_github = {"value": True}
    source = MagicMock(spec=GitHubIssueSource)
    source.get_rate_limit.return_value = {"remaining": 5000, "reset": None}
    source.list_issues.side_effect = lambda repo, **_kwargs: (
        [issue] if ready_on_github["value"] and repo == target_repo else []
    )
    source.list_open_issues.side_effect = lambda repo, **_kwargs: (
        [issue if ready_on_github["value"] else in_progress_issue]
        if repo == target_repo
        else []
    )

    original_upsert = pickup_store.upsert_synced_task
    released_during_pull = False

    def release_before_stale_snapshot_write(
        sync_task: TaskRecord, **kwargs: Any
    ) -> Any:
        nonlocal released_during_pull
        if sync_task.task_id == task_id and not released_during_pull:
            released_during_pull = True
            ready_on_github["value"] = False
            release(pickup_store, task_id, "test-agent")
        return original_upsert(sync_task, **kwargs)

    monkeypatch.setattr(
        pickup_store, "upsert_synced_task", release_before_stale_snapshot_write
    )
    PullSyncAdapter(store=pickup_store, source=source).pull(target_repo)

    assert released_during_pull is True
    released = pickup_store.get_task(task_id)
    assert released is not None
    assert released.sync_state is not None
    assert "last_pull_at" not in released.sync_state
    assert "ready_scan_invalidated_at" in released.sync_state

    with patch("app.dispatcher.cli.GhCliIssueSource", return_value=source):
        refresh_code, refresh = _run(
            ["pickup-refresh", task_id, "--repo", target_repo, "--json"]
        )

    assert refresh_code == 1, refresh
    assert refresh["ok"] is False
    assert refresh["ready"] is False
    assert refresh["reason"] == "task_not_in_observed_ready_set"
    target_reads = [
        call for call in source.list_issues.call_args_list if call.args[0] == target_repo
    ]
    assert len(target_reads) == 2


def test_blocked_open_scan_cannot_restore_released_task_readiness(
    pickup_store: SqliteStore,
) -> None:
    from unittest.mock import MagicMock, patch

    from app.dispatcher.leases import claim, release
    from app.dispatcher.queue import unblock

    target_repo = DEFAULT_REPOS[0]
    issue = _ready_issue(5491)
    blocked_issue = {
        **issue,
        "labels": [{"name": "prio:high"}, {"name": "agent:blocked"}],
    }
    task_id = github_issue_task_id(target_repo, issue["number"])
    old_pull_at = (datetime.now(timezone.utc) - timedelta(minutes=5)).isoformat()
    pickup_store.upsert_task(
        TaskRecord(
            task_id=task_id,
            issue_number=issue["number"],
            title=issue["title"],
            status="ready",
            priority="high",
            source_anchor_refs=[f"github:issue:{issue['number']}"],
            created_at=old_pull_at,
            updated_at=old_pull_at,
            repo=target_repo,
            sync_state={"last_pull_at": old_pull_at},
        )
    )
    claim(pickup_store, task_id, "test-agent")
    release(pickup_store, task_id, "test-agent")

    source = MagicMock(spec=GitHubIssueSource)
    source.get_rate_limit.return_value = {"remaining": 5000, "reset": None}
    source.list_issues.side_effect = lambda _repo, **_kwargs: []
    source.list_open_issues.side_effect = lambda repo, **_kwargs: (
        [blocked_issue] if repo == target_repo else []
    )

    PullSyncAdapter(store=pickup_store, source=source).pull(target_repo)
    blocked_scan_task = pickup_store.get_task(task_id)
    assert blocked_scan_task is not None
    assert blocked_scan_task.status == "blocked"
    assert blocked_scan_task.sync_state is not None
    assert "last_pull_at" not in blocked_scan_task.sync_state
    assert "ready_scan_invalidated_at" in blocked_scan_task.sync_state

    unblock(pickup_store, task_id, "operator")
    unblocked_task = pickup_store.get_task(task_id)
    assert unblocked_task is not None
    assert unblocked_task.status == "ready"
    assert unblocked_task.sync_state is not None
    assert "last_pull_at" not in unblocked_task.sync_state
    assert "ready_scan_invalidated_at" in unblocked_task.sync_state

    with patch("app.dispatcher.cli.GhCliIssueSource", return_value=source):
        refresh_code, refresh = _run(
            ["pickup-refresh", task_id, "--repo", target_repo, "--json"]
        )

    assert refresh_code == 1, refresh
    assert refresh["ok"] is False
    assert refresh["ready"] is False
    assert refresh["action"] == "refuse"
    assert refresh["reason"] == "task_not_in_observed_ready_set"
    after_refresh = pickup_store.get_task(task_id)
    assert after_refresh is not None and after_refresh.sync_state is not None
    assert "last_pull_at" not in after_refresh.sync_state
    assert "ready_scan_invalidated_at" in after_refresh.sync_state
