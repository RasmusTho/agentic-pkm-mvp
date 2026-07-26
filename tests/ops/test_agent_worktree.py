from __future__ import annotations

import json
import os
import stat
import subprocess
import threading
from contextlib import nullcontext
from pathlib import Path

import pytest

from scripts import agent_worktree, git_hygiene


MISSING = object()
GENERATION = "a" * 32


def _allow_lifecycle_authority(_targets):
    return nullcontext(lambda: None)


def _reclaim_plan(worktree: Path, branch: str) -> dict[str, object]:
    return {
        "mode": "report",
        "remote_policy": "merged-and-closed-with-rescue",
        "destructive_actions": [],
        "candidates": {
            "local_branches": [],
            "worktrees": [],
            "orphaned_worktrees": [],
            "remote_branches": [],
            "remote_branches_requiring_rescue": [],
            "old_stashes": [],
        },
        "reclaimable_worktrees": [
            {
                "path": str(worktree),
                "branch": branch,
                "head": "candidate",
                "merge_proof": "merged_pr",
            }
        ],
        "orphaned_worktrees": [],
        "skipped": [],
        "prune_candidates": {"worktree": [], "remote": []},
        "active_leases_respected": [],
        "preservation_receipts": [],
    }


def _write_lifecycle_record(
    registry_path: Path,
    worktree: Path,
    *,
    branch: str = "codex/eligible",
    generation: str = GENERATION,
    status: str = "complete",
) -> None:
    record = {
        "path": str(worktree.resolve()),
        "branch": branch,
        "generation": generation,
        "owner": "active-owner",
        "status": status,
        "registered_at": 10,
        "heartbeat_at": 20,
        "expires_at": 30,
    }
    if status in {"released", "complete"}:
        record[f"{status}_at"] = 30
    registry_path.write_text(
        json.dumps(
            {
                "schema": agent_worktree.REGISTRY_SCHEMA,
                "worktrees": {str(worktree.resolve()): record},
            }
        ),
        encoding="utf-8",
    )


def _worktree_porcelain(
    repo: Path,
    worktree: Path,
    branch: str,
    *,
    head: str = "candidate",
) -> str:
    return (
        f"worktree {repo}\nHEAD root\nbranch refs/heads/main\n\n"
        f"worktree {worktree}\nHEAD {head}\nbranch refs/heads/{branch}\n\n"
    )


def test_registry_write_fsyncs_parent_directory_after_replace(
    tmp_path,
    monkeypatch,
) -> None:
    registry_path = tmp_path / "agent-worktrees.json"
    events: list[str] = []
    real_replace = os.replace

    def tracked_fsync(descriptor: int) -> None:
        mode = os.fstat(descriptor).st_mode
        events.append("directory_fsync" if stat.S_ISDIR(mode) else "file_fsync")

    def tracked_replace(source, destination) -> None:
        events.append("replace")
        real_replace(source, destination)

    monkeypatch.setattr(os, "fsync", tracked_fsync)
    monkeypatch.setattr(os, "replace", tracked_replace)

    agent_worktree._write_registry(
        registry_path,
        {"schema": agent_worktree.REGISTRY_SCHEMA, "worktrees": {}},
    )

    assert events == ["file_fsync", "replace", "directory_fsync"]


