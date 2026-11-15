from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

from scripts import agent_worktree


SOURCE = Path(__file__).resolve().parents[2]
OWNER = "retained-local-owner"
BRANCH = "codex/retained-local-candidate"


def _git(cwd: Path, *args: str) -> str:
    return subprocess.run(
        ["git", "-c", "core.hooksPath=/dev/null", "-c", "commit.gpgsign=false", *args],
        cwd=cwd, check=True, capture_output=True, text=True,
    ).stdout.strip()


@pytest.fixture
def retained(tmp_path: Path):
    repo = tmp_path / "repo"
    repo.mkdir()
    _git(repo, "init", "--initial-branch=main")
    _git(repo, "config", "user.name", "Recovery Fixture")
    _git(repo, "config", "user.email", "fixture@example.invalid")
    (repo / "base.txt").write_text("base\n")
    (repo / ".gitignore").write_text("ignored-private\n")
    _git(repo, "add", ".")
    _git(repo, "commit", "-m", "fixture base")
    worktree = tmp_path / "worker"
    _git(repo, "worktree", "add", "-b", BRANCH, str(worktree))
    (worktree / "committed.py").write_text("unpublished = True\n")
    _git(worktree, "add", "committed.py")
    _git(worktree, "commit", "-m", "unpublished fixture candidate")
    registration = agent_worktree.register_worktree(repo, worktree=worktree, owner=OWNER, now=10, ttl_seconds=1)
    head = _git(worktree, "rev-parse", "HEAD")
    return repo, worktree, registration, head


def _report(retained, **overrides):
    repo, worktree, registration, head = retained
    arguments = {"worktree": worktree, "owner": OWNER, "branch": BRANCH,
                 "generation": registration["generation"], "expected_head": head}
    arguments.update(overrides)
    return agent_worktree.recovery_report(repo, **arguments)


def _cli(retained):
    repo, worktree, registration, head = retained
    return subprocess.run(
        [sys.executable, "-B", str(SOURCE / "scripts/agent_worktree.py"), "--cwd", str(repo),
         "recovery-report", "--worktree", str(worktree), "--owner", OWNER, "--branch", BRANCH,
         "--generation", registration["generation"], "--expected-head", head],
        cwd=repo, capture_output=True, text=True, timeout=30,
    )


@pytest.mark.parametrize("dirty", [False, True])
def test_recovery_cli_binds_candidate_without_writes(retained, dirty):
    repo, worktree, registration, head = retained
    if dirty:
        (worktree / "base.txt").write_text("staged content must not be printed\n")
        _git(worktree, "add", "base.txt")
        (worktree / "base.txt").write_text("unstaged content must not be printed\n")
        (worktree / "local.py").write_text("untracked content must not be printed\n")
    (worktree / "ignored-private").write_text("private content must not be read or printed\n")
    registry = agent_worktree._default_registry_path(repo)
    payload = json.loads(registry.read_text())
    payload["worktrees"][str(worktree)]["unrecognized_private_field"] = "do not emit this value"
    registry.write_text(json.dumps(payload))
    trap = repo / "helper-ran"
    helper = repo / "fsmonitor-helper"
    helper.write_text(f"#!/bin/sh\ntouch '{trap}'\n")
    helper.chmod(0o700)
    _git(repo, "config", "core.fsmonitor", str(helper))
    index = Path(_git(worktree, "rev-parse", "--git-path", "index"))
    before_index = index.read_bytes()
    before_registry = registry.read_bytes()
    before_objects = sorted(str(p.relative_to(repo / ".git")) for p in (repo / ".git/objects").rglob("*"))
    result = _cli(retained)
    assert result.returncode == 0, result.stdout + result.stderr
    report = json.loads(result.stdout)
    assert report["authority"] == "observation-only"
    assert report["ownership_transferred"] is False
    assert report["writer_absence"] == "not-proven"
    assert report["process_closure"] == "unknown"
    assert report["preservation_backup"] is False
    assert report["registration"]["owner"] == OWNER
    assert report["registration"]["generation"] == registration["generation"]
    assert report["registration"]["expires_at"] == 11  # Expiry was not renewed.
    assert report["candidate"]["head"] == head
    assert len(report["candidate"]["index_flags_sha256"]) == 64
    assert report["candidate"]["clean"] is not dirty
    assert len(report["candidate_sha256"]) == 64
    assert "must not" not in result.stdout
    assert "ignored-private" not in result.stdout
    assert "do not emit this value" not in result.stdout
    assert registry.read_bytes() == before_registry
    assert index.read_bytes() == before_index
    assert not trap.exists()
    assert sorted(str(p.relative_to(repo / ".git")) for p in (repo / ".git/objects").rglob("*")) == before_objects
    assert _git(worktree, "rev-parse", "HEAD") == head
    if dirty:
        assert {entry["path"]: entry["status"] for entry in report["candidate"]["files"]} == {
            "base.txt": "MM", "local.py": "??"}
        (worktree / "local.py").write_text("changed untracked content\n")
        changed = json.loads(_cli(retained).stdout)
        assert changed["candidate_sha256"] != report["candidate_sha256"]
        _git(worktree, "add", "base.txt")
        staged = json.loads(_cli(retained).stdout)
        assert staged["candidate"]["index_sha256"] != changed["candidate"]["index_sha256"]
        assert staged["candidate_sha256"] != changed["candidate_sha256"]
        assert staged["candidate"]["head"] == head


