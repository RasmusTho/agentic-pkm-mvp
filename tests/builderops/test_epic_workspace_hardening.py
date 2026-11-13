"""Review findings on preservation and takeover (#6617): forgeable publication, hidden work,
worker-planted filters, checkpoint collisions, start/stop races and hung git. Every test drives the
production CLI (``epic_workspace.main``)."""

from __future__ import annotations

import json
import os
import subprocess
from concurrent.futures import ThreadPoolExecutor
from threading import Event

from app.builderops import epic_run_state
from app.builderops import epic_workspace as ew
from tests.builderops.test_epic_workspace_isolation import FakeEngine, _cli, _seed_repo
from tests.builderops.test_epic_workspace_lifecycle import GIT_ENV, _ckpt, _git, _new_worker, _out, _publish, _snapshot
from tests.builderops.test_epic_workspace_openhands import FakeAgentServer, _main, _setup


def _work(root, engine, capsys, worker):
    capsys.readouterr()
    assert _cli(root, 6615, engine, "status") == 0
    report = json.loads(capsys.readouterr().out)
    return next(w for w in report["workers"] if w["worker"] == worker)["work"]


def _commit(checkout, name="unique.txt", *args):
    (checkout / name).write_text(f"{name}\n")
    _git(checkout, "add", "-f", name)
    _git(checkout, "commit", "--quiet", "-m", f"work {name}", *args)
    return _git(checkout, "rev-parse", "HEAD")


def _layout(root):
    return ew.Layout(root.resolve(), 6615)


def _mapping(root, issue):
    return ew._load_state(_layout(root))["issue_mappings"][str(issue)]


# ------------------------------------------------------------------ P0: published is controller-held evidence


def test_published_is_decided_only_from_controller_held_evidence(tmp_path, capsys):
    repo = _seed_repo(tmp_path)
    root = tmp_path / "ws"
    engine = FakeEngine()
    assert _cli(root, 6615, engine, "init", "--repo-url", repo) == 0
    checkout = _new_worker(root, engine, repo, "w-a", 6617)
    sha = _commit(checkout)
    # The worker can write any ref it likes; none of them is publication evidence.
    for forged in ("refs/remotes/origin/fake", "refs/remotes/origin/b/a", "refs/heads/origin/main"):
        _git(checkout, "update-ref", forged, sha)
    capsys.readouterr()
    assert _cli(root, 6615, engine, "worker-retire", "--worker", "w-a") == 2
    assert "UniqueWorkPresent" in capsys.readouterr().err
    assert checkout.is_dir() and _git(checkout, "rev-parse", "HEAD") == sha
    assert _work(root, engine, capsys, "w-a")["unpublished_commits"] == 1

    # A recorded head that does not contain the worker's commit does not publish it either.
    _publish(root, engine, capsys, "b" * 40, kind="pr_create")
    assert _cli(root, 6615, engine, "worker-retire", "--worker", "w-a") == 2
    assert checkout.is_dir()
    capsys.readouterr()

    # The coordinator's publication-complete step (GitHub head readback) is what publishes it,
    # also when a squash merge leaves the worker's commit out of main.
    _publish(root, engine, capsys, sha)
    assert _mapping(root, 6617)["published_heads"][-1]["sha"] == sha
    assert _work(root, engine, capsys, "w-a")["unique_work"] is False
    for checkpoint in _mapping(root, 6617)["checkpoints"]:
        if checkpoint["status"] == "preserved":
            assert _cli(root, 6615, engine, "checkpoint-release", "--worker", "w-a", "--ref", checkpoint["ref"], "--published-commit", sha) == 0
    assert _cli(root, 6615, engine, "worker-retire", "--worker", "w-a") == 0
    assert not checkout.exists()


def test_publication_completion_rejects_wrong_branch_and_head(tmp_path, capsys):
    repo = _seed_repo(tmp_path)
    root = tmp_path / "ws"
    engine = FakeEngine()
    assert _cli(root, 6615, engine, "init", "--repo-url", repo) == 0
    checkout = _new_worker(root, engine, repo, "w-a", 6617)
    sha = _commit(checkout)
    capsys.readouterr()
    assert _cli(root, 6615, engine, "publication-begin", "--worker", "w-a", "--kind", "pr_create", "--expect-sha", sha) == 0
    operation = _out(capsys)["id"]
    readback = tmp_path / "result.json"
    for result in (
        {"branch": "other", "sha": sha, "number": 42},
        {"branch": "b/a", "sha": "f" * 40, "number": 42},
        {"branch": "b/a", "sha": sha},
    ):
        readback.write_text(json.dumps(result))
        assert _cli(root, 6615, engine, "publication-complete", "--worker", "w-a", "--op", operation, "--result-file", str(readback)) == 2
        assert _mapping(root, 6617)["publication_ops"][-1]["status"] == "intended"
        assert not _mapping(root, 6617).get("published_heads")
    readback.write_text(json.dumps({"branch": "b/a", "sha": sha, "number": 42}))
    assert _cli(root, 6615, engine, "publication-complete", "--worker", "w-a", "--op", operation, "--result-file", str(readback)) == 0
    assert _mapping(root, 6617)["published_heads"][-1]["sha"] == sha


