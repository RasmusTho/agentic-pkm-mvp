"""Production-path tests for the issue pickup claim wrapper."""

from __future__ import annotations

import json
import os
import re
import stat
import subprocess
from pathlib import Path

import pytest

from app.dispatcher.sync_github import github_issue_task_id


REPO_ROOT = Path(__file__).resolve().parents[2]
SCRIPT = REPO_ROOT / "scripts" / "issue_pickup_claim.sh"
VALID_READY_BODY = (
    REPO_ROOT / "tests/fixtures/issue_readiness/valid_ready_candidate.md"
).read_text(encoding="utf-8")


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
    status_rc: int = 0,
    pickup_refresh_json: str = (
        '{"ok":true,"ready":true,"action":"claim",'
        '"reason":"fresh_ready_observation","refreshed":false}'
    ),
    pickup_refresh_rc: int = 0,
    claim_json: str = "",
    claim_rc: int = 0,
    label_replace_rc: int = 0,
    labels_json: str = '[{"name":"type:task"},{"name":"prio:high"},{"name":"lane:governance"},{"name":"agent:ready"}]',
    labels_after_write_json: str | None = None,
    label_readback_rc: int = 0,
    release_json: str = '{"ok":true,"task":{"task_id":"github-RasmusTho--agentic-pkm-mvp-issue-3301","status":"ready","claimed_by":null,"lease_id":null}}',
    release_rc: int = 0,
    issue_json: str | None = None,
) -> tuple[Path, dict[str, str]]:
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir(parents=True)
    command_log = tmp_path / "commands.log"
    if labels_after_write_json is None:
        labels_after_write_json = labels_json
    if issue_json is None:
        issue_json = json.dumps(
            {
                "number": 3301,
                "state": "open",
                "labels": [
                    {"name": "type:task"},
                    {"name": "prio:high"},
                    {"name": "lane:governance"},
                    {"name": "agent:ready"},
                ],
                "body": VALID_READY_BODY,
            }
        )

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
  *"-m app.dispatcher status --json"*) printf '%s\n' "$FAKE_STATUS_JSON"; exit "$FAKE_STATUS_RC" ;;
  *"-m app.dispatcher pickup-refresh "*) printf '%s\n' "$FAKE_PICKUP_REFRESH_JSON"; exit "$FAKE_PICKUP_REFRESH_RC" ;;
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
  *"--method GET repos/"*"/labels"*)
    if [[ -f "$FAKE_LABEL_WRITE_MARKER" ]]; then
      if [[ "$FAKE_LABEL_READBACK_RC" -ne 0 ]]; then exit "$FAKE_LABEL_READBACK_RC"; fi
      printf '%s\n' "$FAKE_LABELS_AFTER_WRITE_JSON"
    else
      printf '%s\n' "$FAKE_LABELS_JSON"
    fi
    ;;
  *"--method PUT repos/"*"/labels"*)
    cat > "$FAKE_LABEL_PAYLOAD"
    touch "$FAKE_LABEL_WRITE_MARKER"
    echo '[]'
    exit "$FAKE_LABEL_REPLACE_RC"
    ;;
  "api repos/"*"/issues/"[0-9]*) printf '%s\n' "$FAKE_ISSUE_JSON" ;;
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
            "FAKE_STATUS_RC": str(status_rc),
            "FAKE_PICKUP_REFRESH_JSON": pickup_refresh_json,
            "FAKE_PICKUP_REFRESH_RC": str(pickup_refresh_rc),
            "FAKE_CLAIM_JSON": claim_json,
            "FAKE_CLAIM_RC": str(claim_rc),
            "FAKE_LABEL_REPLACE_RC": str(label_replace_rc),
            "FAKE_LABELS_JSON": labels_json,
            "FAKE_LABELS_AFTER_WRITE_JSON": labels_after_write_json,
            "FAKE_LABEL_READBACK_RC": str(label_readback_rc),
            "FAKE_LABEL_WRITE_MARKER": str(tmp_path / "label-write-complete"),
            "FAKE_LABEL_PAYLOAD": str(tmp_path / "labels.json"),
            "FAKE_RELEASE_JSON": release_json,
            "FAKE_RELEASE_RC": str(release_rc),
            "FAKE_ISSUE_JSON": issue_json,
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


