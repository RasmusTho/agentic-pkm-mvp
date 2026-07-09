"""Dispatcher state discovery from linked issue worktrees."""

from __future__ import annotations

import io
import json
import subprocess
from contextlib import redirect_stdout
from pathlib import Path

import pytest

from app.dispatcher.cli import main
from app.dispatcher.config import DEFAULT_DB_NAME, DEFAULT_EVENTS_NAME


def _run(argv: list[str]) -> tuple[int, dict]:
    buf = io.StringIO()
    with redirect_stdout(buf):
        code = main(argv)
    output = buf.getvalue().strip()
    return code, json.loads(output) if output else {}


def _mock_git_worktrees(
    monkeypatch: pytest.MonkeyPatch,
    *,
    primary: Path,
    isolated: Path,
) -> None:
    stdout = (
        f"worktree {primary}\n"
        "HEAD 1111111111111111111111111111111111111111\n"
        "branch refs/heads/main\n\n"
        f"worktree {isolated}\n"
        "HEAD 2222222222222222222222222222222222222222\n"
        "branch refs/heads/codex/issue-3272-dispatcher-worktree-portable\n"
    )

    def fake_run(*args, **kwargs):
        return subprocess.CompletedProcess(args=args, returncode=0, stdout=stdout, stderr="")

    monkeypatch.setattr("app.dispatcher.config.subprocess.run", fake_run)


@pytest.fixture()
def no_dispatcher_env(monkeypatch: pytest.MonkeyPatch) -> None:
    for key in (
        "DISPATCHER_STATE_DIR",
        "DISPATCHER_DB_PATH",
        "DISPATCHER_EVENTS_PATH",
    ):
        monkeypatch.delenv(key, raising=False)


def test_dispatcher_status_from_isolated_worktree_uses_canonical_state(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    no_dispatcher_env: None,
) -> None:
    primary = tmp_path / "agentic-pkm-mvp"
    isolated = tmp_path / "agentic-pkm-mvp-3272"
    primary.mkdir()
    isolated.mkdir()
    monkeypatch.chdir(isolated)
    _mock_git_worktrees(monkeypatch, primary=primary, isolated=isolated)

    start_code, start_data = _run(["start", "--agent", "test-agent", "--json"])
    assert start_code == 0
    assert start_data["db_exists"] is True

    status_code, status_data = _run(["status", "--json"])

    canonical_state = primary / "runtime" / "dispatcher"
    assert status_code == 0
    assert status_data["state_dir"] == str(canonical_state)
    assert status_data["db_path"] == str(canonical_state / DEFAULT_DB_NAME)
    assert status_data["events_path"] == str(canonical_state / DEFAULT_EVENTS_NAME)
    assert status_data["db_exists"] is True
    assert status_data["coordination_mode"] == "dispatcher-backed"
    assert status_data["fallback_reason"] is None


def test_missing_dispatcher_state_reports_fallback_reason(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    no_dispatcher_env: None,
) -> None:
    primary = tmp_path / "agentic-pkm-mvp"
    isolated = tmp_path / "agentic-pkm-mvp-3272"
    primary.mkdir()
    isolated.mkdir()
    monkeypatch.chdir(isolated)
    _mock_git_worktrees(monkeypatch, primary=primary, isolated=isolated)

    status_code, status_data = _run(["status", "--json"])

    assert status_code == 0
    assert status_data["db_exists"] is False
    assert status_data["coordination_mode"] == "github-label-only-fallback"
    assert status_data["fallback_reason"] == "dispatcher_db_missing"
    assert status_data["setup_command"] == (
        "python -m app.dispatcher start --agent <agent_id> --json"
    )
    assert status_data["fallback_command"] == (
        "scripts/issue_pickup_claim.sh --issue <ISSUE_NUMBER> --agent <agent_id> "
        "--session <session_id> --coordination-mode github-label-only-fallback "
        "--fallback-reason dispatcher_db_missing"
    )