def test_registration_generation_does_not_replay_after_worktree_recreation(
    tmp_path,
) -> None:
    repo = tmp_path / "repo"
    subprocess.run(["git", "init", "--initial-branch=main", repo], check=True)
    subprocess.run(
        ["git", "config", "user.email", "test@example.com"],
        cwd=repo,
        check=True,
    )
    subprocess.run(
        ["git", "config", "user.name", "Test User"],
        cwd=repo,
        check=True,
    )
    (repo / "base.txt").write_text("base\n", encoding="utf-8")
    subprocess.run(["git", "add", "base.txt"], cwd=repo, check=True)
    subprocess.run(["git", "commit", "-m", "base"], cwd=repo, check=True)
    subprocess.run(["git", "branch", "codex/eligible"], cwd=repo, check=True)
    worktree = tmp_path / "eligible"
    subprocess.run(
        ["git", "worktree", "add", str(worktree), "codex/eligible"],
        cwd=repo,
        check=True,
    )
    registry_path = tmp_path / "agent-worktrees.json"

    registered = agent_worktree.register_worktree(
        repo,
        worktree=worktree,
        owner="active-owner",
        registry_path=registry_path,
        now=10,
    )
    completed = agent_worktree.complete_worktree(
        repo,
        worktree=worktree,
        owner="active-owner",
        registry_path=registry_path,
        now=20,
    )
    marker = Path(
        git_hygiene.run_git(
            [
                "-C",
                str(worktree),
                "rev-parse",
                "--git-path",
                agent_worktree.GENERATION_MARKER,
            ],
            repo,
        )
    )
    assert marker.read_text(encoding="utf-8").strip() == registered["generation"]

    subprocess.run(
        ["git", "worktree", "remove", str(worktree)],
        cwd=repo,
        check=True,
    )
    subprocess.run(
        ["git", "worktree", "add", str(worktree), "codex/eligible"],
        cwd=repo,
        check=True,
    )
    new_marker = Path(
        git_hygiene.run_git(
            [
                "-C",
                str(worktree),
                "rev-parse",
                "--git-path",
                agent_worktree.GENERATION_MARKER,
            ],
            repo,
        )
    )
    assert not new_marker.exists()
    planning_records = agent_worktree._bind_live_generations(
        repo,
        {str(worktree.resolve()): completed},
    )
    assert (
        git_hygiene._worktree_lifecycle_skip_reason(
            str(worktree),
            "codex/eligible",
            planning_records,
            now=30,
        )
        == "registration_mismatch"
    )


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
    monkeypatch.setattr(
        agent_worktree,
        "_worktree_generation",
        lambda _cwd, _worktree, *, create: GENERATION,
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


@pytest.mark.parametrize("status", ("active", "released", "complete"))
def test_existing_lifecycle_record_migrates_generation_before_update(
    tmp_path,
    monkeypatch,
    status,
) -> None:
    repo = tmp_path / "repo"
    repo.mkdir()
    worktree = tmp_path / "issue-4015"
    worktree.mkdir()
    registry_path = tmp_path / "agent-worktrees.json"
    _write_lifecycle_record(registry_path, worktree, status=status)
    payload = json.loads(registry_path.read_text(encoding="utf-8"))
    payload["worktrees"][str(worktree.resolve())].pop("generation")
    registry_path.write_text(json.dumps(payload), encoding="utf-8")
    create_values: list[bool] = []

    monkeypatch.setattr(
        agent_worktree,
        "_worktree_identity",
        lambda _cwd, _worktree: (worktree.resolve(), "codex/eligible"),
    )

    def generation(_cwd: Path, _worktree: Path, *, create: bool) -> str:
        create_values.append(create)
        return GENERATION

    monkeypatch.setattr(agent_worktree, "_worktree_generation", generation)

    if status == "active":
        updated = agent_worktree.heartbeat_worktree(
            repo,
            worktree=worktree,
            owner="active-owner",
            registry_path=registry_path,
            now=40,
        )
    else:
        updated = agent_worktree.complete_worktree(
            repo,
            worktree=worktree,
            owner="active-owner",
            registry_path=registry_path,
            now=40,
        )

    assert create_values == [True]
    assert updated["generation"] == GENERATION
    persisted = agent_worktree.load_lifecycle_records(
        repo,
        registry_path=registry_path,
    )[str(worktree.resolve())]
    assert persisted["generation"] == GENERATION


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
    monkeypatch.setattr(
        agent_worktree,
        "_worktree_generation",
        lambda _cwd, _worktree, *, create: GENERATION,
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


@pytest.mark.parametrize(
    "malformed_expiry",
    (True, float("nan"), float("inf"), float("-inf")),
)
def test_lifecycle_registration_does_not_treat_malformed_expiry_as_abandoned(
    tmp_path,
    monkeypatch,
    malformed_expiry,
) -> None:
    repo = tmp_path / "repo"
    repo.mkdir()
    worktree = tmp_path / "issue-4015"
    worktree.mkdir()
    registry_path = tmp_path / "agent-worktrees.json"
    registry_path.write_text(
        json.dumps(
            {
                "schema": agent_worktree.REGISTRY_SCHEMA,
                "worktrees": {
                    str(worktree.resolve()): {
                        "path": str(worktree.resolve()),
                        "branch": "codex/issue-4015",
                        "generation": GENERATION,
                        "owner": "first-owner",
                        "status": "active",
                        "registered_at": 10,
                        "heartbeat_at": 20,
                        "expires_at": malformed_expiry,
                    }
                },
            }
        ),
        encoding="utf-8",
    )
    monkeypatch.setattr(
        agent_worktree,
        "_worktree_identity",
        lambda _cwd, _worktree: (worktree.resolve(), "codex/issue-4015"),
    )
    monkeypatch.setattr(
        agent_worktree,
        "_worktree_generation",
        lambda _cwd, _worktree, *, create: GENERATION,
    )

    with pytest.raises(
        agent_worktree.WorktreeLifecycleError,
        match="active lifecycle owner",
    ):
        agent_worktree.register_worktree(
            repo,
            worktree=worktree,
            owner="second-owner",
            registry_path=registry_path,
            now=100,
        )


@pytest.mark.parametrize(
    ("field", "value"),
    (
        ("owner", MISSING),
        ("owner", ""),
        ("owner", "   "),
        ("generation", MISSING),
        ("generation", "not-a-generation"),
        ("registered_at", MISSING),
        ("registered_at", True),
        ("registered_at", float("nan")),
        ("heartbeat_at", MISSING),
        ("heartbeat_at", float("inf")),
        ("expires_at", True),
        ("expires_at", float("nan")),
        ("expires_at", float("-inf")),
    ),
)
def test_janitor_rejects_malformed_lifecycle_authority(field, value) -> None:
    worktree = Path("/repo/worktrees/issue-4015")
    record = {
        "path": str(worktree),
        "branch": "codex/issue-4015",
        "generation": GENERATION,
        "owner": "codex-4015",
        "status": "active",
        "registered_at": 10,
        "heartbeat_at": 20,
        "expires_at": 30,
    }
    if value is MISSING:
        record.pop(field)
    else:
        record[field] = value

    reason = git_hygiene._worktree_lifecycle_skip_reason(
        str(worktree),
        "codex/issue-4015",
        {str(worktree): record},
        now=40,
    )

    assert reason == "registration_mismatch"


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
            "generation": GENERATION,
            "owner": "active-owner",
            "status": "active",
            "registered_at": 10,
            "heartbeat_at": 20,
            "expires_at": 200,
        },
        str(locked.resolve()): {
            "path": str(locked.resolve()),
            "branch": "codex/locked",
            "generation": GENERATION,
            "owner": "locked-owner",
            "status": "released",
            "registered_at": 10,
            "heartbeat_at": 20,
            "released_at": 50,
            "expires_at": 50,
        },
        str(dirty.resolve()): {
            "path": str(dirty.resolve()),
            "branch": "codex/dirty",
            "generation": GENERATION,
            "owner": "dirty-owner",
            "status": "released",
            "registered_at": 10,
            "heartbeat_at": 20,
            "released_at": 50,
            "expires_at": 50,
        },
        str(eligible.resolve()): {
            "path": str(eligible.resolve()),
            "branch": "codex/eligible",
            "generation": GENERATION,
            "owner": "eligible-owner",
            "status": "complete",
            "registered_at": 10,
            "heartbeat_at": 20,
            "complete_at": 50,
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
            "head": "e",
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
        active_lease_loader=lambda: [],
        lifecycle_authority_guard=_allow_lifecycle_authority,
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
                        "generation": GENERATION,
                        "owner": "codex-4015",
                        "status": "complete",
                        "registered_at": 10,
                        "heartbeat_at": 20,
                        "complete_at": 50,
                        "expires_at": 50,
                    }
                },
            }
        ),
        encoding="utf-8",
    )
    authoritative_leases = [
        {
            "resource_id": f"worktree:{worktree.resolve()}",
            "execution_id": "active-owner",
            "expires_at": 200,
        }
    ]
    lease_path = tmp_path / "leases.json"
    lease_path.write_text(json.dumps(authoritative_leases), encoding="utf-8")
    captured: dict[str, object] = {}

    def fake_apply(_cwd: Path, **kwargs):
        captured.update(kwargs)
        captured["loaded_leases"] = kwargs["active_lease_loader"]()
        return {"mode": "apply", "ok": False, "errors": []}

    monkeypatch.setattr(git_hygiene, "janitor_apply", fake_apply)
    monkeypatch.setattr(
        agent_worktree,
        "_worktree_generation",
        lambda _cwd, _worktree, *, create: GENERATION,
    )
    monkeypatch.setattr(
        git_hygiene,
        "run_git",
        lambda args, _cwd: (
            _worktree_porcelain(repo, worktree, "codex/eligible")
            if args == ["worktree", "list", "--porcelain"]
            else ""
        ),
    )

    agent_worktree.janitor_apply(
        repo,
        registry_path=registry_path,
        pr_states={"codex/eligible": {"state": "MERGED"}},
        lease_path=lease_path,
    )

    assert captured["loaded_leases"] == authoritative_leases
    records = captured["lifecycle_records"]
    assert isinstance(records, dict)
    assert records[str(worktree.resolve())]["status"] == "complete"
    lifecycle_guard = captured["lifecycle_authority_guard"]
    assert callable(lifecycle_guard)


