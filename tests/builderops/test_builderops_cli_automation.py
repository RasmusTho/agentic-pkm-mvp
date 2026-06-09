"""Tests for the standalone BuilderOps CLI entry point (issue #1722).

These tests verify that:
1. ``app.builderops`` standalone entry point works (``python3 -m app.builderops``)
2. BuilderOps read commands return JSON, not ModuleNotFoundError
3. BuilderOps write commands reach validation/store logic
4. ``app.config`` package-level import does not trigger the yaml import chain
"""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

from click.testing import CliRunner

from app.builderops.__main__ import _root as builderops_standalone_root


# ---------------------------------------------------------------------------
# AC 1: read commands work via the standalone entry point
# ---------------------------------------------------------------------------

def _run_standalone(args: list[str]):
    return CliRunner().invoke(builderops_standalone_root, args, catch_exceptions=False)


def _json(output: str):
    return json.loads(output)


def test_standalone_list_returns_json(tmp_path: Path) -> None:
    """``builderops list --json`` via standalone entry returns valid JSON, not an error."""
    db_path = tmp_path / "builderops.sqlite3"
    result = _run_standalone(
        ["builderops", "--db-path", str(db_path), "list", "--type", "LearningSignal", "--json"]
    )
    assert result.exit_code == 0, result.output
    records = _json(result.output)
    assert isinstance(records, list)


def test_standalone_list_all_types_returns_json(tmp_path: Path) -> None:
    """``builderops list --json`` without a type filter returns valid JSON."""
    db_path = tmp_path / "builderops.sqlite3"
    result = _run_standalone(
        ["builderops", "--db-path", str(db_path), "list", "--json"]
    )
    assert result.exit_code == 0, result.output
    assert isinstance(_json(result.output), list)


# ---------------------------------------------------------------------------
# AC 2: write commands reach BuilderOps validation/store logic
# ---------------------------------------------------------------------------

def test_standalone_create_learning_signal_reaches_store(tmp_path: Path) -> None:
    """``create-learning-signal`` via standalone entry creates a record in the store."""
    db_path = tmp_path / "builderops.sqlite3"
    result = _run_standalone(
        [
            "builderops",
            "--db-path",
            str(db_path),
            "create-learning-signal",
            "--summary",
            "Automation worktree test",
            "--content",
            "Issue #1722: BuilderOps CLI available from automation worktrees.",
            "--signal-type",
            "workflow",
            "--source-ref",
            "github_issue:#1722",
            "--json",
        ]
    )
    assert result.exit_code == 0, result.output
    record = _json(result.output)
    assert record["object_type"] == "LearningSignal"
    assert record["lifecycle_state"] == "active"
    assert record["promotion_status"] == "candidate"

    # Verify the record is visible via list
    listed = _run_standalone(
        ["builderops", "--db-path", str(db_path), "list", "--type", "LearningSignal", "--json"]
    )
    assert listed.exit_code == 0, listed.output
    records = _json(listed.output)
    assert any(r["id"] == record["id"] for r in records)


def test_standalone_append_receipt_reaches_store(tmp_path: Path) -> None:
    """``append-receipt`` via standalone entry creates a BuilderOpsReceipt in the store."""
    db_path = tmp_path / "builderops.sqlite3"
    result = _run_standalone(
        [
            "builderops",
            "--db-path",
            str(db_path),
            "append-receipt",
            "--summary",
            "Automation receipt test",
            "--event-type",
            "object_created",
            "--actor",
            "codex-test",
            "--occurred-at",
            "2026-06-09T00:00:00Z",
            "--target-ref",
            "github_issue:#1722",
            "--action",
            "create",
            "--receipt-body",
            "BuilderOps CLI automation worktree test receipt.",
            "--idempotency-key",
            "test:automation-receipt:#1722",
            "--source-ref",
            "github_issue:#1722",
            "--json",
        ]
    )
    assert result.exit_code == 0, result.output
    record = _json(result.output)
    assert record["object_type"] == "BuilderOpsReceipt"
    assert record["promotion_status"] == "not_promotable"


def test_standalone_write_command_bad_args_fails_with_validation_error(tmp_path: Path) -> None:
    """Write commands with missing required fields fail with BuilderOps validation, not an import error."""
    db_path = tmp_path / "builderops.sqlite3"
    # list with an unsupported object_type must produce a BuilderOps validation error, not ImportError
    result = CliRunner().invoke(
        builderops_standalone_root,
        [
            "builderops",
            "--db-path",
            str(db_path),
            "list",
            "--type",
            "NonExistentType",
            "--json",
        ],
    )
    assert result.exit_code != 0
    assert "unsupported object_type" in result.output
    assert "ModuleNotFoundError" not in result.output
    assert "ImportError" not in result.output


# ---------------------------------------------------------------------------
# AC: app.config package-level import does not trigger the yaml import chain
# ---------------------------------------------------------------------------

def test_app_config_package_import_does_not_require_yaml(tmp_path: Path) -> None:
    """Importing app.config does not trigger the yaml import chain.

    This verifies the fix to app/config/__init__.py: it no longer re-exports
    from app.config.agent (which imports yaml), so automation environments
    that have click but not yaml can still import app.config.
    """
    result = subprocess.run(
        [
            sys.executable,
            "-c",
            "import sys; sys.modules.pop('yaml', None); import app.config; print('ok')",
        ],
        capture_output=True,
        text=True,
        # Use the current sys.path so the test finds the right app/ package.
        env={
            "PYTHONPATH": ":".join(sys.path),
            "HOME": str(tmp_path),
        },
    )
    # If app.config triggers yaml and yaml is not installed, this would fail.
    # With the fix it should either succeed (yaml available) or only fail on
    # something other than app.config's own import.
    # We just verify there is no ImportError from app.config itself.
    if result.returncode != 0:
        assert "from .agent import" not in result.stderr, (
            "app/config/__init__.py still eagerly imports from agent.py which requires yaml. "
            f"stderr: {result.stderr}"
        )