def test_controller_owned_nonstandard_ref_is_publication_evidence(tmp_path, capsys):
    repo = _seed_repo(tmp_path)
    root = tmp_path / "ws"
    engine = FakeEngine()
    assert _cli(root, 6615, engine, "init", "--repo-url", repo) == 0
    checkout = _new_worker(root, engine, repo, "w-a", 6617)
    sha = _commit(checkout)
    capsys.readouterr()
    assert _work(root, engine, capsys, "w-a")["unique_work"] is True
    # The test coordinator updates its own bare source repo; the worker's refs alone do not count.
    _git(checkout, "push", "--quiet", str(_layout(root).source), f"{sha}:refs/verified/fixture")
    assert _work(root, engine, capsys, "w-a")["unique_work"] is False
    base = _git(checkout, "rev-parse", "origin/main")
    subprocess.run(["git", "--git-dir", str(_layout(root).source), "pack-refs", "--all"], check=True)
    subprocess.run(["git", "--git-dir", str(_layout(root).source), "update-ref", "refs/verified/fixture", base], check=True)
    assert _work(root, engine, capsys, "w-a")["unique_work"] is True


def test_work_hidden_in_other_refs_worktrees_and_index_flags_is_unique(tmp_path, capsys):
    repo = _seed_repo(tmp_path)
    root = tmp_path / "ws"
    engine = FakeEngine()
    assert _cli(root, 6615, engine, "init", "--repo-url", repo) == 0

    def detached_commit(c):
        _git(c, "checkout", "--quiet", "--detach")
        sha = _commit(c)
        _git(c, "checkout", "--quiet", c.parent.name and _git(c, "rev-parse", "--abbrev-ref", "origin/HEAD").split("/")[-1])
        return sha

    def via_tag(c):
        _git(c, "tag", "keep", detached_commit(c))

    def via_custom_ref(c):
        _git(c, "update-ref", "refs/custom/keep", detached_commit(c))

    def via_remote_ref(c):
        _git(c, "update-ref", "refs/remotes/upstream/keep", detached_commit(c))

    def via_linked_worktree(c):
        wt = tmp_path / "linked-worktree"
        _git(c, "worktree", "add", "--quiet", "--detach", str(wt))
        _commit(wt)

    def skip_worktree(c):
        (c / "README.md").write_text("hidden edit\n")
        _git(c, "update-index", "--skip-worktree", "README.md")

    def assume_unchanged_ignore_stat(c):
        (c / "README.md").write_text("hidden edit\n")
        _git(c, "update-index", "--assume-unchanged", "README.md")
        _git(c, "config", "core.ignoreStat", "true")

    scenarios = {
        "tag": via_tag, "custom": via_custom_ref, "remote": via_remote_ref, "worktree": via_linked_worktree,
        "skip": skip_worktree, "assume": assume_unchanged_ignore_stat,
    }
    for number, (name, mutate) in enumerate(scenarios.items()):
        worker = f"w-{name}"
        checkout = _new_worker(root, engine, repo, worker, 8000 + number, branch=f"b/{name}")
        mutate(checkout)
        work = _work(root, engine, capsys, worker)
        assert work["unique_work"] is True, name
        assert work["unpublished_total"] or work["uncommitted_count"], name
        assert _cli(root, 6615, engine, "worker-retire", "--worker", worker) == 2, name
        assert checkout.is_dir(), name
        capsys.readouterr()


def test_every_contained_git_call_is_hardened_and_read_only(tmp_path, capsys):
    repo = _seed_repo(tmp_path)
    root = tmp_path / "ws"
    engine = FakeEngine()
    assert _cli(root, 6615, engine, "init", "--repo-url", repo) == 0
    checkout = _new_worker(root, engine, repo, "w-a", 6617)
    (checkout / "partial.txt").write_text("x\n")
    assert _cli(root, 6615, engine, "worker-stop", "--worker", "w-a", "--reason", "r") == 0
    assert _cli(root, 6615, engine, "status") == 0
    assert engine.inspections
    for argv in engine.inspections:
        text = " ".join(argv)
        for needle in ("core.ignoreStat=false", "core.fsmonitor=false", "core.hooksPath=/dev/null", "core.commitGraph=false", "GIT_NO_REPLACE_OBJECTS=1"):
            assert needle in text, (needle, text)
        assert argv[argv.index("--user") + 1] == f"{os.geteuid()}:{os.getegid()}"
        mounts = [argv[i + 1] for i, a in enumerate(argv) if a == "--mount"]
        assert mounts[0].endswith(f"target={ew.INSPECT_TARGET},readonly")
    assert all(timeout for timeout in engine.timeouts)


# ------------------------------------------------------------------ P1: filters, symlinks, ref collisions


