"""Persistent epic workspace lifecycle (#6616)."""

from __future__ import annotations

import json
import os
import subprocess

from app.builderops import epic_workspace as ew
from tests.builderops.test_epic_workspace_isolation import FakeEngine, _cli, _seed_repo


def test_container_removal_preserves_checkout_and_run_state(tmp_path, capsys):
    repo = _seed_repo(tmp_path)
    root = tmp_path / "ws"
    engine = FakeEngine()
    assert _cli(root, 6615, engine, "init", "--repo-url", repo) == 0
    assert _cli(root, 6615, engine, "worker-create", "--worker", "w-a", "--issue", "6617", "--branch", "b/a", "--next-action", "finish checkpoint tests") == 0
    assert _cli(root, 6615, engine, "worker-start", "--worker", "w-a", "--model", "claude-sonnet-5-5", "--", "sleep", "60") == 0

    layout = ew.Layout(root.resolve(), 6615)
    partial = layout.checkout("w-a") / "app" / "partial.py"
    partial.parent.mkdir()
    partial.write_text("def half_done():\n")
    (layout.checkout("w-a") / ".gitignore").write_text("*.txt\n")
    (layout.checkout("w-a") / "notes.txt").write_text("ignored but unique\n")
    (layout.home("w-a") / "session.jsonl").write_text("{}\n")

    capsys.readouterr()
    assert _cli(root, 6615, engine, "worker-stop", "--worker", "w-a", "--reason", "controlled loss") == 0
    stop = json.loads(capsys.readouterr().out)["work_at_stop"]
    assert stop["unique_work"] is True and "app/partial.py" in stop["uncommitted_paths"]
    assert stop["ignored_paths"] == ["notes.txt"]
    assert engine.containers == {}

    # A fresh controller process (new engine object, no in-memory state) reads it back.
    fresh = FakeEngine()
    assert _cli(root, 6615, fresh, "status") == 0
    report = json.loads(capsys.readouterr().out)
    [worker] = report["workers"]
    assert worker["issue"] == 6617 and worker["branch"] == "b/a"
    assert worker["recorded_state"] == "stopped_verified" and worker["container"] == "absent"
    assert worker["model"] == "claude-sonnet-5-5"
    assert worker["next_action"] == "finish checkpoint tests"
    assert worker["work"]["uncommitted_count"] == 2  # app/partial.py and the new .gitignore
    assert worker["work"]["ignored_count"] == 1
    assert partial.read_text() == "def half_done():\n"
    assert (layout.home("w-a") / "session.jsonl").exists()

    # Re-init is idempotent and keeps the record.
    assert _cli(root, 6615, fresh, "init", "--repo-url", repo) == 0
    state = ew._load_state(layout)
    assert state["issue_mappings"]["6617"]["stop_reason"] == "controlled loss"


GIT_ENV = {**os.environ, "GIT_AUTHOR_NAME": "t", "GIT_AUTHOR_EMAIL": "t@example.invalid", "GIT_COMMITTER_NAME": "t", "GIT_COMMITTER_EMAIL": "t@example.invalid"}


def _git(checkout, *args):
    """Fixture-side git, standing in for what a worker did inside its own container."""

    return subprocess.run(["git", "-C", str(checkout), *args], check=True, capture_output=True, text=True, env=GIT_ENV).stdout.strip()


def _out(capsys):
    return json.loads(capsys.readouterr().out)


def _new_worker(root, engine, repo, name, issue, branch="b/a"):
    assert _cli(root, 6615, engine, "worker-create", "--worker", name, "--issue", str(issue), "--branch", branch, "--next-action", f"finish {name}") == 0
    return ew.Layout(root.resolve(), 6615).checkout(name)