def test_janitor_apply_allows_heartbeat_during_fetch_and_rechecks_before_remove(
    tmp_path,
    monkeypatch,
) -> None:
    repo = tmp_path / "repo"
    repo.mkdir()
    worktree = tmp_path / "eligible"
    worktree.mkdir()
    registry_path = tmp_path / "agent-worktrees.json"
    lease_path = tmp_path / "leases.json"
    lease_path.write_text("[]\n", encoding="utf-8")
    registry_path.write_text(
        json.dumps(
            {
                "schema": agent_worktree.REGISTRY_SCHEMA,
                "worktrees": {
                    str(worktree.resolve()): {
                        "path": str(worktree.resolve()),
                        "branch": "codex/eligible",
                        "generation": GENERATION,
                        "owner": "active-owner",
                        "status": "active",
                        "registered_at": 10,
                        "heartbeat_at": 20,
                        "expires_at": 30,
                    }
                },
            }
        ),
        encoding="utf-8",
    )
    monkeypatch.setattr(
        agent_worktree,
        "_worktree_identity",
        lambda _cwd, _worktree: (worktree.resolve(), "codex/eligible"),
    )
    monkeypatch.setattr(
        agent_worktree,
        "_worktree_generation",
        lambda _cwd, _worktree, *, create: GENERATION,
    )
    monkeypatch.setattr(git_hygiene, "_worktree_dirty", lambda _path: False)
    def fake_run_git(args: list[str], _cwd: Path) -> str:
        if args == ["worktree", "list", "--porcelain"]:
            return _worktree_porcelain(repo, worktree, "codex/eligible")
        raise AssertionError(f"unexpected git command: {args}")

    monkeypatch.setattr(git_hygiene, "run_git", fake_run_git)
    commands: list[list[str]] = []
    heartbeat_finished = threading.Event()
    heartbeat_errors: list[BaseException] = []

    def renew_during_fetch() -> None:
        try:
            agent_worktree.heartbeat_worktree(
                repo,
                worktree=worktree,
                owner="active-owner",
                ttl_seconds=1000,
                registry_path=registry_path,
                now=3_000_000_000,
            )
        except BaseException as exc:  # pragma: no cover - surfaced below
            heartbeat_errors.append(exc)
        finally:
            heartbeat_finished.set()

    def fake_run_git_result(args: list[str], _cwd: Path):
        commands.append(args)
        if args == ["fetch", "--prune", "origin"]:
            heartbeat = threading.Thread(target=renew_during_fetch)
            heartbeat.start()
            assert heartbeat_finished.wait(1), "janitor blocked the active owner heartbeat"
            heartbeat.join()
        return subprocess.CompletedProcess(["git", *args], 0, "", "")

    monkeypatch.setattr(git_hygiene, "run_git_result", fake_run_git_result)
    monkeypatch.setattr(
        git_hygiene,
        "build_janitor_plan",
        lambda *_args, **_kwargs: _reclaim_plan(worktree, "codex/eligible"),
    )

    report = agent_worktree.janitor_apply(
        repo,
        registry_path=registry_path,
        pr_states={"codex/eligible": {"state": "MERGED"}},
        lease_path=lease_path,
    )

    assert heartbeat_errors == []
    assert report["ok"] is False
    assert report["errors"][0]["reason"] == "lifecycle_authority_changed"
    assert commands == [["fetch", "--prune", "origin"]]
    records = agent_worktree.load_lifecycle_records(
        repo,
        registry_path=registry_path,
    )
    assert records[str(worktree.resolve())]["expires_at"] == 3_000_001_000