def test_worker_planted_filters_cannot_run_or_alter_the_checkpoint(tmp_path, capsys):
    repo = _seed_repo(tmp_path)
    root = tmp_path / "ws"
    engine = FakeEngine()
    assert _cli(root, 6615, engine, "init", "--repo-url", repo) == 0
    checkout = _new_worker(root, engine, repo, "w-a", 6617)
    marker = tmp_path / "filter-ran"
    cleaner = tmp_path / "clean.sh"
    cleaner.write_text(f"#!/bin/sh\ntouch {marker}\nsed 's/^/FILTERED:/'\n")
    cleaner.chmod(0o755)
    _git(checkout, "config", "filter.evil.clean", str(cleaner))
    _git(checkout, "config", "filter.evil.required", "true")
    (checkout / ".git" / "info" / "attributes").write_text("* filter=evil\n")
    (checkout / ".gitattributes").write_text("* filter=evil\n")
    (checkout / "README.md").write_text("tracked edit\n")
    (checkout / "partial.py").write_text("def half():\n")
    head = _git(checkout, "rev-parse", "HEAD")
    # The attacker's escape hatch: a pre-existing symlink where the old checkpoint index lived.
    victim = tmp_path / "victim.txt"
    victim.write_text("do not touch\n")
    (checkout / ".git" / "epic-checkpoint.index").symlink_to(victim)
    before = _snapshot(checkout / ".git")
    capsys.readouterr()

    assert _cli(root, 6615, engine, "takeover", "--worker", "w-a", "--reason", "continue") == 2
    assert "unreadable" in capsys.readouterr().err
    assert victim.read_text() == "do not touch\n" and not marker.exists()
    (checkout / ".git" / "epic-checkpoint.index").unlink()
    before = _snapshot(checkout / ".git")
    assert _cli(root, 6615, engine, "takeover", "--worker", "w-a", "--reason", "continue") == 0
    taken = _out(capsys)
    assert not marker.exists(), "a worker-planted filter ran during inspection or checkpoint"
    assert victim.read_text() == "do not touch\n"
    assert _git(checkout, "rev-parse", "HEAD") == head
    assert _snapshot(checkout / ".git") == before
    ref = taken["checkpoints"][0]["ref"]
    assert _ckpt(root, "w-a", "show", f"{ref}:partial.py") == "def half():"
    assert _ckpt(root, "w-a", "show", f"{ref}:README.md") == "tracked edit"
    assert _ckpt(root, "w-a", "show", f"{ref}:.gitattributes") == "* filter=evil"
    assert _mapping(root, 6617)["takeover"]["status"] == "authorized"


def test_checkpoint_preserves_raw_bytes_despite_worker_attributes(tmp_path, capsys):
    repo = _seed_repo(tmp_path)
    root = tmp_path / "ws"
    engine = FakeEngine()
    assert _cli(root, 6615, engine, "init", "--repo-url", repo) == 0
    checkout = _new_worker(root, engine, repo, "w-a", 6617)
    (checkout / ".gitattributes").write_text("*.txt text eol=lf\n")
    (checkout / "raw.txt").write_bytes(b"one\r\ntwo\r\n")
    capsys.readouterr()
    assert _cli(root, 6615, engine, "takeover", "--worker", "w-a", "--reason", "r") == 0
    checkpoint_repo = _layout(root).epic_dir / "control" / "checkpoints" / "w-a.git"
    result = subprocess.run(
        ["git", "--git-dir", str(checkpoint_repo), "show", "refs/checkpoints/ckpt-0001:raw.txt"],
        capture_output=True, check=True,
    )
    assert result.stdout == b"one\r\ntwo\r\n"


def test_controller_paths_that_are_symlinks_are_refused(tmp_path, capsys):
    repo = _seed_repo(tmp_path)
    root = tmp_path / "ws"
    engine = FakeEngine()
    assert _cli(root, 6615, engine, "init", "--repo-url", repo) == 0
    checkout = _new_worker(root, engine, repo, "w-a", 6617)
    (checkout / "partial.py").write_text("x\n")
    layout = _layout(root)
    elsewhere = tmp_path / "elsewhere"
    elsewhere.mkdir()
    control = layout.epic_dir / "control"
    control.mkdir(mode=0o700, exist_ok=True)
    (control / "checkpoints").symlink_to(elsewhere)
    capsys.readouterr()
    assert _cli(root, 6615, engine, "worker-stop", "--worker", "w-a", "--reason", "r") == 2
    assert "symlink" in capsys.readouterr().err
    assert list(elsewhere.iterdir()) == []
    assert not _mapping(root, 6617).get("checkpoints")
    assert (checkout / "partial.py").exists()
    (control / "checkpoints").unlink()
    repo_dir = control / "checkpoints" / "w-a.git"
    (control / "checkpoints").mkdir()
    repo_dir.symlink_to(elsewhere)
    assert _cli(root, 6615, engine, "worker-checkpoint", "--worker", "w-a", "--reason", "r") == 2
    assert list(elsewhere.iterdir()) == []


def test_symlinked_worker_object_directory_is_unreadable_and_preserved(tmp_path, capsys):
    repo = _seed_repo(tmp_path)
    root = tmp_path / "ws"
    engine = FakeEngine()
    assert _cli(root, 6615, engine, "init", "--repo-url", repo) == 0
    checkout = _new_worker(root, engine, repo, "w-a", 6617)
    objects = checkout / ".git" / "objects"
    saved = checkout / ".git" / "fixture-objects"
    objects.rename(saved)
    objects.symlink_to(saved, target_is_directory=True)
    capsys.readouterr()
    work = _work(root, engine, capsys, "w-a")
    assert work["unique_work"] is True and work["readable"] is False
    assert _cli(root, 6615, engine, "worker-retire", "--worker", "w-a") == 2
    assert checkout.exists() and objects.is_symlink() and saved.is_dir()
    assert not _mapping(root, 6617).get("checkpoints")


