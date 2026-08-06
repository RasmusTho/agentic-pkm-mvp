"""Production-path tests for the issue pickup claim wrapper."""

from __future__ import annotations

import json
import os
import re
import stat
import subprocess
from pathlib import Path

from app.dispatcher.sync_github import github_issue_task_id


REPO_ROOT = Path(__file__).resolve().parents[2]
SCRIPT = REPO_ROOT / "scripts" / "issue_pickup_claim.sh"


def _write_executable(path: Path, content: str) -> None:
    path.write_text(content, encoding="utf-8")
    path.chmod(path.stat().st_mode | stat.S_IEXEC | stat.S_IXGRP | stat.S_IXOTH)


def _dispatcher_claim(
    *,
    holder: str = "codex-3301",
    include_lease: bool = True,
    expires_at: str = "2099-07-10T01:00:00Z",
) -> str:
    payload: dict[str, object] = {
        "ok": True,
        "task": {
            "task_id": "github-RasmusTho--agentic-pkm-mvp-issue-3301",
            "issue_number": 3301,
            "status": "claimed",
            "claimed_by": holder,
            "lease_id": "lease-3301",
        },
    }
    if include_lease:
        payload["lease"] = {
            "lease_id": "lease-3301",
            "resource": "issue:3301",
            "holder": holder,
            "expires_at": expires_at,
            "released_at": None,
        }
    return json.dumps(payload)


def _make_harness(
    tmp_path: Path,
    *,
    status_json: str,
    claim_json: str = "",
    claim_rc: int = 0,
    label_delete_rc: int = 0,
    release_json: str = '{"ok":true,"task":{"task_id":"github-RasmusTho--agentic-pkm-mvp-issue-3301","status":"ready","claimed_by":null,"lease_id":null}}',
    release_rc: int = 0,
) -> tuple[Path, dict[str, str]]:
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir(parents=True)
    command_log = tmp_path / "commands.log"

    _write_executable(
        bin_dir / "git",
        """#!/usr/bin/env bash
set -eu
case "$*" in
  "branch --show-current") echo "codex/issue-3301-dispatcher-pickup-receipt" ;;
  "rev-parse --show-toplevel") printf '%s\n' "$FAKE_WORKTREE" ;;
  "remote get-url origin") echo "https://github.com/RasmusTho/agentic-pkm-mvp.git" ;;
  *) echo "unexpected git call: $*" >&2; exit 1 ;;
esac
""",
    )
    _write_executable(
        bin_dir / "fake-python",
        """#!/usr/bin/env bash
set -u
printf 'dispatcher %s\n' "$*" >> "$COMMAND_LOG"
case "$*" in
  *"-m app.dispatcher status --json"*) printf '%s\n' "$FAKE_STATUS_JSON"; exit 0 ;;
  *"-m app.dispatcher claim "*) printf '%s\n' "$FAKE_CLAIM_JSON"; exit "$FAKE_CLAIM_RC" ;;
  *"-m app.dispatcher release "*) printf '%s\n' "$FAKE_RELEASE_JSON"; exit "$FAKE_RELEASE_RC" ;;
  *) echo "unexpected dispatcher call: $*" >&2; exit 1 ;;
esac
""",
    )
    _write_executable(
        bin_dir / "gh",
        """#!/usr/bin/env bash
set -eu
printf 'gh %s\n' "$*" >> "$COMMAND_LOG"
case "$*" in
  *"/comments"*) echo '{"id":9876,"html_url":"https://example.test/comment/9876"}' ;;
  *"/labels/agent%3Aready"*) echo '[]'; exit "$FAKE_LABEL_DELETE_RC" ;;
  *) echo "unexpected gh call: $*" >&2; exit 1 ;;
esac
""",
    )

    worktree = tmp_path / "worktree"
    (worktree / "scripts").mkdir(parents=True)
    _write_executable(
        worktree / "scripts" / "agent_workspace_preflight.sh",
        """#!/usr/bin/env bash
set -eu
printf 'preflight %s\n' "$*" >> "$COMMAND_LOG"
""",
    )

    env = dict(os.environ)
    env.update(
        {
            "PATH": f"{bin_dir}{os.pathsep}{env.get('PATH', '')}",
            "PYTHON": str(bin_dir / "fake-python"),
            "JSON_PYTHON": env.get("PYTHON", "python3"),
            "COMMAND_LOG": str(command_log),
            "FAKE_WORKTREE": str(worktree),
            "FAKE_STATUS_JSON": status_json,
            "FAKE_CLAIM_JSON": claim_json,
            "FAKE_CLAIM_RC": str(claim_rc),
            "FAKE_LABEL_DELETE_RC": str(label_delete_rc),
            "FAKE_RELEASE_JSON": release_json,
            "FAKE_RELEASE_RC": str(release_rc),
        }
    )
    return worktree, env