@pytest.mark.parametrize(
    ("live_branch", "live_generation", "live_head"),
    (
        ("codex/reused", GENERATION, "candidate"),
        ("codex/eligible", "b" * 32, "candidate"),
        ("codex/eligible", GENERATION, "replacement"),
    ),
)
def test_janitor_rechecks_live_checkout_identity_and_generation_before_remove(
    tmp_path,
    monkeypatch,
    live_branch,
    live_generation,
    live_head,
) -> None:
    repo = tmp_path / "repo"
    repo.mkdir()
    worktree = tmp_path / "eligible"
    worktree.mkdir()
    registry_path = tmp_path / "agent-worktrees.json"
    lease_path = tmp_path / "leases.json"
    lease_path.write_text("[]\n", encoding="utf-8")
    _write_lifecycle_record(registry_path, worktree)
    commands: list[list[str]] = []

    monkeypatch.setattr(
        agent_worktree,
        "_worktree_identity",
        lambda _cwd, _worktree: (worktree.resolve(), live_branch),
    )
    monkeypatch.setattr(
        agent_worktree,
        "_worktree_generation",
        lambda _cwd, _worktree, *, create: live_generation,
    )
    monkeypatch.setattr(git_hygiene, "_worktree_dirty", lambda _path: False)
    monkeypatch.setattr(
        git_hygiene,
        "run_git",
        lambda args, _cwd: (
            _worktree_porcelain(
                repo,
                worktree,
                "codex/eligible",
                head=live_head,
            )
            if args == ["worktree", "list", "--porcelain"]
            else ""
        ),
    )
    monkeypatch.setattr(
        git_hygiene,
        "build_janitor_plan",
        lambda *_args, **_kwargs: _reclaim_plan(worktree, "codex/eligible"),
    )
    monkeypatch.setattr(
        git_hygiene,
        "run_git_result",
        lambda args, _cwd: (
            commands.append(args)
            or subprocess.CompletedProcess(["git", *args], 0, "", "")
        ),
    )

    report = agent_worktree.janitor_apply(
        repo,
        registry_path=registry_path,
        pr_states={"codex/eligible": {"state": "MERGED"}},
        lease_path=lease_path,
    )

    assert report["ok"] is False
    assert report["errors"][0]["reason"] == "lifecycle_authority_changed"
    assert commands == [["fetch", "--prune", "origin"]]