def test_missing_checkout_never_authorizes_takeover_or_retirement(tmp_path, capsys):
    repo = _seed_repo(tmp_path)
    root = tmp_path / "ws"
    engine = FakeEngine()
    assert _cli(root, 6615, engine, "init", "--repo-url", repo) == 0
    checkout = _new_worker(root, engine, repo, "w-a", 6617)
    (checkout / "partial.txt").write_text("keep\n")
    preserved = checkout.with_name("preserved-fixture")
    checkout.rename(preserved)
    capsys.readouterr()
    work = _work(root, engine, capsys, "w-a")
    assert work["unique_work"] is True and work["readable"] is False
    assert _cli(root, 6615, engine, "takeover", "--worker", "w-a", "--reason", "r") == 2
    assert _mapping(root, 6617)["takeover"]["status"] == "required"
    assert _cli(root, 6615, engine, "worker-retire", "--worker", "w-a") == 2
    assert (preserved / "partial.txt").read_text() == "keep\n"


def test_ignored_nested_repository_is_preserved_as_unreadable(tmp_path, capsys):
    repo = _seed_repo(tmp_path)
    root = tmp_path / "ws"
    engine = FakeEngine()
    assert _cli(root, 6615, engine, "init", "--repo-url", repo) == 0
    checkout = _new_worker(root, engine, repo, "w-a", 6617)
    (checkout / ".git" / "info" / "exclude").write_text("archive/\n")
    archive = checkout / "archive"
    archive.mkdir()
    _seed_repo(archive)
    (archive / "origin" / "uncommitted").write_text("must survive\n")
    capsys.readouterr()
    work = _work(root, engine, capsys, "w-a")
    assert work["unique_work"] is True and work["readable"] is False
    assert _cli(root, 6615, engine, "worker-retire", "--worker", "w-a") == 2
    assert (archive / "origin" / "uncommitted").read_text() == "must survive\n"


def test_checkpoint_ref_collisions_never_block_takeover(tmp_path, capsys):
    repo = _seed_repo(tmp_path)
    root = tmp_path / "ws"
    engine = FakeEngine()
    assert _cli(root, 6615, engine, "init", "--repo-url", repo) == 0
    checkout = _new_worker(root, engine, repo, "w-a", 6617)
    (checkout / "partial.py").write_text("def half():\n")
    # A worker pre-creating the next checkpoint name in its own checkout blocks nothing.
    _git(checkout, "update-ref", "refs/checkpoints/ckpt-0001", "HEAD")
    capsys.readouterr()
    assert _cli(root, 6615, engine, "takeover", "--worker", "w-a", "--reason", "r") == 0
    capsys.readouterr()
    [record] = _mapping(root, 6617)["checkpoints"]
    assert record["ref"] == "refs/checkpoints/ckpt-0001"
    assert _ckpt(root, "w-a", "show", "refs/checkpoints/ckpt-0001:partial.py") == "def half():"

    def forget_records():
        epic_run_state.update_epic_run_state(
            "epic-6615", root=_layout(root).run_state_dir, expected_epic_issue_number=6615,
            updater=lambda state: {**state, "issue_mappings": {**state["issue_mappings"], "6617": {**state["issue_mappings"]["6617"], "checkpoints": []}}},
        )

    # Crash between update-ref and the run-state write: the identical ref is adopted, not duplicated.
    forget_records()
    assert _cli(root, 6615, engine, "worker-checkpoint", "--worker", "w-a", "--reason", "retry after crash") == 0
    adopted = _out(capsys)["checkpoint"]
    assert adopted["ref"] == "refs/checkpoints/ckpt-0001" and adopted["adopted"] is True
    assert _ckpt(root, "w-a", "for-each-ref", "--format=%(refname)", "refs/checkpoints") == "refs/checkpoints/ckpt-0001"
    assert [c["ref"] for c in _mapping(root, 6617)["checkpoints"]] == ["refs/checkpoints/ckpt-0001"]

    # A stale ref with different content is never overwritten; the next free name is allocated.
    stale = _ckpt(root, "w-a", "commit-tree", "-m", "stale", "4b825dc642cb6eb9a060e54bf8d69288fbee4904")
    _ckpt(root, "w-a", "update-ref", "refs/checkpoints/ckpt-0002", stale)
    forget_records()
    (checkout / "partial.py").write_text("def half():\n    return 1\n")
    assert _cli(root, 6615, engine, "worker-checkpoint", "--worker", "w-a", "--reason", "new content") == 0
    assert _out(capsys)["checkpoint"]["ref"] == "refs/checkpoints/ckpt-0003"
    assert _ckpt(root, "w-a", "rev-parse", "refs/checkpoints/ckpt-0002") == stale


