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
    assert "project state" in combined
    assert "github.rest" not in combined
    assert "createcomment" not in combined
    assert not classify_command("gh pr merge 1 --squash").allowed
    assert not classify_command("gh pr close 1").allowed
    assert not classify_command("gh issue comment 1 --body blocked").allowed


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
        "gh pr close 3230",
        "pytest -q && gh pr close 3230",
        "git status; gh api repos/o/r/issues/1/comments -f body=hi",
        "GH_TOKEN=x gh pr merge 1 --squash",
        "env GH_TOKEN=x gh api repos/o/r/issues/1/comments --field body=hi",
        "cd /tmp && gh --repo owner/repo pr close 3230",
        "bash -lc 'gh pr close 3230'",
        "/usr/local/bin/gh pr close 3230",
        "result=$(gh api repos/o/r/issues/1/comments -f body=hi)",
        "result=`gh api repos/o/r/issues/1/comments -f body=hi`",
        "(gh pr close 3230)",
        "(gh pr close)",
        "gh --repo owner/repo pr close 3230",
        "gh issue edit 1 --add-label agent:ready",
        "gh label create blocked --color ff0000",
        "gh label delete blocked --yes",
        "gh project item-edit --id X --field-id Y --single-select-option-id Z",
        "gh api repos/owner/repo/issues/1/labels -X POST -f labels[]=blocked",
        "gh api repos/owner/repo/issues/1 --method PATCH -f title=blocked",
        "gh api repos/o/r/issues/1/comments -f body=hi",
        "gh api repos/o/r/issues/1/comments -f=body=hi",
        "gh api repos/o/r/issues/1/labels -F labels[]=blocked",
        "gh api repos/o/r/issues/1/labels -F=body=@msg.txt",
        "gh api repos/o/r/issues/1/comments --raw-field body=hi",
        "gh api repos/o/r/issues/1/comments --field body=hi",
        "gh api repos/o/r/issues/1 --method=POST",
        "gh api repos/o/r/issues/1 -X=PATCH",
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
        ["git", "diff", "--name-only", "origin/main...HEAD"],
        cwd=REPO_ROOT,
        check=False,
        text=True,
        capture_output=True,
    )
    changed_paths = changed.stdout.splitlines()
    if changed.returncode != 0:
        changed_paths = subprocess.run(
            ["git", "show", "--name-only", "--format=", "HEAD"],
            cwd=REPO_ROOT,
            check=True,
            text=True,
            capture_output=True,
        ).stdout.splitlines()
    allowed_prefixes = (".claude/", "scripts/local_agent_command_guard.py", "tests/governance/test_local_agent_hooks.py")

    assert changed_paths
    assert all(path.startswith(allowed_prefixes) for path in changed_paths)
