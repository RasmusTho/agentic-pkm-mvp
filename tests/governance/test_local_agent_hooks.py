from __future__ import annotations

import subprocess
import sys
from pathlib import Path

from scripts.local_agent_command_guard import classify_command


REPO_ROOT = Path(__file__).resolve().parents[2]
HOOK_DOC = REPO_ROOT / ".claude/hooks/README.md"


def test_hook_docs_explain_event_command_behavior_and_failure_mode() -> None:
    text = HOOK_DOC.read_text(encoding="utf-8")

    assert "SessionStart" in text
    assert "PreToolUse: Bash" in text
    assert "Failure Mode" in text
    assert "scripts/agent_workspace_preflight.sh" in text
    assert "scripts/local_agent_command_guard.py" in text


def test_hooks_do_not_post_push_merge_label_project_or_close() -> None:
    combined = "\n".join(
        [
            HOOK_DOC.read_text(encoding="utf-8"),
            (REPO_ROOT / "scripts/local_agent_command_guard.py").read_text(encoding="utf-8"),
        ]
    ).lower()

    assert "git push" in combined
    assert "not allowed" in combined
    assert "pr merge" in combined
    assert "issue\\s+" in combined and "close|edit|comment" in combined
    assert "project state" in combined
    assert "github.rest" not in combined
    assert "createcomment" not in combined


def test_hooks_reuse_existing_preflight_or_small_safe_helpers() -> None:
    text = HOOK_DOC.read_text(encoding="utf-8")

    assert "scripts/agent_workspace_preflight.sh" in text
    assert "python3 scripts/local_agent_command_guard.py" in text


def test_dangerous_command_guard_allows_validation_and_denies_prod_or_destructive_commands() -> None:
    allowed = [
        "pytest -q tests/governance/test_local_agent_hooks.py",
        "ruff check scripts tests",
        "git status --short --branch",
        "scripts/agent_workspace_preflight.sh --allow-dirty",
    ]
    denied = [
        "rm -rf /tmp/something",
        "git push origin main",
        "gh pr merge 1 --squash",
        "gh issue edit 1 --add-label agent:ready",
        "prod migrate restart",
        "alembic upgrade head",
        "vault secret write token",
    ]

    for command in allowed:
        assert classify_command(command).allowed, command
    for command in denied:
        assert not classify_command(command).allowed, command


def test_command_guard_cli_exit_codes() -> None:
    allowed = subprocess.run(
        [sys.executable, "scripts/local_agent_command_guard.py", "--command", "pytest -q"],
        cwd=REPO_ROOT,
        check=False,
        text=True,
        capture_output=True,
    )
    blocked = subprocess.run(
        [sys.executable, "scripts/local_agent_command_guard.py", "--command", "git push origin main"],
        cwd=REPO_ROOT,
        check=False,
        text=True,
        capture_output=True,
    )

    assert allowed.returncode == 0
    assert blocked.returncode == 1


def test_changed_paths_are_limited_to_claude_docs_or_local_helpers() -> None:
    changed = subprocess.run(
        ["git", "status", "--short"],
        cwd=REPO_ROOT,
        check=True,
        text=True,
        capture_output=True,
    ).stdout.splitlines()
    allowed_prefixes = (".claude/", "scripts/local_agent_command_guard.py", "tests/governance/test_local_agent_hooks.py")

    assert changed
    paths = [line[3:] for line in changed]
    assert all(path.startswith(allowed_prefixes) for path in paths)