def test_checkpoint_collision_with_extra_parent_is_not_adopted(tmp_path, capsys):
    repo = _seed_repo(tmp_path)
    root = tmp_path / "ws"
    engine = FakeEngine()
    assert _cli(root, 6615, engine, "init", "--repo-url", repo) == 0
    checkout = _new_worker(root, engine, repo, "w-a", 6617)
    (checkout / "partial.py").write_text("work\n")
    capsys.readouterr()
    assert _cli(root, 6615, engine, "takeover", "--worker", "w-a", "--reason", "r") == 0
    record = _mapping(root, 6617)["checkpoints"][0]
    other = _ckpt(root, "w-a", "commit-tree", record["tree"], "-m", "other")
    collision = _ckpt(root, "w-a", "commit-tree", record["tree"], "-p", record["head"], "-p", other, "-m", "collision")
    _ckpt(root, "w-a", "update-ref", record["ref"], collision)
    epic_run_state.update_epic_run_state(
        "epic-6615", root=_layout(root).run_state_dir, expected_epic_issue_number=6615,
        updater=lambda state: {**state, "issue_mappings": {**state["issue_mappings"], "6617": {**state["issue_mappings"]["6617"], "checkpoints": []}}},
    )
    capsys.readouterr()
    assert _cli(root, 6615, engine, "worker-checkpoint", "--worker", "w-a", "--reason", "retry") == 0
    assert _out(capsys)["checkpoint"]["ref"] == "refs/checkpoints/ckpt-0002"
    assert _ckpt(root, "w-a", "rev-parse", "refs/checkpoints/ckpt-0001") == collision


# ------------------------------------------------------------------ acceptance binding: races and exactly-one continuation


class RacingEngine(FakeEngine):
    """Runs a callback when the controller first reads a worker's container state."""

    def __init__(self) -> None:
        super().__init__()
        self.on_first_ps = None
        self.appear_after_ps: int | None = None
        self.ps_calls = 0

    def __call__(self, argv, **kwargs):
        argv = list(argv)
        if len(argv) > 1 and argv[1] == "ps" and any(a.startswith(f"label={ew.LABEL_WORKER}=") for a in argv):
            self.ps_calls += 1
            callback, self.on_first_ps = self.on_first_ps, None
            if callback:
                callback()
            if self.appear_after_ps is not None and self.ps_calls > self.appear_after_ps:
                return subprocess.CompletedProcess(argv, 0, "running\n", "")
        return super().__call__(argv, **kwargs)


def test_start_cannot_race_a_stop_that_requires_takeover(tmp_path, capsys):
    repo = _seed_repo(tmp_path)
    root = tmp_path / "ws"
    engine = RacingEngine()
    assert _cli(root, 6615, engine, "init", "--repo-url", repo) == 0
    checkout = _new_worker(root, engine, repo, "w-a", 6617)
    (checkout / "partial.py").write_text("unique work\n")
    # A stop attempts to land after start's engine readback, before it records and launches.
    # The controller's per-worker lifecycle fence refuses the overlapping stop.
    outcomes = []
    engine.on_first_ps = lambda: outcomes.append(_cli(root, 6615, engine, "worker-stop", "--worker", "w-a", "--reason", "raced stop"))
    capsys.readouterr()
    assert _cli(root, 6615, engine, "worker-start", "--worker", "w-a", "--", "sleep", "60") == 0
    assert outcomes == [2] and "lifecycle operation is in progress" in capsys.readouterr().err
    assert len(engine.runs()) == 1 and engine.containers == {"w-a": "running"}
    assert _cli(root, 6615, engine, "worker-stop", "--worker", "w-a", "--reason", "stop") == 0
    assert _mapping(root, 6617)["takeover"]["status"] == "required"

    assert _cli(root, 6615, engine, "takeover", "--worker", "w-a", "--reason", "authorize") == 0
    assert _main(root, engine, FakeAgentServer(), "openhands-start", "--worker", "w-a") == 0
    assert _mapping(root, 6617)["takeover"]["status"] == "consumed"


def test_stop_is_fenced_while_a_start_is_actually_in_flight(tmp_path, capsys):
    repo = _seed_repo(tmp_path)
    root = tmp_path / "ws"
    entered, finish = Event(), Event()

    class DelayedStart(FakeEngine):
        def __call__(self, argv, **kwargs):
            if list(argv)[:2] == ["docker", "run"] and "--rm" not in argv:
                entered.set()
                assert finish.wait(10), "fixture start did not resume"
            return super().__call__(argv, **kwargs)

    engine = DelayedStart()
    assert _cli(root, 6615, engine, "init", "--repo-url", repo) == 0
    _new_worker(root, engine, repo, "w-a", 6617)
    with ThreadPoolExecutor(max_workers=1) as pool:
        start = pool.submit(_cli, root, 6615, engine, "worker-start", "--worker", "w-a", "--", "sleep", "60")
        assert entered.wait(10)
        try:
            assert _mapping(root, 6617)["state"] == "starting"
            assert _cli(root, 6615, engine, "worker-stop", "--worker", "w-a", "--reason", "overlap") == 2
            assert _cli(root, 6615, engine, "takeover", "--worker", "w-a", "--reason", "overlap") == 2
        finally:
            finish.set()
        assert start.result(timeout=10) == 0
    assert _mapping(root, 6617)["state"] == "running" and engine.containers == {"w-a": "running"}
    assert "lifecycle operation is in progress" in capsys.readouterr().err


