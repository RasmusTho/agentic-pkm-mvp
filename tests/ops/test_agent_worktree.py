from __future__ import annotations

import json
import subprocess
from pathlib import Path

import pytest

from scripts import agent_worktree, git_hygiene


def test_lifecycle_register_heartbeat_release_and_report(
    tmp_path,
    monkeypatch,
) -> None:
    repo = tmp_path / "repo"
    repo.mkdir()
    worktree = tmp_path / "issue-4015"
    worktree.mkdir()
    registry_path = tmp_path / "agent-worktrees.json"
    monkeypatch.setattr(
        agent_worktree,
        "_worktree_identity",
        lambda _cwd, _worktree: (worktree.resolve(), "codex/issue-4015"),
    )

    registered = agent_worktree.register_worktree(
        repo,
        worktree=worktree,
        owner="codex-4015",
        ttl_seconds=60,
        registry_path=registry_path,
        now=100,
    )
    assert registered["status"] == "active"
    assert registered["expires_at"] == 160

    heartbeat = agent_worktree.heartbeat_worktree(
        repo,
        worktree=worktree,
        owner="codex-4015",
        ttl_seconds=90,
        registry_path=registry_path,
        now=120,
    )
    assert heartbeat["heartbeat_at"] == 120
    assert heartbeat["expires_at"] == 210

    released = agent_worktree.release_worktree(
        repo,
        worktree=worktree,
        owner="codex-4015",
        registry_path=registry_path,
        now=130,
    )
    assert released["status"] == "released"
    assert released["expires_at"] == 130

    completed = agent_worktree.complete_worktree(
        repo,
        worktree=worktree,
        owner="codex-4015",
        registry_path=registry_path,
        now=135,
    )
    assert completed["status"] == "complete"
    assert completed["expires_at"] == 135

    captured: dict[str, object] = {}

    def fake_plan(_cwd: Path, **kwargs):
        captured.update(kwargs)
        return {
            "mode": "report",
            "candidates": {"worktrees": []},
            "reclaimable_worktrees": [],
            "orphaned_worktrees": [],
            "skipped": [],
            "preservation_receipts": [],
        }

    monkeypatch.setattr(git_hygiene, "build_janitor_plan", fake_plan)
    report = agent_worktree.janitor_report(
        repo,
        registry_path=registry_path,
        now=140,
    )

    assert report["mode"] == "report-only"
    records = captured["lifecycle_records"]
    assert isinstance(records, dict)
    assert records[str(worktree.resolve())]["status"] == "complete"


def test_lifecycle_registration_preserves_active_owner_until_expiry(
    tmp_path,
    monkeypatch,
) -> None:
    repo = tmp_path / "repo"
    repo.mkdir()
    worktree = tmp_path / "issue-4015"
    worktree.mkdir()
    registry_path = tmp_path / "agent-worktrees.json"
    monkeypatch.setattr(
        agent_worktree,
        "_worktree_identity",
        lambda _cwd, _worktree: (worktree.resolve(), "codex/issue-4015"),
    )
    agent_worktree.register_worktree(
        repo,
        worktree=worktree,
        owner="first-owner",
        ttl_seconds=60,
        registry_path=registry_path,
        now=100,
    )

    with pytest.raises(
        agent_worktree.WorktreeLifecycleError,
        match="active lifecycle owner",
    ):
        agent_worktree.register_worktree(
            repo,
            worktree=worktree,
            owner="second-owner",
            ttl_seconds=60,
            registry_path=registry_path,
            now=159,
        )

    takeover = agent_worktree.register_worktree(
        repo,
        worktree=worktree,
        owner="second-owner",
        ttl_seconds=60,
        registry_path=registry_path,
        now=160,
    )
    assert takeover["owner"] == "second-owner"
    assert takeover["expires_at"] == 220