@pytest.mark.parametrize("change", ["owner", "branch", "generation", "head", "bytes", "registry"])
def test_recovery_report_refuses_drift(retained, monkeypatch, change):
    repo, worktree, registration, _head = retained
    if change in {"owner", "branch", "generation", "head"}:
        key = "expected_head" if change == "head" else change
        value = "0" * 40 if change == "head" else ("0" * 32 if change == "generation" else "foreign")
        with pytest.raises(agent_worktree.WorktreeLifecycleError):
            _report(retained, **{key: value})
        return
    (worktree / "base.txt").write_text("first candidate\n")
    original = agent_worktree._recovery_candidate
    calls = 0

    def changed_candidate(*args):
        nonlocal calls
        calls += 1
        result = original(*args)
        if calls == 1:
            if change == "bytes":
                (worktree / "base.txt").write_text("other candidate\n")
            else:
                registry = agent_worktree._default_registry_path(repo)
                payload = json.loads(registry.read_text())
                payload["worktrees"][str(worktree)]["heartbeat_at"] = registration["heartbeat_at"] + 0.5
                registry.write_text(json.dumps(payload))
        return result

    monkeypatch.setattr(agent_worktree, "_recovery_candidate", changed_candidate)
    with pytest.raises(agent_worktree.WorktreeLifecycleError, match="changed"):
        _report(retained)


@pytest.mark.parametrize("case", ["symlink", "fifo", "hardlink", "aggregate", "count", "git-bytes", "ignored", "malformed", "missing"])
def test_recovery_report_bounds_and_exclusions(retained, monkeypatch, case):
    repo, worktree, _registration, _head = retained
    if case == "ignored":
        (worktree / "ignored-private").write_bytes(b"secret" * 100)
        monkeypatch.setattr(agent_worktree, "RECOVERY_MAX_CONTENT_BYTES", 0)
        assert _report(retained)["candidate"]["files"] == []
        return
    if case == "symlink":
        target = repo / "private-target"
        target.write_text("never traverse this input")
        (worktree / "local").symlink_to(target)
    elif case == "fifo":
        # An untracked FIFO is not a Git candidate. A tracked path replaced by a FIFO is.
        (worktree / "base.txt").unlink()
        os.mkfifo(worktree / "base.txt")
    elif case == "hardlink":
        os.link(worktree / "base.txt", worktree / "linked")
    elif case == "aggregate":
        (worktree / "base.txt").write_text("too large")
        monkeypatch.setattr(agent_worktree, "RECOVERY_MAX_CONTENT_BYTES", 1)
        def no_content_hash(*_args, **_kwargs):
            raise AssertionError("aggregate validation must precede content hashing")
        monkeypatch.setattr(agent_worktree.hashlib, "sha256", no_content_hash)
    elif case == "count":
        (worktree / "first").write_text("first")
        (worktree / "second").write_text("second")
        monkeypatch.setattr(agent_worktree, "RECOVERY_MAX_FILES", 1)
    elif case == "git-bytes":
        monkeypatch.setattr(agent_worktree, "RECOVERY_MAX_GIT_BYTES", 1)
        with pytest.raises(agent_worktree.WorktreeLifecycleError, match="byte bound"):
            agent_worktree._recovery_git(worktree, "rev-parse", "HEAD")
        return
    else:
        registry = agent_worktree._default_registry_path(repo)
        if case == "malformed":
            registry.write_text("not json")
        else:
            registry.unlink()
    with pytest.raises(agent_worktree.WorktreeLifecycleError):
        _report(retained)
    if case == "missing":
        assert not agent_worktree._default_registry_path(repo).exists()


def test_recovery_report_keeps_deleted_paths_and_literal_names(retained):
    _repo, worktree, _registration, _head = retained
    (worktree / "base.txt").unlink()
    (worktree / "literal\nname.py").write_text("retained data\n")
    result = _report(retained)
    entries = {entry["path"]: entry for entry in result["candidate"]["files"]}
    assert entries["base.txt"] == {"path": "base.txt", "status": " D", "worktree": "absent"}
    assert entries["literal\nname.py"]["status"] == "??"
    assert entries["literal\nname.py"]["size"] == len("retained data\n")


@pytest.mark.parametrize("flag", ["--assume-unchanged", "--skip-worktree"])
def test_recovery_cli_refuses_hidden_index_changes(retained, flag):
    _repo, worktree, _registration, _head = retained
    _git(worktree, "update-index", flag, "base.txt")
    (worktree / "base.txt").write_text("hidden unpublished content\n")
    index = Path(_git(worktree, "rev-parse", "--git-path", "index"))
    before = index.read_bytes()
    result = _cli(retained)
    assert result.returncode == 1, result.stdout
    assert json.loads(result.stdout)["ok"] is False
    assert "index" in json.loads(result.stdout)["error"]
    assert "hidden unpublished content" not in result.stdout
    assert index.read_bytes() == before  # Refusal must not clear or normalize the hints.
    assert (worktree / "base.txt").read_text() == "hidden unpublished content\n"


@pytest.mark.parametrize("flags", [b"H base.txt", b"H \0", b"\0"])
def test_recovery_refuses_malformed_index_flags_before_status(retained, monkeypatch, flags):
    _repo, worktree, _registration, head = retained
    original = agent_worktree._recovery_git

    def observe(path, *args):
        if args == ("ls-files", "-v", "-z"):
            return flags
        assert args[0] != "status", "index refusal must precede candidate selection and content reads"
        return original(path, *args)

    monkeypatch.setattr(agent_worktree, "_recovery_git", observe)
    with pytest.raises(agent_worktree.WorktreeLifecycleError, match="index flags"):
        agent_worktree._recovery_candidate(worktree, head)