def test_dispatcher_backed_pickup_replaces_ready_with_in_progress_after_verified_lease(
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
    assert commands.index("dispatcher -m app.dispatcher pickup-refresh") < commands.index(
        "dispatcher -m app.dispatcher claim"
    )
    assert commands.index("dispatcher -m app.dispatcher claim") < commands.index(
        "gh api --method GET repos/RasmusTho/agentic-pkm-mvp/issues/3301/labels"
    )
    assert "gh api --method PUT repos/RasmusTho/agentic-pkm-mvp/issues/3301/labels" in commands
    assert json.loads(Path(env["FAKE_LABEL_PAYLOAD"]).read_text(encoding="utf-8")) == {
        "labels": ["type:task", "prio:high", "lane:governance", "agent:in-progress"]
    }


def test_pickup_normalizes_stale_mixed_agent_labels_without_erasing_non_agent_labels(
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
        labels_json=(
            '[{"name":"type:task"},{"name":"prio:high"},{"name":"lane:governance"},'
            '{"name":"agent:ready"},{"name":"agent:blocked"},'
            '{"name":"agent:needs-human"},{"name":"agent:in-progress"}]'
        ),
    )

    result = _run(worktree, env)

    assert result.returncode == 0, result.stdout + result.stderr
    assert json.loads(Path(env["FAKE_LABEL_PAYLOAD"]).read_text(encoding="utf-8")) == {
        "labels": ["type:task", "prio:high", "lane:governance", "agent:in-progress"]
    }


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
        assert "gh api --method PUT repos/" not in commands
        if claim_rc == 0:
            assert "dispatcher -m app.dispatcher release github-RasmusTho--agentic-pkm-mvp-issue-3301" in commands


def test_dispatcher_refresh_refusal_does_not_claim_or_mutate_labels(tmp_path: Path) -> None:
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
        pickup_refresh_json=json.dumps(
            {
                "ok": False,
                "ready": False,
                "action": "refuse",
                "reason": "task_not_in_observed_ready_set",
                # A stale or buggy response must never authorize lease bypass.
                "fallback_allowed": True,
            }
        ),
        pickup_refresh_rc=1,
    )

    result = _run(worktree, env)

    assert result.returncode != 0
    assert "reason=task_not_in_observed_ready_set" in result.stderr
    assert "agent:ready was not removed" in result.stderr
    assert "pickup-claim-complete" not in result.stdout
    commands = Path(env["COMMAND_LOG"]).read_text(encoding="utf-8")
    assert "dispatcher -m app.dispatcher pickup-refresh" in commands
    assert "dispatcher -m app.dispatcher claim" not in commands
    assert "gh api repos/RasmusTho/agentic-pkm-mvp/issues/3301" not in commands
    assert "gh api --method POST" not in commands
    assert "gh api --method PUT repos/" not in commands


def test_explicit_label_fallback_is_refused_when_dispatcher_is_available(
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
    )

    result = _run(
        worktree,
        env,
        "--coordination-mode",
        "github-label-only-fallback",
        "--fallback-reason",
        "operator-requested",
    )

    assert result.returncode != 0
    assert "fallback refused while dispatcher-backed coordination is available" in result.stderr
    commands = Path(env["COMMAND_LOG"]).read_text(encoding="utf-8")
    assert "dispatcher -m app.dispatcher status --json" in commands
    assert "dispatcher -m app.dispatcher pickup-refresh" not in commands
    assert "dispatcher -m app.dispatcher claim" not in commands
    assert "gh api repos/RasmusTho/agentic-pkm-mvp/issues/3301" not in commands
    assert "gh api --method POST" not in commands
    assert "gh api --method PUT repos/" not in commands


def test_label_fallback_is_refused_when_database_exists_but_status_is_degraded(
    tmp_path: Path,
) -> None:
    worktree, env = _make_harness(
        tmp_path,
        status_json=json.dumps(
            {
                "ok": True,
                "db_exists": True,
                "coordination_mode": "github-label-only-fallback",
                "fallback_reason": "dispatcher_db_uninitialized",
            }
        ),
    )

    result = _run(worktree, env)

    assert result.returncode != 0
    assert "dispatcher status is malformed or inconsistent" in result.stderr
    commands = Path(env["COMMAND_LOG"]).read_text(encoding="utf-8")
    assert "gh api repos/RasmusTho/agentic-pkm-mvp/issues/3301" not in commands
    assert "gh api --method POST" not in commands
    assert "gh api --method PUT repos/" not in commands