def test_janitor_preserves_active_locked_dirty_and_unregistered_worktrees(
    tmp_path,
    monkeypatch,
) -> None:
    root = tmp_path / "repo"
    root.mkdir()
    active = tmp_path / "active"
    locked = tmp_path / "locked"
    dirty = tmp_path / "dirty"
    unregistered = tmp_path / "unregistered"
    eligible = tmp_path / "eligible"
    for path in (active, locked, dirty, unregistered, eligible):
        path.mkdir()

    porcelain = (
        f"worktree {root}\nHEAD root\nbranch refs/heads/main\n\n"
        f"worktree {active}\nHEAD a\nbranch refs/heads/codex/active\n\n"
        f"worktree {locked}\nHEAD b\nbranch refs/heads/codex/locked\nlocked session\n\n"
        f"worktree {dirty}\nHEAD c\nbranch refs/heads/codex/dirty\n\n"
        f"worktree {unregistered}\nHEAD d\nbranch refs/heads/codex/unregistered\n\n"
        f"worktree {eligible}\nHEAD e\nbranch refs/heads/codex/eligible\n\n"
    )

    def fake_run_git(args: list[str], _cwd: Path) -> str:
        if args == ["branch", "--show-current"]:
            return "main"
        if args == ["rev-parse", "--show-toplevel"]:
            return str(root)
        if args == ["worktree", "list", "--porcelain"]:
            return porcelain
        if args == ["for-each-ref", "--format=%(refname:short)", "refs/heads"]:
            return "\n".join(
                [
                    "main",
                    "codex/active",
                    "codex/locked",
                    "codex/dirty",
                    "codex/unregistered",
                    "codex/eligible",
                ]
            )
        if args == ["for-each-ref", "--format=%(refname:short)", "refs/remotes/origin"]:
            return ""
        if args == ["stash", "list", "--date=unix"]:
            return ""
        if args == ["worktree", "prune", "--dry-run"]:
            return ""
        if args == ["remote", "prune", "origin", "--dry-run"]:
            return ""
        raise AssertionError(f"unexpected git command: {args}")

    monkeypatch.setattr(git_hygiene, "run_git", fake_run_git)
    monkeypatch.setattr(git_hygiene, "_is_ancestor", lambda *_args: True)
    monkeypatch.setattr(
        git_hygiene,
        "_worktree_dirty",
        lambda path: path == str(dirty),
    )
    records = {
        str(active.resolve()): {
            "path": str(active.resolve()),
            "branch": "codex/active",
            "status": "active",
            "expires_at": 200,
        },
        str(locked.resolve()): {
            "path": str(locked.resolve()),
            "branch": "codex/locked",
            "status": "released",
            "expires_at": 50,
        },
        str(dirty.resolve()): {
            "path": str(dirty.resolve()),
            "branch": "codex/dirty",
            "status": "released",
            "expires_at": 50,
        },
        str(eligible.resolve()): {
            "path": str(eligible.resolve()),
            "branch": "codex/eligible",
            "status": "complete",
            "expires_at": 50,
        },
    }

    report = git_hygiene.build_janitor_plan(
        root,
        lifecycle_records=records,
        pr_states={
            branch: {"state": "MERGED", "isDraft": False}
            for branch in (
                "codex/active",
                "codex/locked",
                "codex/dirty",
                "codex/unregistered",
                "codex/eligible",
            )
        },
        now=100,
    )

    reasons = {
        item["path"]: item["reason"]
        for item in report["skipped"]
        if item.get("artifact") == "worktree"
    }
    assert reasons[str(active)] == "active_registration"
    assert reasons[str(locked)] == "locked_worktree"
    assert reasons[str(dirty)] == "dirty_worktree"
    assert reasons[str(unregistered)] == "unregistered_worktree"
    assert report["reclaimable_worktrees"] == [
        {
            "path": str(eligible),
            "branch": "codex/eligible",
            "merge_proof": "ancestor_of_origin_main",
        }
    ]

    commands: list[list[str]] = []

    def fake_run_git_result(args: list[str], _cwd: Path):
        commands.append(args)
        return subprocess.CompletedProcess(["git", *args], 0, "", "")

    monkeypatch.setattr(git_hygiene, "run_git_result", fake_run_git_result)
    monkeypatch.setattr(
        git_hygiene,
        "build_janitor_plan",
        lambda *_args, **_kwargs: report,
    )
    applied = git_hygiene.janitor_apply(
        root,
        active_leases=[],
        pr_states={},
        lifecycle_records=records,
    )

    assert applied["ok"] is False
    assert applied["errors"][0]["reason"] == "preservation_evidence_present"
    assert commands == [["fetch", "--prune", "origin"]]