@pytest.mark.parametrize("boundary_change", ("dirty", "locked", "shared_root"))
def test_janitor_preserves_target_when_checkout_changes_at_remove_boundary(
    tmp_path,
    monkeypatch,
    boundary_change,
) -> None:
    repo = tmp_path / "repo"
    repo.mkdir()
    worktree = tmp_path / "eligible"
    worktree.mkdir()
    registry_path = tmp_path / "agent-worktrees.json"
    lease_path = tmp_path / "leases.json"
    lease_path.write_text("[]\n", encoding="utf-8")
    _write_lifecycle_record(registry_path, worktree)
    commands: list[list[str]] = []

    monkeypatch.setattr(
        agent_worktree,
        "_worktree_identity",
        lambda _cwd, _worktree: (
            repo.resolve() if boundary_change == "shared_root" else worktree.resolve(),
            "codex/eligible",
        ),
    )
    monkeypatch.setattr(
        agent_worktree,
        "_worktree_generation",
        lambda _cwd, _worktree, *, create: GENERATION,
    )
    monkeypatch.setattr(
        git_hygiene,
        "_worktree_dirty",
        lambda _path: boundary_change == "dirty",
    )

    def live_worktrees(args: list[str], _cwd: Path) -> str:
        if args != ["worktree", "list", "--porcelain"]:
            raise AssertionError(f"unexpected git command: {args}")
        result = _worktree_porcelain(repo, worktree, "codex/eligible")
        if boundary_change == "locked":
            return result.rstrip() + "\nlocked session\n\n"
        return result

    monkeypatch.setattr(git_hygiene, "run_git", live_worktrees)
    monkeypatch.setattr(
        git_hygiene,
        "build_janitor_plan",
        lambda *_args, **_kwargs: _reclaim_plan(worktree, "codex/eligible"),
    )
    monkeypatch.setattr(
        git_hygiene,
        "run_git_result",
        lambda args, _cwd: (
            commands.append(args)
            or subprocess.CompletedProcess(["git", *args], 0, "", "")
        ),
    )

    report = agent_worktree.janitor_apply(
        repo,
        registry_path=registry_path,
        pr_states={"codex/eligible": {"state": "MERGED"}},
        lease_path=lease_path,
    )

    assert report["ok"] is False
    assert report["errors"][0]["reason"] == "lifecycle_authority_changed"
    assert commands == [["fetch", "--prune", "origin"]]