def test_status_failure_uses_strict_label_fallback(
    tmp_path: Path,
) -> None:
    worktree, env = _make_harness(
        tmp_path,
        status_json="{}",
        status_rc=1,
    )

    result = _run(worktree, env)

    assert result.returncode == 0, result.stdout + result.stderr
    assert "coordination_mode=github-label-only-fallback" in result.stdout
    assert "fallback_reason=dispatcher_status_failed" in result.stdout
    commands = Path(env["COMMAND_LOG"]).read_text(encoding="utf-8")
    assert "dispatcher -m app.dispatcher status --json" in commands
    assert "dispatcher -m app.dispatcher pickup-refresh" not in commands
    assert "dispatcher -m app.dispatcher claim" not in commands
    ready_read_at = commands.index("gh api repos/RasmusTho/agentic-pkm-mvp/issues/3301")
    comment_at = commands.index("gh api --method POST")
    label_write_at = commands.index(
        "gh api --method PUT repos/RasmusTho/agentic-pkm-mvp/issues/3301/labels"
    )
    assert ready_read_at < comment_at < label_write_at


def test_malformed_successful_status_read_fails_closed(tmp_path: Path) -> None:
    worktree, env = _make_harness(
        tmp_path,
        status_json="{}",
    )

    result = _run(worktree, env)

    assert result.returncode != 0
    assert "dispatcher status is malformed or inconsistent" in result.stderr
    commands = Path(env["COMMAND_LOG"]).read_text(encoding="utf-8")
    assert "gh api repos/RasmusTho/agentic-pkm-mvp/issues/3301" not in commands
    assert "gh api --method POST" not in commands
    assert "gh api --method PUT repos/" not in commands


def test_label_only_fallback_refuses_issue_without_strict_readiness(
    tmp_path: Path,
) -> None:
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
        issue_json=json.dumps(
            {
                "number": 3301,
                "state": "open",
                "labels": [{"name": "agent:ready"}],
                "body": "incomplete issue body",
            }
        ),
    )

    result = _run(worktree, env)

    assert result.returncode != 0
    assert "exact issue is not freshly open and strictly ready" in result.stderr
    commands = Path(env["COMMAND_LOG"]).read_text(encoding="utf-8")
    assert "gh api repos/RasmusTho/agentic-pkm-mvp/issues/3301" in commands
    assert "gh api --method POST" not in commands
    assert "gh api --method PUT repos/" not in commands


def test_label_only_fallback_refuses_mismatched_issue_identity(tmp_path: Path) -> None:
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
        issue_json=json.dumps(
            {
                "number": 3302,
                "state": "open",
                "labels": [{"name": "agent:ready"}],
                "body": VALID_READY_BODY,
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

    assert result.returncode != 0
    assert "exact issue is not freshly open and strictly ready" in result.stderr
    commands = Path(env["COMMAND_LOG"]).read_text(encoding="utf-8")
    assert "gh api repos/RasmusTho/agentic-pkm-mvp/issues/3301" in commands
    assert "gh api --method POST" not in commands
    assert "gh api --method PUT repos/" not in commands


def test_label_only_fallback_refuses_conflicting_agent_state_labels(
    tmp_path: Path,
) -> None:
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
        issue_json=json.dumps(
            {
                "number": 3301,
                "state": "open",
                "labels": [
                    {"name": "agent:ready"},
                    {"name": "agent:in-progress"},
                ],
                "body": VALID_READY_BODY,
            }
        ),
    )

    result = _run(worktree, env)

    assert result.returncode != 0
    assert "exact issue is not freshly open and strictly ready" in result.stderr
    commands = Path(env["COMMAND_LOG"]).read_text(encoding="utf-8")
    assert "gh api repos/RasmusTho/agentic-pkm-mvp/issues/3301" in commands
    assert "gh api --method POST" not in commands
    assert "gh api --method PUT repos/" not in commands


def test_label_only_fallback_refuses_closed_issue(tmp_path: Path) -> None:
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
        issue_json=json.dumps(
            {
                "number": 3301,
                "state": "closed",
                "labels": [{"name": "agent:ready"}],
                "body": VALID_READY_BODY,
            }
        ),
    )

    result = _run(worktree, env)

    assert result.returncode != 0
    assert "exact issue is not freshly open and strictly ready" in result.stderr
    commands = Path(env["COMMAND_LOG"]).read_text(encoding="utf-8")
    assert "gh api repos/RasmusTho/agentic-pkm-mvp/issues/3301" in commands
    assert "gh api --method POST" not in commands
    assert "gh api --method PUT repos/" not in commands


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

    result = _run(worktree, env)

    assert result.returncode == 0, result.stdout + result.stderr
    assert "coordination_mode=github-label-only-fallback" in result.stdout
    assert "fallback_reason=dispatcher_db_missing" in result.stdout
    assert "agent=codex-3301" in result.stdout
    assert "session=session-3301" in result.stdout
    commands = Path(env["COMMAND_LOG"]).read_text(encoding="utf-8")
    assert "dispatcher -m app.dispatcher pickup-refresh" not in commands
    ready_read_at = commands.index("gh api repos/RasmusTho/agentic-pkm-mvp/issues/3301")
    comment_at = commands.index("gh api --method POST")
    label_at = commands.index("gh api --method PUT repos/RasmusTho/agentic-pkm-mvp/issues/3301/labels")
    assert ready_read_at < comment_at < label_at
    assert "agent=codex-3301" in commands
    assert "session=session-3301" in commands
    assert "fallback_reason=dispatcher_db_missing" in commands
    assert "dispatcher-backed" not in result.stdout
    assert json.loads(Path(env["FAKE_LABEL_PAYLOAD"]).read_text(encoding="utf-8")) == {
        "labels": ["type:task", "prio:high", "lane:governance", "agent:in-progress"]
    }


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
        label_replace_rc=1,
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
        label_replace_rc=1,
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