def test_takeover_rereads_the_engine_before_authorizing(tmp_path, capsys):
    repo = _seed_repo(tmp_path)
    root = tmp_path / "ws"
    engine = RacingEngine()
    assert _cli(root, 6615, engine, "init", "--repo-url", repo) == 0
    checkout = _new_worker(root, engine, repo, "w-a", 6617)
    (checkout / "partial.py").write_text("unique work\n")
    # The stop readback is clean; a container appears before the continuation would be authorized.
    engine.appear_after_ps = 1
    capsys.readouterr()
    assert _cli(root, 6615, engine, "takeover", "--worker", "w-a", "--reason", "r") == 2
    assert "not authorizing a continuation" in capsys.readouterr().err
    assert _mapping(root, 6617)["takeover"]["status"] == "required"


def test_plain_worker_start_consumes_the_authorized_continuation_once(tmp_path, capsys):
    repo = _seed_repo(tmp_path)
    root = tmp_path / "ws"
    engine = FakeEngine()
    assert _cli(root, 6615, engine, "init", "--repo-url", repo) == 0
    checkout = _new_worker(root, engine, repo, "w-a", 6617)
    (checkout / "partial.py").write_text("unique work\n")
    assert _cli(root, 6615, engine, "takeover", "--worker", "w-a", "--reason", "r") == 0
    assert _mapping(root, 6617)["takeover"]["status"] == "authorized"
    assert _cli(root, 6615, engine, "worker-start", "--worker", "w-a", "--", "sleep", "60") == 0
    spent = _mapping(root, 6617)["takeover"]
    assert spent["status"] == "consumed" and spent["consumed_by"] == "native-exception"

    # The successor died without a verified stop: no second continuation without a new takeover.
    engine.containers.clear()
    capsys.readouterr()
    assert _cli(root, 6615, engine, "worker-start", "--worker", "w-a", "--", "sleep", "60") == 2
    assert "without a verified stop" in capsys.readouterr().err
    assert _cli(root, 6615, engine, "openhands-start", "--worker", "w-a") == 2
    assert len(engine.runs()) == 1
    assert _cli(root, 6615, engine, "takeover", "--worker", "w-a", "--reason", "again") == 0
    assert _out(capsys)["generation"] == 2
    assert _main(root, engine, FakeAgentServer(), "openhands-start", "--worker", "w-a") == 0
    assert _mapping(root, 6617)["takeover"]["consumed_by"] == "openhands"
    assert len(engine.runs()) == 2


def test_takeover_refuses_content_changed_after_checkpoint(tmp_path, capsys):
    repo = _seed_repo(tmp_path)
    root = tmp_path / "ws"

    class MutatingEngine(FakeEngine):
        changed = False

        def __call__(self, argv, **kwargs):
            result = super().__call__(argv, **kwargs)
            if not self.changed and "update-ref" in argv and "--rm" in argv:
                self.changed = True
                (checkout / "README.md").write_text("a later partial write\n")
            return result

    engine = MutatingEngine()
    assert _cli(root, 6615, engine, "init", "--repo-url", repo) == 0
    checkout = _new_worker(root, engine, repo, "w-a", 6617)
    (checkout / "README.md").write_text("the checkpointed edit\n")
    capsys.readouterr()
    assert _cli(root, 6615, engine, "takeover", "--worker", "w-a", "--reason", "r") == 2
    assert "changed while the checkpoint" in capsys.readouterr().err
    assert _mapping(root, 6617)["takeover"]["status"] == "required"
    assert _ckpt(root, "w-a", "show", "refs/checkpoints/ckpt-0001:README.md") == "the checkpointed edit"
    assert (checkout / "README.md").read_text() == "a later partial write\n"


def test_failed_takeover_closes_gate_when_checkout_was_initially_clean(tmp_path, capsys):
    repo = _seed_repo(tmp_path)
    root = tmp_path / "ws"

    class LateWrite(FakeEngine):
        armed = False
        reads = 0

        def __call__(self, argv, **kwargs):
            if self.armed and "rev-parse" in argv and "--rm" in argv:
                self.reads += 1
                if self.reads == 2:
                    (checkout / "README.md").write_text("late write\n")
            return super().__call__(argv, **kwargs)

    engine = LateWrite()
    assert _cli(root, 6615, engine, "init", "--repo-url", repo) == 0
    checkout = _new_worker(root, engine, repo, "w-a", 6617)
    engine.armed = True
    capsys.readouterr()
    assert _cli(root, 6615, engine, "takeover", "--worker", "w-a", "--reason", "r") == 2
    assert "changed while the checkpoint" in capsys.readouterr().err
    assert _mapping(root, 6617)["takeover"]["status"] == "required"
    assert _cli(root, 6615, engine, "worker-start", "--worker", "w-a", "--", "sleep", "60") == 2
    assert (checkout / "README.md").read_text() == "late write\n"