def _run(worktree: Path, env: dict[str, str], *extra: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [
            "bash",
            str(SCRIPT),
            "--issue",
            "3301",
            "--repo",
            "RasmusTho/agentic-pkm-mvp",
            "--agent",
            "codex-3301",
            "--session",
            "session-3301",
            *extra,
        ],
        cwd=worktree,
        env=env,
        capture_output=True,
        text=True,
        check=False,
    )


def test_dispatcher_backed_pickup_requires_verified_lease_before_label_removal(
    tmp_path: Path,
) -> None:
    worktree, env = _make_harness(
        tmp_path,
        status_json=json.dumps(
            {
                "ok": True,
                "db_exists": True,
                "coordination_mode": "dispatcher-backed",
                "fallback_reason": None,
            }
        ),
        claim_json=_dispatcher_claim(),
    )

    result = _run(worktree, env)

    assert result.returncode == 0, result.stdout + result.stderr
    assert "coordination_mode=dispatcher-backed" in result.stdout
    assert "task_id=github-RasmusTho--agentic-pkm-mvp-issue-3301" in result.stdout
    assert "lease_id=lease-3301" in result.stdout
    assert "holder=codex-3301" in result.stdout
    commands = Path(env["COMMAND_LOG"]).read_text(encoding="utf-8")
    assert commands.index("dispatcher -m app.dispatcher claim") < commands.index(
        "gh api --method DELETE"
    )


def test_default_task_id_is_repo_qualified_to_match_dispatcher_pull(tmp_path: Path) -> None:
    """The default ``TASK_ID`` must match the repo-qualified id
    ``app/dispatcher/sync_github.py::normalize_github_issue`` produces for tasks
    synced via ``dispatcher pull --repo``, or a multi-repo-synced issue can never
    be claimed through this wrapper without an explicit ``--task-id`` override.
    """
    worktree, env = _make_harness(
        tmp_path,
        status_json=json.dumps(
            {
                "ok": True,
                "db_exists": True,
                "coordination_mode": "dispatcher-backed",
                "fallback_reason": None,
            }
        ),
        claim_json=json.dumps(
            {
                "ok": True,
                "task": {
                    "task_id": "github-RasmusTho--bifrost-issue-21",
                    "issue_number": 21,
                    "status": "claimed",
                    "claimed_by": "codex-21",
                    "lease_id": "lease-21",
                },
                "lease": {
                    "lease_id": "lease-21",
                    "resource": "issue:21",
                    "holder": "codex-21",
                    "expires_at": "2099-07-10T01:00:00Z",
                    "released_at": None,
                },
            }
        ),
    )

    result = subprocess.run(
        [
            "bash",
            str(SCRIPT),
            "--issue",
            "21",
            "--repo",
            "RasmusTho/bifrost",
            "--agent",
            "codex-21",
            "--session",
            "session-21",
        ],
        cwd=worktree,
        env=env,
        capture_output=True,
        text=True,
        check=False,
    )

    assert result.returncode == 0, result.stdout + result.stderr
    assert "task_id=github-RasmusTho--bifrost-issue-21" in result.stdout
    commands = Path(env["COMMAND_LOG"]).read_text(encoding="utf-8")
    assert "dispatcher -m app.dispatcher claim github-RasmusTho--bifrost-issue-21" in commands


def test_explicit_task_id_override_still_wins(tmp_path: Path) -> None:
    """``--task-id`` bypasses the derived default so multi-repo edge cases keep
    an escape hatch (#4440)."""
    worktree, env = _make_harness(
        tmp_path,
        status_json=json.dumps(
            {
                "ok": True,
                "db_exists": True,
                "coordination_mode": "dispatcher-backed",
                "fallback_reason": None,
            }
        ),
        claim_json=json.dumps(
            {
                "ok": True,
                "task": {
                    "task_id": "custom-task-id-3301",
                    "issue_number": 3301,
                    "status": "claimed",
                    "claimed_by": "codex-3301",
                    "lease_id": "lease-3301",
                },
                "lease": {
                    "lease_id": "lease-3301",
                    "resource": "issue:3301",
                    "holder": "codex-3301",
                    "expires_at": "2099-07-10T01:00:00Z",
                    "released_at": None,
                },
            }
        ),
    )

    result = _run(worktree, env, "--task-id", "custom-task-id-3301")

    assert result.returncode == 0, result.stdout + result.stderr
    assert "task_id=custom-task-id-3301" in result.stdout
    commands = Path(env["COMMAND_LOG"]).read_text(encoding="utf-8")
    assert "dispatcher -m app.dispatcher claim custom-task-id-3301" in commands


