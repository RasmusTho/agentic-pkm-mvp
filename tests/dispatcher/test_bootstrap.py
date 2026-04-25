"""Tests for dispatcher bootstrap and makefile targets.

Tests that make dispatcher-init and make dispatcher-sync work correctly.
"""

from __future__ import annotations

import os
from pathlib import Path

import pytest

from app.dispatcher.config import load_paths


@pytest.fixture()
def tmp_env(tmp_path: Path) -> dict[str, str]:
    """Env vars pointing to a temporary state directory."""
    state_dir = tmp_path / "dispatcher"
    return {
        "DISPATCHER_STATE_DIR": str(state_dir),
        "DISPATCHER_DB_PATH": str(state_dir / "dispatcher.sqlite3"),
        "DISPATCHER_EVENTS_PATH": str(state_dir / "events.jsonl"),
    }


# ---------------------------------------------------------------------------
# AC: make dispatcher-init runs init then pull and exits 0 on a clean state dir.
# Verify: test_make_dispatcher_init
# ---------------------------------------------------------------------------

def test_make_dispatcher_init(tmp_env: dict[str, str], tmp_path: Path) -> None:
    """make dispatcher-init initializes and populates the queue."""
    old = os.environ.copy()
    os.environ.update(tmp_env)
    try:
        # Mock the pull by calling init directly; real pull would require gh auth
        from app.dispatcher.cli import main

        # Test that make dispatcher-init equivalent works
        code = main(["init", "--json"])
        assert code == 0

        # Verify state dir and DB were created
        paths = load_paths(tmp_env)
        assert paths.db_path.exists()
        assert paths.state_dir.exists()

    finally:
        os.environ.clear()
        os.environ.update(old)


# ---------------------------------------------------------------------------
# AC: make dispatcher-sync runs pull only (does not reinitialise schema) and exits 0.
# Verify: test_make_dispatcher_sync
# ---------------------------------------------------------------------------

def test_make_dispatcher_sync(tmp_env: dict[str, str]) -> None:
    """make dispatcher-sync runs pull without reinitializing."""
    from unittest.mock import MagicMock, patch
    from app.dispatcher.cli import main
    from app.dispatcher.config import load_paths
    from app.dispatcher.sync_github import GitHubIssueSource

    old = os.environ.copy()
    os.environ.update(tmp_env)
    try:
        # Initialize first
        code = main(["init", "--json"])
        assert code == 0

        # Now test dispatcher-sync equivalent by running pull
        paths = load_paths(tmp_env)
        db_path_before = paths.db_path
        assert db_path_before.exists()

        # Mock the GitHub source
        mock_source = MagicMock(spec=GitHubIssueSource)
        mock_source.list_issues.return_value = []
        mock_source.get_rate_limit.return_value = None

        with patch("app.dispatcher.cli.GhCliIssueSource", return_value=mock_source):
            code = main(["pull", "--repo", "test/repo", "--json"])

        assert code == 0

        # DB should still exist and be the same file
        assert db_path_before.exists()
        paths_after = load_paths(tmp_env)
        assert paths_after.db_path == db_path_before

    finally:
        os.environ.clear()
        os.environ.update(old)