def test_janitor_wins_boundary_blocks_heartbeat_and_retires_generation(
    tmp_path,
    monkeypatch,
) -> None:
    repo = tmp_path / "repo"
    repo.mkdir()
    worktree = tmp_path / "eligible"
    worktree.mkdir()
    registry_path = tmp_path / "agent-worktrees.json"
    lease_path = tmp_path / "leases.json"
    lease_path.write_text("[]\n", encoding="utf-8")
    _write_lifecycle_record(
        registry_path,
        worktree,
        status="active",
    )
    remove_started = threading.Event()
    allow_remove = threading.Event()
    heartbeat_finished = threading.Event()
    removed = False
    live_generation = GENERATION
    remove_calls = 0
    janitor_reports: list[dict[str, object]] = []
    heartbeat_errors: list[BaseException] = []

    def live_identity(_cwd: Path, _worktree: Path):
        if removed:
            raise agent_worktree.WorktreeLifecycleError(
                "worktree is not registered with git"
            )
        return worktree.resolve(), "codex/eligible"

    def fake_run_git(args: list[str], _cwd: Path) -> str:
        if args == ["worktree", "list", "--porcelain"]:
            return _worktree_porcelain(repo, worktree, "codex/eligible")
        raise AssertionError(f"unexpected git command: {args}")

    def fake_run_git_result(args: list[str], _cwd: Path):
        nonlocal removed, remove_calls
        if args == ["worktree", "remove", str(worktree)]:
            remove_calls += 1
            remove_started.set()
            assert allow_remove.wait(1)
            removed = True
        return subprocess.CompletedProcess(["git", *args], 0, "", "")

    monkeypatch.setattr(agent_worktree, "_worktree_identity", live_identity)
    monkeypatch.setattr(
        agent_worktree,
        "_worktree_generation",
        lambda _cwd, _worktree, *, create: live_generation,
    )
    monkeypatch.setattr(git_hygiene, "_worktree_dirty", lambda _path: False)
    monkeypatch.setattr(git_hygiene, "run_git", fake_run_git)
    monkeypatch.setattr(git_hygiene, "run_git_result", fake_run_git_result)
    monkeypatch.setattr(
        git_hygiene,
        "build_janitor_plan",
        lambda *_args, **_kwargs: _reclaim_plan(worktree, "codex/eligible"),
    )

    def run_janitor() -> None:
        janitor_reports.append(
            agent_worktree.janitor_apply(
                repo,
                registry_path=registry_path,
                pr_states={"codex/eligible": {"state": "MERGED"}},
                lease_path=lease_path,
            )
        )

    def run_heartbeat() -> None:
        try:
            agent_worktree.heartbeat_worktree(
                repo,
                worktree=worktree,
                owner="active-owner",
                registry_path=registry_path,
                now=3_000_000_000,
            )
        except BaseException as exc:  # pragma: no cover - surfaced below
            heartbeat_errors.append(exc)
        finally:
            heartbeat_finished.set()

    janitor = threading.Thread(target=run_janitor)
    janitor.start()
    assert remove_started.wait(1)
    heartbeat = threading.Thread(target=run_heartbeat)
    heartbeat.start()
    assert not heartbeat_finished.wait(0.1)
    allow_remove.set()
    janitor.join()
    heartbeat.join()

    assert janitor_reports[0]["ok"] is True
    assert len(heartbeat_errors) == 1
    assert isinstance(heartbeat_errors[0], agent_worktree.WorktreeLifecycleError)
    record = agent_worktree.load_lifecycle_records(
        repo,
        registry_path=registry_path,
    )[str(worktree.resolve())]
    assert record["status"] == "removed"
    assert record["generation"] == GENERATION

    removed = False
    live_generation = "b" * 32
    replay = agent_worktree.janitor_apply(
        repo,
        registry_path=registry_path,
        pr_states={"codex/eligible": {"state": "MERGED"}},
        lease_path=lease_path,
    )
    assert replay["ok"] is False
    assert replay["errors"][0]["reason"] == "lifecycle_authority_changed"
    assert remove_calls == 1