def test_lost_label_write_response_is_reconciled_from_github_readback(
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
        label_replace_rc=1,
        labels_after_write_json=(
            '[{"name":"type:task"},{"name":"prio:high"},'
            '{"name":"lane:governance"},{"name":"agent:in-progress"}]'
        ),
    )

    result = _run(worktree, env)

    assert result.returncode == 0, result.stdout + result.stderr
    assert "pickup-claim-complete" in result.stdout
    assert "lease_id=lease-3301" in result.stdout
    commands = Path(env["COMMAND_LOG"]).read_text(encoding="utf-8")
    assert commands.count(
        "gh api --method GET repos/RasmusTho/agentic-pkm-mvp/issues/3301/labels"
    ) == 2
    assert "dispatcher -m app.dispatcher release" not in commands


@pytest.mark.parametrize(
    "labels_after_write_json",
    [
        '[{"name":"type:task"},{"name":"prio:high"},'
        '{"name":"lane:governance"},{"name":"agent:in-progress"},'
        '{"name":"agent:blocked"}]',
        '[{"name":"type:task"},{"name":"prio:high"},'
        '{"name":"lane:governance"},{"name":"agent:ready"},'
        '{"name":"agent:blocked"}]',
    ],
    ids=["in-progress-plus-blocked", "ready-plus-blocked"],
)
def test_mixed_label_readback_retains_dispatcher_lease(
    tmp_path: Path,
    labels_after_write_json: str,
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
        label_replace_rc=1,
        labels_after_write_json=labels_after_write_json,
    )

    result = _run(worktree, env)

    assert result.returncode != 0
    assert "label-transition-unknown cleanup=lease-retained" in result.stderr
    assert "lease_id=lease-3301" in result.stderr
    assert "pickup-claim-complete" not in result.stdout
    commands = Path(env["COMMAND_LOG"]).read_text(encoding="utf-8")
    assert "dispatcher -m app.dispatcher release" not in commands


def test_unknown_label_write_outcome_retains_dispatcher_lease(
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
        label_replace_rc=1,
        label_readback_rc=1,
    )

    result = _run(worktree, env)

    assert result.returncode != 0
    assert "label-transition-unknown cleanup=lease-retained" in result.stderr
    assert "lease_id=lease-3301" in result.stderr
    assert "pickup-claim-complete" not in result.stdout
    commands = Path(env["COMMAND_LOG"]).read_text(encoding="utf-8")
    assert "dispatcher -m app.dispatcher release" not in commands


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
        pickup_refresh_json=json.dumps(
            {
                "ok": False,
                "ready": False,
                "action": "refuse",
                "reason": "target_repository_sync_failed",
            }
        ),
        pickup_refresh_rc=1,
    )

    result = _run(worktree, env)

    assert result.returncode != 0
    assert "pickup-claim-complete" not in result.stdout
    assert "cause=kill-switch-partial-sync" not in result.stderr
    assert "--coordination-mode github-label-only-fallback" not in result.stderr
    assert "dispatcher pickup refresh refused" in result.stderr
    commands = Path(env["COMMAND_LOG"]).read_text(encoding="utf-8")
    assert "dispatcher -m app.dispatcher claim" not in commands
    assert "gh api --method PUT repos/" not in commands


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
        pickup_refresh_json=json.dumps(
            {
                "ok": False,
                "ready": False,
                "action": "refuse",
                "reason": "task_missing",
            }
        ),
        pickup_refresh_rc=1,
    )

    result = _run(worktree, env)

    assert result.returncode != 0
    assert "pickup-claim-complete" not in result.stdout
    assert "cause=kill-switch-partial-sync" not in result.stderr
    assert "dispatcher pickup refresh refused" in result.stderr
    commands = Path(env["COMMAND_LOG"]).read_text(encoding="utf-8")
    assert "dispatcher -m app.dispatcher claim" not in commands
    assert "gh api --method PUT repos/" not in commands
