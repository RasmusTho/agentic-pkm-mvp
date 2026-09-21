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
from app.dispatcher.pickup_refresh import repository_coverage
from app.dispatcher.repositories import (
    DEFAULT_REPOS,
    EXTRA_REPOS_ENV,
    LEGACY_EXTRA_REPOS_ENV,
)
from app.dispatcher.store import SqliteStore
from app.dispatcher.sync_github import GitHubIssueSource, github_issue_task_id

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