def test_replacement_preserves_work_and_reconstructs_next_action(tmp_path, capsys):
    repo = _seed_repo(tmp_path)
    root = tmp_path / "ws"
    engine = FakeEngine()
    assert _cli(root, 6615, engine, "init", "--repo-url", repo) == 0
    checkout = _new_worker(root, engine, repo, "w-a", 6617)
    assert _cli(root, 6615, engine, "worker-start", "--worker", "w-a", "--model", "claude-sonnet-5-5", "--", "sleep", "60") == 0

    # A partial write: modified tracked file, new file, an ignored-but-unique file.
    (checkout / "README.md").write_text("half edited\n")
    (checkout / "app").mkdir()
    (checkout / "app" / "partial.py").write_text("def half_done():\n")
    (checkout / ".git" / "info" / "exclude").write_text("*.txt\n")
    (checkout / "notes.txt").write_text("ignored but unique\n")
    capsys.readouterr()

    # The worker is replaced: container removed, work checkpointed before anything else happens.
    assert _cli(root, 6615, engine, "worker-stop", "--worker", "w-a", "--reason", "replaced mid-write") == 0
    stop = _out(capsys)["work_at_stop"]
    ref = stop["checkpoint"]["ref"]
    assert ref == "refs/checkpoints/ckpt-0001"
    assert _git(checkout, "show", f"{ref}:app/partial.py") == "def half_done():"
    assert _git(checkout, "show", f"{ref}:README.md") == "half edited"
    assert _git(checkout, "show", f"{ref}:notes.txt") == "ignored but unique"
    assert _git(checkout, "rev-parse", f"{ref}^") == stop["head"]
    # The working tree and the real index are untouched by the checkpoint.
    assert (checkout / "app" / "partial.py").read_text() == "def half_done():\n"
    assert [line.strip() for line in _git(checkout, "status", "--porcelain").splitlines()] == ["M README.md", "?? app/"]

    # No successor may write until takeover has reconciled.
    assert _cli(root, 6615, engine, "worker-start", "--worker", "w-a", "--", "sleep", "60") == 2
    assert "takeover required" in capsys.readouterr().err

    # A fresh controller process with no memory reconstructs the next action from run-state alone.
    fresh = FakeEngine()
    assert _cli(root, 6615, fresh, "continuation-brief", "--worker", "w-a") == 0
    brief = _out(capsys)
    assert brief["issue"] == 6617 and brief["branch"] == "b/a"
    assert brief["next_authorized_action"]["action"].startswith("run takeover")
    assert brief["next_authorized_action"]["recorded_next_action"] == "finish w-a"
    assert [c["ref"] for c in brief["checkpoints"]] == [ref]

    assert _cli(root, 6615, fresh, "takeover", "--worker", "w-a", "--reason", "continue after replacement") == 0
    taken = _out(capsys)
    assert taken["already_authorized"] is False and taken["generation"] == 1
    assert taken["next_authorized_action"]["action"].endswith("finish w-a")
    assert "finish w-a" in taken["prompt"] and ref in taken["prompt"] and "git status" in taken["prompt"]
    assert "githubusercontent" not in taken["prompt"]
    # Repeating takeover does not mint a second continuation.
    assert _cli(root, 6615, fresh, "takeover", "--worker", "w-a", "--reason", "again") == 0
    again = _out(capsys)
    assert again["already_authorized"] is True and again["generation"] == 1
    # The successor continues in the same checkout and finds the edits.
    assert _cli(root, 6615, fresh, "worker-start", "--worker", "w-a", "--", "sleep", "60") == 0
    assert (checkout / "app" / "partial.py").read_text() == "def half_done():\n"


def test_worker_create_records_actual_branch_and_refuses_mismatch(tmp_path, capsys):
    repo = _seed_repo(tmp_path)
    root = tmp_path / "ws"
    engine = FakeEngine()
    assert _cli(root, 6615, engine, "init", "--repo-url", repo) == 0
    checkout = _new_worker(root, engine, repo, "w-a", 6617)
    layout = ew.Layout(root.resolve(), 6615)
    assert ew._load_state(layout)["issue_mappings"]["6617"]["branch"] == "b/a"

    # Re-running with another branch used to record it without switching; now it refuses.
    capsys.readouterr()
    assert _cli(root, 6615, engine, "worker-create", "--worker", "w-a", "--issue", "6617", "--branch", "b/other", "--next-action", "x") == 2
    assert "not the requested" in capsys.readouterr().err
    assert ew._load_state(layout)["issue_mappings"]["6617"]["branch"] == "b/a"
    # A checkout that drifted to another branch is refused even for its recorded branch.
    _git(checkout, "checkout", "--quiet", "-b", "drifted")
    assert _cli(root, 6615, engine, "worker-create", "--worker", "w-a", "--issue", "6617", "--branch", "b/a", "--next-action", "x") == 2
    _git(checkout, "checkout", "--quiet", "b/a")
    assert _cli(root, 6615, engine, "worker-create", "--worker", "w-a", "--issue", "6617", "--branch", "b/a", "--next-action", "updated") == 0
    mapping = ew._load_state(layout)["issue_mappings"]["6617"]
    assert mapping["branch"] == "b/a" and mapping["next_action"] == "updated" and mapping["state"] == "created"