def test_default_task_id_derived_from_python_single_source(tmp_path: Path) -> None:
    """The wrapper derives its default task id from
    ``app.dispatcher.sync_github.github_issue_task_id`` and carries no
    independent spelling of the format string (INV-DG-2, #4440)."""
    script_text = SCRIPT.read_text(encoding="utf-8")
    assert "github_issue_task_id" in script_text
    assert re.search(r"github-.*-issue-", script_text) is None

    worktree, env = _make_harness(
        tmp_path,
        status_json=json.dumps(
            {
                "ok": True,
                "db_exists": True,
                "coordination_mode": "dispatcher-backed",
                "fallback_reason": None,
            }
        ),
        claim_json=_dispatcher_claim(),
    )

    result = _run(worktree, env)

    assert result.returncode == 0, result.stdout + result.stderr
    expected = github_issue_task_id("RasmusTho/agentic-pkm-mvp", 3301)
    assert f"task_id={expected}" in result.stdout
    commands = Path(env["COMMAND_LOG"]).read_text(encoding="utf-8")
    assert f"dispatcher -m app.dispatcher claim {expected}" in commands


def test_dispatcher_availability_is_not_reported_as_acquired_claim(tmp_path: Path) -> None:
    status = json.dumps(
        {
            "ok": True,
            "db_exists": True,
            "coordination_mode": "dispatcher-backed",
            "fallback_reason": None,
        }
    )
    cases = [
        ("missing-task", "", 1),
        ("missing-lease", _dispatcher_claim(include_lease=False), 0),
        ("wrong-owner", _dispatcher_claim(holder="another-agent"), 0),
        ("expired-lease", _dispatcher_claim(expires_at="2000-01-01T00:00:00Z"), 0),
    ]

    for name, claim_json, claim_rc in cases:
        case_root = tmp_path / name
        case_root.mkdir()
        worktree, env = _make_harness(
            case_root,
            status_json=status,
            claim_json=claim_json,
            claim_rc=claim_rc,
        )

        result = _run(worktree, env)

        assert result.returncode != 0, name
        assert "pickup-claim-complete" not in result.stdout
        commands = Path(env["COMMAND_LOG"]).read_text(encoding="utf-8")
        assert "gh api --method DELETE" not in commands
        if claim_rc == 0:
            assert "dispatcher -m app.dispatcher release github-RasmusTho--agentic-pkm-mvp-issue-3301" in commands


def test_label_only_fallback_emits_durable_claimant_receipt(tmp_path: Path) -> None:
    worktree, env = _make_harness(
        tmp_path,
        status_json=json.dumps(
            {
                "ok": True,
                "db_exists": False,
                "coordination_mode": "github-label-only-fallback",
                "fallback_reason": "dispatcher_db_missing",
            }
        ),
    )

    result = _run(
        worktree,
        env,
        "--coordination-mode",
        "github-label-only-fallback",
        "--fallback-reason",
        "dispatcher_db_missing",
    )

    assert result.returncode == 0, result.stdout + result.stderr
    assert "coordination_mode=github-label-only-fallback" in result.stdout
    assert "fallback_reason=dispatcher_db_missing" in result.stdout
    assert "agent=codex-3301" in result.stdout
    assert "session=session-3301" in result.stdout
    commands = Path(env["COMMAND_LOG"]).read_text(encoding="utf-8")
    comment_at = commands.index("gh api --method POST")
    label_at = commands.index("gh api --method DELETE")
    assert comment_at < label_at
    assert "agent=codex-3301" in commands
    assert "session=session-3301" in commands
    assert "fallback_reason=dispatcher_db_missing" in commands
    assert "dispatcher-backed" not in result.stdout