def test_janitor_restart_reconciles_removed_generation_idempotently(
    tmp_path,
    monkeypatch,
) -> None:
    repo = tmp_path / "repo"
    repo.mkdir()
    worktree = tmp_path / "removed"
    registry_path = tmp_path / "agent-worktrees.json"
    lease_path = tmp_path / "leases.json"
    lease_path.write_text("[]\n", encoding="utf-8")
    _write_lifecycle_record(registry_path, worktree)
    captured_statuses: list[str] = []

    monkeypatch.setattr(
        git_hygiene,
        "run_git",
        lambda args, _cwd: (
            f"worktree {repo}\nHEAD root\nbranch refs/heads/main\n\n"
            if args == ["worktree", "list", "--porcelain"]
            else ""
        ),
    )
    monkeypatch.setattr(
        agent_worktree,
        "_worktree_generation",
        lambda _cwd, _worktree, *, create: (
            (_ for _ in ()).throw(
                agent_worktree.WorktreeLifecycleError(
                    "worktree generation marker is missing"
                )
            )
        ),
    )

    def fake_apply(_cwd: Path, **kwargs):
        captured_statuses.append(
            kwargs["lifecycle_records"][str(worktree.resolve())]["status"]
        )
        return {"mode": "apply", "ok": True, "errors": []}

    monkeypatch.setattr(git_hygiene, "janitor_apply", fake_apply)

    agent_worktree.janitor_apply(
        repo,
        registry_path=registry_path,
        pr_states={},
        lease_path=lease_path,
    )
    first_payload = registry_path.read_bytes()
    first_record = agent_worktree.load_lifecycle_records(
        repo,
        registry_path=registry_path,
    )[str(worktree.resolve())]
    agent_worktree.janitor_apply(
        repo,
        registry_path=registry_path,
        pr_states={},
        lease_path=lease_path,
    )

    assert captured_statuses == ["removed", "removed"]
    assert first_record["status"] == "removed"
    assert first_record["generation"] == GENERATION
    assert "removed_at" in first_record
    assert registry_path.read_bytes() == first_payload