def test_retirement_preserves_unique_work_and_unrelated_services(tmp_path, capsys):
    repo = _seed_repo(tmp_path)
    root = tmp_path / "ws"
    engine = FakeEngine()
    layout = ew.Layout(root.resolve(), 6615)
    assert _cli(root, 6615, engine, "init", "--repo-url", repo) == 0
    # Unrelated service and another epic's worker, running throughout.
    engine.containers["unrelated-svc"] = "running"
    engine.containers["other-epic-worker"] = "running"

    def other_branch(c):
        _git(c, "checkout", "--quiet", "-b", "side")
        (c / "side.txt").write_text("side\n")
        _git(c, "add", "-f", "side.txt")
        _git(c, "commit", "--quiet", "-m", "side work")
        _git(c, "checkout", "--quiet", "b/other-branch")

    def stashed(c):
        (c / "README.md").write_text("stashed edit\n")
        _git(c, "stash", "push", "--quiet")

    def ignored(c):
        (c / ".git" / "info" / "exclude").write_text("*.txt\n.codex-tmp/\n")
        (c / ".codex-tmp").mkdir()
        (c / ".codex-tmp" / "epic-continuation.md").write_text("note\n")

    def unreadable(c):
        (c / ".git" / "HEAD").write_text("garbage\n")

    def detached_commit(c):
        _git(c, "checkout", "--quiet", "--detach")
        (c / "d.txt").write_text("d\n")
        _git(c, "add", "d.txt")
        _git(c, "commit", "--quiet", "-m", "detached")

    scenarios = {"other-branch": other_branch, "stash": stashed, "ignored": ignored, "unreadable": unreadable, "detached": detached_commit}
    for number, (name, mutate) in enumerate(scenarios.items()):
        worker = f"w-{name}"
        checkout = _new_worker(root, engine, repo, worker, 7000 + number, branch=f"b/{name}")
        mutate(checkout)
        work = ew.inspect_checkout(checkout, runner=engine)
        assert work["unique_work"] is True, name
        if name == "other-branch":
            assert [b["ref"] for b in work["other_branches"]] == ["refs/heads/side"] and work["unpublished_commits"] == 0
        if name == "stash":
            assert work["stash_entries"] == 1 and work["stash_unpublished"] > 0 and work["uncommitted_count"] == 0
        if name == "ignored":
            assert work["ignored_paths"] == [".codex-tmp/"] and work["uncommitted_count"] == 0
        if name == "unreadable":
            assert work["readable"] is False
        capsys.readouterr()
        assert _cli(root, 6615, engine, "worker-retire", "--worker", worker) == 2, name
        assert "UniqueWorkPresent" in capsys.readouterr().err
        assert checkout.is_dir()
        assert ew._load_state(layout)["issue_mappings"][str(7000 + number)]["retirement_refused"]["reasons"]

    # Disposable caches alone are not unique work; the clean worker's checkout is removed, its home and record stay.
    clean = _new_worker(root, engine, repo, "w-clean", 7100, branch="b/clean")
    (clean / ".git" / "info" / "exclude").write_text("__pycache__/\n*.pyc\n")
    (clean / "__pycache__").mkdir()
    (clean / "__pycache__" / "x.cpython-312.pyc").write_bytes(b"\0")
    work = ew.inspect_checkout(clean, runner=engine)
    assert work["unique_work"] is False and work["disposable_ignored_count"] == 1 and work["ignored_count"] == 0
    assert _cli(root, 6615, engine, "worker-start", "--worker", "w-clean", "--", "sleep", "60") == 0
    capsys.readouterr()
    assert _cli(root, 6615, engine, "worker-retire", "--worker", "w-clean") == 0
    assert _out(capsys) == {"worker": "w-clean", "container_removed": True, "checkout_removed": True}
    assert not clean.exists() and layout.home("w-clean").is_dir()
    assert "w-clean" not in engine.containers
    assert ew._load_state(layout)["issue_mappings"]["7100"]["state"] == "retired"
    assert engine.containers["unrelated-svc"] == "running" and engine.containers["other-epic-worker"] == "running"
    rm_targets = {c[-1] for c in engine.calls if c[1] == "rm"}
    assert all(t.startswith("epicws-6615-w-") for t in rm_targets)


def test_checkpoint_release_gates_retirement_on_published_content(tmp_path, capsys):
    repo = _seed_repo(tmp_path)
    root = tmp_path / "ws"
    engine = FakeEngine()
    assert _cli(root, 6615, engine, "init", "--repo-url", repo) == 0
    checkout = _new_worker(root, engine, repo, "w-a", 6617)
    (checkout / "app.py").write_text("work\n")
    capsys.readouterr()
    assert _cli(root, 6615, engine, "worker-stop", "--worker", "w-a", "--reason", "replace") == 0
    ref = _out(capsys)["work_at_stop"]["checkpoint"]["ref"]

    # The successor commits the same content; the coordinator publishes it (remote-tracking ref updated).
    _git(checkout, "add", "app.py")
    _git(checkout, "commit", "--quiet", "-m", "work")
    sha = _git(checkout, "rev-parse", "HEAD")
    assert _cli(root, 6615, engine, "worker-retire", "--worker", "w-a") == 2  # unpublished commit
    _git(checkout, "update-ref", "refs/remotes/origin/b/a", sha)
    capsys.readouterr()
    assert _cli(root, 6615, engine, "worker-retire", "--worker", "w-a") == 2
    assert "unreleased checkpoints" in capsys.readouterr().err
    base = _git(checkout, "rev-parse", "origin/main")
    assert _cli(root, 6615, engine, "checkpoint-release", "--worker", "w-a", "--ref", ref, "--published-commit", base) == 2
    assert "not in the published commit" in capsys.readouterr().err
    assert _cli(root, 6615, engine, "checkpoint-release", "--worker", "w-a", "--ref", ref, "--published-commit", sha) == 0
    assert _cli(root, 6615, engine, "worker-retire", "--worker", "w-a") == 0
    assert not checkout.exists()
