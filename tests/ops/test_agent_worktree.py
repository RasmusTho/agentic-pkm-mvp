from __future__ import annotations

import json
import subprocess
from subprocess import CompletedProcess
from pathlib import Path

from scripts import agent_worktree


def git(cwd: Path, *args: str) -> None:
    subprocess.run(["git", *args], cwd=cwd, check=True, capture_output=True, text=True)


def make_repo(tmp_path: Path) -> tuple[Path, Path]:
    repo = tmp_path / "repo"
    repo.mkdir()
    git(repo, "init", "-q")
    git(repo, "config", "user.email", "test@example.invalid")
    git(repo, "config", "user.name", "Test")
    (repo / "README").write_text("test\n")
    git(repo, "add", "README")
    git(repo, "commit", "-qm", "initial")
    linked = tmp_path / "worktree"
    git(repo, "worktree", "add", "-q", "-b", "test/agent", str(linked))
    return repo, linked


def test_register_verify_and_heartbeat(tmp_path: Path, monkeypatch) -> None:
    repo, linked = make_repo(tmp_path)
    monkeypatch.setenv("PKM_WORKTREE_REGISTRY", str(tmp_path / "registry.json"))
    args = agent_worktree.parser().parse_args(
        ["--cwd", str(repo), "register", "--path", str(linked), "--task-id", "issue-1", "--owner", "test"]
    )
    args.func(args)
    verify = agent_worktree.parser().parse_args(
        ["--cwd", str(repo), "verify", "--path", str(linked)]
    )
    assert verify.func(verify) == 0
    data = json.loads((tmp_path / "registry.json").read_text())
    assert data["worktrees"][str(linked.resolve())]["task_id"] == "issue-1"


def test_janitor_preserves_unregistered_and_dirty_worktrees(tmp_path: Path, monkeypatch, capsys) -> None:
    repo, linked = make_repo(tmp_path)
    monkeypatch.setenv("PKM_WORKTREE_REGISTRY", str(tmp_path / "registry.json"))
    data = {"schema_version": 1, "worktrees": {}}
    registry = tmp_path / "registry.json"
    registry.write_text(json.dumps(data))
    args = agent_worktree.parser().parse_args(["--cwd", str(repo), "janitor"])
    args.func(args)
    result = json.loads(capsys.readouterr().out)
    assert result["candidates"] == []
    assert result["preserved"][0]["reason"] == "unregistered"

    register = agent_worktree.parser().parse_args(
        ["--cwd", str(repo), "register", "--path", str(linked), "--task-id", "issue-2", "--owner", "test", "--ttl-hours", "1"]
    )
    register.func(register)
    capsys.readouterr()
    (linked / "dirty").write_text("keep\n")
    data = json.loads(registry.read_text())
    data["worktrees"][str(linked.resolve())]["expires_at"] = 0
    registry.write_text(json.dumps(data))
    args.func(args)
    result = json.loads(capsys.readouterr().out)
    assert result["candidates"] == []
    assert {item["reason"] for item in result["preserved"]} == {"unregistered", "dirty_worktree"}


def test_dispatcher_state_is_fail_closed(tmp_path: Path, monkeypatch) -> None:
    entry = {"task_id": "issue-1", "coordination_mode": "dispatcher-backed"}

    def unavailable(*_args, **_kwargs) -> CompletedProcess[str]:
        return CompletedProcess([], 1, "", "dispatcher unavailable")

    monkeypatch.setattr(agent_worktree.subprocess, "run", unavailable)
    assert agent_worktree.dispatcher_state(tmp_path, entry) == "unavailable"

    def active(*_args, **_kwargs) -> CompletedProcess[str]:
        return CompletedProcess(
            [],
            0,
            json.dumps(
                {"task": {"lease_id": "lease-1", "lease_expires_at": "2999-01-01T00:00:00Z"}}
            ),
            "",
        )

    monkeypatch.setattr(agent_worktree.subprocess, "run", active)
    assert agent_worktree.dispatcher_state(tmp_path, entry) == "active"