def test_label_delete_failure_reports_verified_dispatcher_release(tmp_path: Path) -> None:
    worktree, env = _make_harness(
        tmp_path,
        status_json=json.dumps(
            {
                "ok": True,
                "db_exists": True,
                "coordination_mode": "dispatcher-backed",
                "fallback_reason": None,
            }
        ),
        claim_json=_dispatcher_claim(),
        label_delete_rc=1,
    )

    result = _run(worktree, env)

    assert result.returncode != 0
    assert "cleanup=released" in result.stderr
    assert "evidence=verified-dispatcher-release" in result.stderr
    assert "task_id=github-RasmusTho--agentic-pkm-mvp-issue-3301" in result.stderr
    assert "lease_id=lease-3301" in result.stderr
    assert "holder=codex-3301" in result.stderr
    assert "pickup-claim-complete" not in result.stdout


def test_label_delete_and_release_failure_reports_cleanup_failed_evidence(
    tmp_path: Path,
) -> None:
    worktree, env = _make_harness(
        tmp_path,
        status_json=json.dumps(
            {
                "ok": True,
                "db_exists": True,
                "coordination_mode": "dispatcher-backed",
                "fallback_reason": None,
            }
        ),
        claim_json=_dispatcher_claim(),
        label_delete_rc=1,
        release_json='{ "ok": false }',
        release_rc=1,
    )

    result = _run(worktree, env)

    assert result.returncode != 0
    assert "cleanup-failed" in result.stderr
    assert "task_id=github-RasmusTho--agentic-pkm-mvp-issue-3301" in result.stderr
    assert "lease_id=lease-3301" in result.stderr
    assert "holder=codex-3301" in result.stderr
    assert "cleanup=released" not in result.stderr
    assert "pickup-claim-complete" not in result.stdout


def test_partial_sync_fallback_requires_requested_task_evidence(
    tmp_path: Path,
) -> None:
    """Provider-wide partial sync is not evidence about one requested task.

    The kill switch skips only the non-essential open-issue reconciliation
    scan; the essential ``agent:ready`` scan still runs. A missing task must
    therefore remain an opaque claim failure unless task-specific evidence is
    available, rather than offering a lease-bypassing label-only rerun.
    """
    worktree, env = _make_harness(
        tmp_path,
        status_json=json.dumps(
            {
                "ok": True,
                "db_exists": True,
                "coordination_mode": "dispatcher-backed",
                "fallback_reason": None,
                "last_sync": {
                    "last_pull_at": "2026-07-30T23:54:56+00:00",
                    "sync_result": "partial",
                    "sync_note": (
                        "kill switch active: non-essential open-issues scan skipped"
                    ),
                    "kill_switch_active": True,
                },
            }
        ),
        claim_json=json.dumps(
            {
                "ok": False,
                "error": "Task github-RasmusTho--agentic-pkm-mvp-issue-3301 not found",
            }
        ),
        claim_rc=1,
    )

    result = _run(worktree, env)

    assert result.returncode != 0
    assert "pickup-claim-complete" not in result.stdout
    assert "cause=kill-switch-partial-sync" not in result.stderr
    assert "--coordination-mode github-label-only-fallback" not in result.stderr
    assert "dispatcher claim failed for expected task" in result.stderr
    commands = Path(env["COMMAND_LOG"]).read_text(encoding="utf-8")
    assert "gh api --method DELETE" not in commands


def test_complete_sync_missing_task_keeps_opaque_claim_failure(
    tmp_path: Path,
) -> None:
    """A missing task after a complete (ok) sync is a genuine claim failure and
    must not be routed to label-only fallback guidance (#4606)."""
    worktree, env = _make_harness(
        tmp_path,
        status_json=json.dumps(
            {
                "ok": True,
                "db_exists": True,
                "coordination_mode": "dispatcher-backed",
                "fallback_reason": None,
                "last_sync": {
                    "last_pull_at": "2026-07-30T23:54:56+00:00",
                    "sync_result": "ok",
                    "sync_note": None,
                    "kill_switch_active": False,
                },
            }
        ),
        claim_json=json.dumps(
            {
                "ok": False,
                "error": "Task github-RasmusTho--agentic-pkm-mvp-issue-3301 not found",
            }
        ),
        claim_rc=1,
    )

    result = _run(worktree, env)

    assert result.returncode != 0
    assert "pickup-claim-complete" not in result.stdout
    assert "cause=kill-switch-partial-sync" not in result.stderr
    assert "dispatcher claim failed for expected task" in result.stderr
    commands = Path(env["COMMAND_LOG"]).read_text(encoding="utf-8")
    assert "gh api --method DELETE" not in commands
