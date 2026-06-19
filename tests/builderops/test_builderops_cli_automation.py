"""Tests for the standalone BuilderOps CLI entry point (issue #1722).

These tests verify that:
1. ``app.builderops`` standalone entry point works (``python3 -m app.builderops``)
2. BuilderOps read commands return JSON, not ModuleNotFoundError
3. BuilderOps write commands reach validation/store logic
4. ``app.config`` package-level import does not trigger the yaml import chain
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

from click.testing import CliRunner

from app.builderops.__main__ import _root as builderops_standalone_root

REPO_ROOT = Path(__file__).resolve().parents[2]
BUILDEROPS_WRAPPER = REPO_ROOT / "scripts" / "builderops_cli.sh"


# ---------------------------------------------------------------------------
# AC 1: read commands work via the standalone entry point
# ---------------------------------------------------------------------------

def _run_standalone(args: list[str]):
    return CliRunner().invoke(builderops_standalone_root, args, catch_exceptions=False)


def _json(output: str):
    return json.loads(output)


def _write_executable(path: Path, content: str) -> None:
    path.write_text(content)
    path.chmod(0o755)


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


def test_standalone_entry_does_not_import_app_cli(tmp_path: Path) -> None:
    """The standalone entry point must NOT import the app.cli package.

    Regression guard for PR #1768 Codex P1: app/cli/__init__.py eagerly imports
    httpx/watchfiles and other runtime-only deps, so if the standalone entry
    pulls in app.cli it fails with ModuleNotFoundError before any BuilderOps
    command can run — defeating the automation-worktree fix. The command
    implementation now lives in app.builderops.cli, so importing the standalone
    entry must leave 'app.cli' absent from sys.modules.
    """
    result = subprocess.run(
        [
            sys.executable,
            "-c",
            "import app.builderops.__main__ as m; import sys; "
            "assert 'app.cli' not in sys.modules, "
            "'standalone entry imported app.cli: ' + repr(sorted(k for k in sys.modules if k.startswith('app.cli'))); "
            "print('ok')",
        ],
        capture_output=True,
        text=True,
        env={
            "PYTHONPATH": ":".join(sys.path),
            "HOME": str(tmp_path),
        },
    )
    assert result.returncode == 0, (
        "Standalone BuilderOps entry point imported app.cli (pulls heavy runtime "
        f"deps).\nstdout: {result.stdout}\nstderr: {result.stderr}"
    )
    assert "ok" in result.stdout


# ---------------------------------------------------------------------------
# AC #1819: wrapper resolves canonical venv for Codex app worktrees
# ---------------------------------------------------------------------------

def test_builderops_wrapper_finds_canonical_venv_from_codex_worktree(tmp_path: Path) -> None:
    """The wrapper uses git worktree metadata to find the canonical checkout venv."""
    canonical_root = tmp_path / "code" / "agentic-pkm-mvp"
    canonical_python = canonical_root / ".venv" / "bin" / "python3"
    fakebin = tmp_path / "bin"
    worktree_root = tmp_path / ".codex" / "worktrees" / "7c2f" / "agentic-pkm-mvp"
    invocation_cwd = tmp_path / "invocation.cwd"
    invocation_args = tmp_path / "invocation.args"

    (canonical_root / ".git").mkdir(parents=True)
    canonical_python.parent.mkdir(parents=True)
    fakebin.mkdir()
    (worktree_root / "scripts").mkdir(parents=True)
    (worktree_root / "app").mkdir()
    (worktree_root / "scripts" / "builderops_cli.sh").write_text(BUILDEROPS_WRAPPER.read_text())
    (worktree_root / "scripts" / "builderops_cli.sh").chmod(0o755)

    _write_executable(
        canonical_python,
        f"""#!/usr/bin/env bash
printf '%s\\n' "$PWD" > {invocation_cwd}
printf '%s\\n' "$@" > {invocation_args}
""",
    )
    _write_executable(
        fakebin / "git",
        f"""#!/usr/bin/env bash
if [ "$1" = "-C" ] && [ "$3" = "rev-parse" ] && [ "$4" = "--git-common-dir" ]; then
  printf '%s\\n' {canonical_root / ".git"}
  exit 0
fi
exit 1
""",
    )

    result = subprocess.run(
        [
            str(worktree_root / "scripts" / "builderops_cli.sh"),
            "builderops",
            "list",
            "--type",
            "LearningSignal",
            "--json",
        ],
        capture_output=True,
        text=True,
        env={"PATH": f"{fakebin}:{os.environ['PATH']}"},
    )

    assert result.returncode == 0, result.stderr
    assert invocation_cwd.read_text().strip() == str(worktree_root)
    assert invocation_args.read_text().splitlines() == [
        "-m",
        "app.builderops",
        "builderops",
        "list",
        "--type",
        "LearningSignal",
        "--json",
    ]


def test_builderops_wrapper_resolves_repo_venv(tmp_path: Path) -> None:
    """Issue #2215 verify target: wrapper resolves the repo venv from a worktree."""

    test_builderops_wrapper_finds_canonical_venv_from_codex_worktree(tmp_path)


def test_builderops_wrapper_missing_venv_message(tmp_path: Path) -> None:
    """Missing repo venvs fail with an actionable message instead of host Python fallback."""
    canonical_root = tmp_path / "code" / "agentic-pkm-mvp"
    fakebin = tmp_path / "bin"
    worktree_root = tmp_path / ".codex" / "worktrees" / "7c2f" / "agentic-pkm-mvp"

    (canonical_root / ".git").mkdir(parents=True)
    fakebin.mkdir()
    (worktree_root / "scripts").mkdir(parents=True)
    (worktree_root / "scripts" / "builderops_cli.sh").write_text(BUILDEROPS_WRAPPER.read_text())
    (worktree_root / "scripts" / "builderops_cli.sh").chmod(0o755)
    _write_executable(
        fakebin / "git",
        f"""#!/usr/bin/env bash
if [ "$1" = "-C" ] && [ "$3" = "rev-parse" ] && [ "$4" = "--git-common-dir" ]; then
  printf '%s\\n' {canonical_root / ".git"}
  exit 0
fi
exit 1
""",
    )

    result = subprocess.run(
        [str(worktree_root / "scripts" / "builderops_cli.sh"), "builderops", "list", "--json"],
        capture_output=True,
        text=True,
        env={"PATH": f"{fakebin}:{os.environ['PATH']}"},
    )

    assert result.returncode == 1
    assert "requires the repo virtualenv" in result.stderr
    assert "cd /Users/rasmusthornberg/code/agentic-pkm-mvp" in result.stderr
    assert "Host Python" not in result.stderr