def test_janitor_does_not_delete_branch_until_retirement_is_durable(
    tmp_path,
    monkeypatch,
) -> None:
    repo = tmp_path / "repo"
    repo.mkdir()
    worktree = tmp_path / "eligible"
    worktree.mkdir()
    registry_path = tmp_path / "agent-worktrees.json"
    lease_path = tmp_path / "leases.json"
    lease_path.write_text("[]\n", encoding="utf-8")
    _write_lifecycle_record(registry_path, worktree)
    commands: list[list[str]] = []
    real_write_registry = agent_worktree._write_registry

    monkeypatch.setattr(
        agent_worktree,
        "_worktree_identity",
        lambda _cwd, _worktree: (worktree.resolve(), "codex/eligible"),
    )
    monkeypatch.setattr(
        agent_worktree,
        "_worktree_generation",
        lambda _cwd, _worktree, *, create: GENERATION,
    )
    monkeypatch.setattr(git_hygiene, "_worktree_dirty", lambda _path: False)
    monkeypatch.setattr(
        git_hygiene,
        "run_git",
        lambda args, _cwd: (
            _worktree_porcelain(repo, worktree, "codex/eligible")
            if args == ["worktree", "list", "--porcelain"]
            else ""
        ),
    )
    monkeypatch.setattr(
        git_hygiene,
        "build_janitor_plan",
        lambda *_args, **_kwargs: _reclaim_plan(worktree, "codex/eligible"),
    )
    monkeypatch.setattr(
        git_hygiene,
        "run_git_result",
        lambda args, _cwd: (
            commands.append(args)
            or subprocess.CompletedProcess(["git", *args], 0, "", "")
        ),
    )

    def fail_retirement_write(path: Path, payload: dict[str, object]) -> None:
        record = payload["worktrees"][str(worktree.resolve())]
        if record.get("status") == "removed":
            raise OSError("simulated durable retirement failure")
        real_write_registry(path, payload)

    monkeypatch.setattr(agent_worktree, "_write_registry", fail_retirement_write)

    report = agent_worktree.janitor_apply(
        repo,
        registry_path=registry_path,
        pr_states={"codex/eligible": {"state": "MERGED"}},
        lease_path=lease_path,
    )

    assert report["ok"] is False
    assert report["errors"][0]["reason"] == "lifecycle_authority_changed"
    assert commands == [
        ["fetch", "--prune", "origin"],
        ["worktree", "remove", str(worktree)],
    ]
    record = agent_worktree.load_lifecycle_records(
        repo,
        registry_path=registry_path,
    )[str(worktree.resolve())]
    assert record["status"] == "complete"


def test_janitor_restart_fails_closed_when_git_state_is_unavailable(
    tmp_path,
    monkeypatch,
) -> None:
    repo = tmp_path / "repo"
    repo.mkdir()
    worktree = tmp_path / "eligible"
    registry_path = tmp_path / "agent-worktrees.json"
    lease_path = tmp_path / "leases.json"
    lease_path.write_text("[]\n", encoding="utf-8")
    _write_lifecycle_record(registry_path, worktree)
    core_called = False

    def unavailable(_args: list[str], _cwd: Path) -> str:
        raise subprocess.CalledProcessError(1, ["git", "worktree", "list"])

    def fake_apply(_cwd: Path, **_kwargs):
        nonlocal core_called
        core_called = True
        return {}

    monkeypatch.setattr(git_hygiene, "run_git", unavailable)
    monkeypatch.setattr(git_hygiene, "janitor_apply", fake_apply)

    with pytest.raises(subprocess.CalledProcessError):
        agent_worktree.janitor_apply(
            repo,
            registry_path=registry_path,
            pr_states={},
            lease_path=lease_path,
        )

    assert core_called is False


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
    assert captured["lease_path"] == lease_path.resolve()