def test_takeover_refuses_head_movement_after_checkpoint(tmp_path, capsys):
    repo = _seed_repo(tmp_path)
    root = tmp_path / "ws"

    class MovingHead(FakeEngine):
        moved = False

        def __call__(self, argv, **kwargs):
            result = super().__call__(argv, **kwargs)
            if not self.moved and "update-ref" in argv and "--rm" in argv:
                self.moved = True
                _git(checkout, "update-ref", "HEAD", base)
            return result

    engine = MovingHead()
    assert _cli(root, 6615, engine, "init", "--repo-url", repo) == 0
    checkout = _new_worker(root, engine, repo, "w-a", 6617)
    base = _git(checkout, "rev-parse", "HEAD")
    _commit(checkout)
    (checkout / "partial.py").write_text("keep this\n")
    capsys.readouterr()
    assert _cli(root, 6615, engine, "takeover", "--worker", "w-a", "--reason", "r") == 2
    assert "HEAD moved" in capsys.readouterr().err
    assert _mapping(root, 6617)["takeover"]["status"] == "required"
    assert (checkout / "partial.py").read_text() == "keep this\n"


def test_checkpoint_retains_other_refs_stash_and_linked_heads_without_worker_objects(tmp_path, capsys):
    repo = _seed_repo(tmp_path)
    root = tmp_path / "ws"
    engine = FakeEngine()
    assert _cli(root, 6615, engine, "init", "--repo-url", repo) == 0
    checkout = _new_worker(root, engine, repo, "w-a", 6617)
    _git(checkout, "checkout", "--quiet", "-b", "other")
    other = _commit(checkout, "side.txt")
    _git(checkout, "checkout", "--quiet", "b/a")
    (checkout / "README.md").write_text("stashed work\n")
    _git(checkout, "stash", "push", "--quiet")
    stash = _git(checkout, "rev-parse", "refs/stash")
    linked = tmp_path / "linked"
    _git(checkout, "worktree", "add", "--quiet", "--detach", str(linked))
    linked_head = _commit(linked, "linked.txt")
    (checkout / "partial.txt").write_text("uncommitted work\n")
    capsys.readouterr()
    assert _cli(root, 6615, engine, "takeover", "--worker", "w-a", "--reason", "r") == 0
    record = _mapping(root, 6617)["checkpoints"][0]
    assert {other, stash, linked_head} <= {
        *(item["sha"] for item in record["retained_refs"]), *record["retained_heads"], *record["retained_stash"]
    }

    # Read the controller repo without the worker object directory as an alternate.
    checkpoint_repo = _layout(root).epic_dir / "control" / "checkpoints" / "w-a.git"
    for oid, path, expected in (
        (other, "side.txt", "side.txt"), (stash, "README.md", "stashed work"),
        (linked_head, "linked.txt", "linked.txt"), (record["commit"], "partial.txt", "uncommitted work"),
    ):
        result = subprocess.run(
            ["git", "--git-dir", str(checkpoint_repo), "show", f"{oid}:{path}"],
            capture_output=True, text=True, check=True,
        )
        assert result.stdout.strip() == expected


def test_checkpoint_release_refuses_unpublished_retained_branch(tmp_path, capsys):
    repo = _seed_repo(tmp_path)
    root = tmp_path / "ws"
    engine = FakeEngine()
    assert _cli(root, 6615, engine, "init", "--repo-url", repo) == 0
    checkout = _new_worker(root, engine, repo, "w-a", 6617)
    base = _git(checkout, "rev-parse", "HEAD")
    _git(checkout, "checkout", "--quiet", "-b", "other")
    side = _commit(checkout, "side.txt")
    _git(checkout, "checkout", "--quiet", "b/a")
    capsys.readouterr()
    assert _cli(root, 6615, engine, "worker-stop", "--worker", "w-a", "--reason", "r") == 0
    ref = _out(capsys)["work_at_stop"]["checkpoint"]["ref"]
    # A later worker can remove its ref, but that is not publication evidence.
    _git(checkout, "branch", "-D", "other")
    _publish(root, engine, capsys, base)
    assert _cli(root, 6615, engine, "checkpoint-release", "--worker", "w-a", "--ref", ref, "--published-commit", base) == 2
    assert "retained commits not published" in capsys.readouterr().err
    assert _ckpt(root, "w-a", "show", f"refs/retained/{side}:side.txt") == "side.txt"


def test_failed_launch_leaves_a_retryable_record(tmp_path, capsys):
    root, engine, server = _setup(tmp_path, capsys)

    class Failing(FakeEngine):
        def __call__(self, argv, **kwargs):
            if list(argv)[:2] == ["docker", "run"] and "--rm" not in argv:
                return subprocess.CompletedProcess(argv, 125, "", "no such image")
            return super().__call__(argv, **kwargs)

    assert _main(root, Failing(), server, "openhands-start", "--worker", "w-a") == 2
    assert _mapping(root, 6617)["state"] == "start_failed"
    assert _main(root, engine, server, "openhands-start", "--worker", "w-a") == 0


