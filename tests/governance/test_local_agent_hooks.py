from __future__ import annotations

import os
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


def test_hook_safety_guard_allows_clean_checkout(tmp_path: Path) -> None:
    clean_repo = tmp_path / "clean-repo"
    head_sha = subprocess.check_output(
        ["git", "rev-parse", "HEAD"],
        cwd=REPO_ROOT,
        text=True,
    ).strip()
    subprocess.run(
        [
            "git",
            "clone",
            "--no-hardlinks",
            str(REPO_ROOT),
            str(clean_repo),
        ],
        check=True,
        text=True,
        capture_output=True,
    )
    subprocess.run(
        ["git", "checkout", "--detach", head_sha],
        cwd=clean_repo,
        check=True,
        text=True,
        capture_output=True,
    )
    subprocess.run(
        ["git", "switch", "-c", "clean-checkout-test"],
        cwd=clean_repo,
        check=True,
        text=True,
        capture_output=True,
    )
    branch = subprocess.check_output(
        ["git", "branch", "--show-current"],
        cwd=clean_repo,
        text=True,
    ).strip()

    result = subprocess.run(
        [
            "scripts/agent_workspace_preflight.sh",
            "--expected-branch",
            branch,
            "--expected-worktree",
            str(clean_repo),
            "--base-branch",
            "",
        ],
        cwd=clean_repo,
        env={**os.environ, "PKM_ALLOW_SHARED_ROOT": "1"},
        check=False,
        text=True,
        capture_output=True,
    )

    assert result.returncode == 0, result.stderr + result.stdout


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


def test_hook_artifacts_are_limited_to_local_session_surfaces() -> None:
    text = "\n".join(
        [
            HOOK_DOC.read_text(encoding="utf-8"),
            (REPO_ROOT / "scripts/local_agent_command_guard.py").read_text(encoding="utf-8"),
        ]
    )

    assert HOOK_DOC.relative_to(REPO_ROOT).as_posix() == ".claude/hooks/README.md"
    assert ".github/workflows" not in text
    assert "pull_request" not in text
    assert "workflow_dispatch" not in text