def test_janitor_apply_forwards_lifecycle_and_lease_authority(
    tmp_path,
    monkeypatch,
) -> None:
    repo = tmp_path / "repo"
    repo.mkdir()
    worktree = tmp_path / "eligible"
    worktree.mkdir()
    registry_path = tmp_path / "agent-worktrees.json"
    registry_path.write_text(
        json.dumps(
            {
                "schema": agent_worktree.REGISTRY_SCHEMA,
                "worktrees": {
                    str(worktree.resolve()): {
                        "path": str(worktree.resolve()),
                        "branch": "codex/eligible",
                        "owner": "codex-4015",
                        "status": "complete",
                        "expires_at": 50,
                    }
                },
            }
        ),
        encoding="utf-8",
    )
    active_leases = [
        {
            "resource_id": f"worktree:{worktree.resolve()}",
            "execution_id": "active-owner",
            "expires_at": 200,
        }
    ]
    captured: dict[str, object] = {}

    def fake_apply(_cwd: Path, **kwargs):
        captured.update(kwargs)
        return {"mode": "apply", "ok": False, "errors": []}

    monkeypatch.setattr(git_hygiene, "janitor_apply", fake_apply)

    agent_worktree.janitor_apply(
        repo,
        registry_path=registry_path,
        pr_states={"codex/eligible": {"state": "MERGED"}},
        active_leases=active_leases,
    )

    assert captured["active_leases"] == active_leases
    records = captured["lifecycle_records"]
    assert isinstance(records, dict)
    assert records[str(worktree.resolve())]["status"] == "complete"


def test_janitor_apply_cli_requires_and_loads_lease_snapshot(
    tmp_path,
    monkeypatch,
    capsys,
) -> None:
    repo = tmp_path / "repo"
    repo.mkdir()
    registry_path = tmp_path / "agent-worktrees.json"
    registry_path.write_text(
        json.dumps(
            {
                "schema": agent_worktree.REGISTRY_SCHEMA,
                "worktrees": {},
            }
        ),
        encoding="utf-8",
    )
    pr_state_path = tmp_path / "pr-states.json"
    pr_state_path.write_text("{}\n", encoding="utf-8")
    lease_path = tmp_path / "leases.json"
    leases = [
        {
            "resource_id": "branch:codex/active",
            "execution_id": "active-owner",
            "expires_at": 200,
        }
    ]
    lease_path.write_text(json.dumps(leases), encoding="utf-8")
    captured: dict[str, object] = {}

    def fake_apply(_cwd: Path, **kwargs):
        captured.update(kwargs)
        return {"mode": "apply", "ok": True, "errors": []}

    monkeypatch.setattr(agent_worktree, "janitor_apply", fake_apply)
    common_args = [
        "--cwd",
        str(repo),
        "--registry-file",
        str(registry_path),
    ]

    assert (
        agent_worktree.main(
            [
                *common_args,
                "janitor",
                "--mode",
                "apply",
                "--pr-state-file",
                str(pr_state_path),
            ]
        )
        == 1
    )
    assert "janitor apply requires --lease-file" in capsys.readouterr().out

    assert (
        agent_worktree.main(
            [
                *common_args,
                "--lease-file",
                str(lease_path),
                "janitor",
                "--mode",
                "apply",
                "--pr-state-file",
                str(pr_state_path),
            ]
        )
        == 0
    )
    assert captured["active_leases"] == leases