def test_timed_out_launch_stays_unknown_after_an_absence_readback(tmp_path, capsys):
    root, engine, server = _setup(tmp_path, capsys)

    class TimedOut(FakeEngine):
        def __call__(self, argv, **kwargs):
            if list(argv)[:2] == ["docker", "run"] and "--rm" not in argv:
                raise subprocess.TimeoutExpired(argv, kwargs["timeout"])
            return super().__call__(argv, **kwargs)

    assert _main(root, TimedOut(), server, "openhands-start", "--worker", "w-a") == 2
    assert _mapping(root, 6617)["state"] == "starting"
    assert "unknown worker launch" in ew.next_authorized_action(_mapping(root, 6617))["action"]
    assert _main(root, engine, server, "openhands-start", "--worker", "w-a") == 2
    assert not engine.runs()
    assert _main(root, engine, server, "takeover", "--worker", "w-a", "--reason", "reconcile") == 2
    assert "launch outcome is unknown" in capsys.readouterr().err
    assert _mapping(root, 6617)["state"] == "starting" and not engine.runs()


# ------------------------------------------------------------------ hung git


def test_hung_contained_git_is_unreadable_unique_work_not_a_hang(tmp_path, capsys):
    repo = _seed_repo(tmp_path)
    root = tmp_path / "ws"
    engine = FakeEngine()
    assert _cli(root, 6615, engine, "init", "--repo-url", repo) == 0
    checkout = _new_worker(root, engine, repo, "w-a", 6617)
    assert _cli(root, 6615, engine, "worker-start", "--worker", "w-a", "--", "sleep", "60") == 0
    assert _work(root, engine, capsys, "w-a")["unique_work"] is False

    engine.hang_inspections = True
    work = _work(root, engine, capsys, "w-a")
    assert work["readable"] is False and work["unique_work"] is True
    assert engine.timeouts and all(timeout and timeout > 0 for timeout in engine.timeouts)
    # The abandoned inspection containers are removed by name, never the worker's.
    removed = [c[-1] for c in engine.calls if c[1] == "rm"]
    assert removed and all(name.startswith(f"{ew.CONTAINER_PREFIX}-git-") for name in removed)

    assert _cli(root, 6615, engine, "worker-stop", "--worker", "w-a", "--reason", "sleeping filter") == 0
    stop = _out(capsys)["work_at_stop"]
    assert stop["readable"] is False and stop["checkpoint"] is None
    assert _mapping(root, 6617)["takeover"]["status"] == "required"
    assert _cli(root, 6615, engine, "worker-retire", "--worker", "w-a") == 2
    assert _cli(root, 6615, engine, "takeover", "--worker", "w-a", "--reason", "r") == 2
    assert checkout.is_dir()
    engine.hang_inspections = False
    assert _cli(root, 6615, engine, "takeover", "--worker", "w-a", "--reason", "r") == 0


def test_successful_git_with_unreadable_warning_is_not_clean_evidence(tmp_path, capsys):
    repo = _seed_repo(tmp_path)
    root = tmp_path / "ws"

    class WarningEngine(FakeEngine):
        def __call__(self, argv, **kwargs):
            result = super().__call__(argv, **kwargs)
            if "status" in argv and "--rm" in argv and result.returncode == 0:
                return subprocess.CompletedProcess(argv, 0, result.stdout, "warning: could not read a directory\n")
            return result

    engine = WarningEngine()
    assert _cli(root, 6615, engine, "init", "--repo-url", repo) == 0
    checkout = _new_worker(root, engine, repo, "w-a", 6617)
    capsys.readouterr()
    work = _work(root, engine, capsys, "w-a")
    assert work["readable"] is False and work["unique_work"] is True
    assert _cli(root, 6615, engine, "worker-retire", "--worker", "w-a") == 2
    assert checkout.is_dir()


def test_unknown_checkpoint_container_cleanup_blocks_reuse_and_takeover(tmp_path, capsys):
    repo = _seed_repo(tmp_path)
    root = tmp_path / "ws"

    class UnknownCleanup(FakeEngine):
        def __call__(self, argv, **kwargs):
            argv = list(argv)
            if argv[:2] == ["docker", "run"] and "--rm" in argv and any(
                "/control/checkpoints/" in item for item in argv
            ):
                raise subprocess.TimeoutExpired(argv, kwargs["timeout"])
            if argv[:2] == ["docker", "rm"] and argv[-1].startswith("epicws-git-"):
                return subprocess.CompletedProcess(argv, 1, "", "cleanup outcome unknown")
            return super().__call__(argv, **kwargs)

    engine = UnknownCleanup()
    assert _cli(root, 6615, engine, "init", "--repo-url", repo) == 0
    checkout = _new_worker(root, engine, repo, "w-a", 6617)
    (checkout / "partial.txt").write_text("keep\n")
    capsys.readouterr()
    assert _cli(root, 6615, engine, "worker-stop", "--worker", "w-a", "--reason", "r") == 2
    assert _mapping(root, 6617)["checkpoint_inspection_unknown"]
    assert "unknown checkpoint inspection" in ew.next_authorized_action(_mapping(root, 6617))["action"]
    assert _cli(root, 6615, FakeEngine(), "takeover", "--worker", "w-a", "--reason", "retry") == 2
    assert "cleanup is unknown" in capsys.readouterr().err
    assert _cli(root, 6615, FakeEngine(), "worker-start", "--worker", "w-a", "--", "sleep", "60") == 2
    assert (checkout / "partial.txt").read_text() == "keep\n"


def test_git_identity_env_is_not_needed_by_the_controller():
    assert "GIT_AUTHOR_NAME" in GIT_ENV  # fixture-side only; the controller passes its own checkpoint identity
