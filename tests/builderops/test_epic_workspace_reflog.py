"""Reflog-only work survives checkpoint, reconciliation and retirement (#6617)."""

from __future__ import annotations

import subprocess

import pytest

from app.builderops import epic_workspace as ew
from tests.builderops.test_epic_workspace_isolation import FakeEngine
from tests.builderops.test_epic_workspace_lifecycle import GIT_ENV, _git
from tests.builderops.test_epic_workspace_openhands import _main, _setup


def _entry(root):
    return ew._load_state(ew.Layout(root.resolve(), 6615))["issue_mappings"]["6617"]


def _make_orphan(checkout, mode, tmp_path):
    base = _git(checkout, "rev-parse", "HEAD")
    target = checkout
    if mode == "detached":
        _git(checkout, "checkout", "--quiet", "--detach", base)
    elif mode == "linked":
        target = tmp_path / "linked"
        _git(checkout, "worktree", "add", "--quiet", "--detach", str(target), base)
    (target / "orphan.txt").write_bytes(b"unique\r\nbytes\r\n")
    _git(target, "add", "orphan.txt")
    _git(target, "commit", "--quiet", "-m", "reflog-only work")
    orphan = _git(target, "rev-parse", "HEAD")
    if mode == "named":
        _git(target, "reset", "--quiet", "--hard", base)
    else:
        _git(target, "checkout", "--quiet", "--detach", base)
    return base, orphan


def _publish(root, engine, server, capsys, tmp_path, sha):
    import json

    capsys.readouterr()
    assert _main(root, engine, server, "publication-begin", "--worker", "w-a", "--kind", "branch_push", "--expect-sha", sha) == 0
    operation = json.loads(capsys.readouterr().out)["id"]
    result = tmp_path / "published.json"
    result.write_text(json.dumps({"branch": "b/a", "sha": sha}))
    assert _main(root, engine, server, "publication-complete", "--worker", "w-a", "--op", operation, "--result-file", str(result)) == 0
    capsys.readouterr()


@pytest.mark.parametrize("mode", ["named", "detached", "linked"])
def test_reflog_only_commit_retained_until_published_then_retired(tmp_path, capsys, mode):
    root, engine, server = _setup(tmp_path, capsys)
    layout = ew.Layout(root.resolve(), 6615)
    checkout = layout.checkout("w-a")
    engine.containers["unrelated-svc"] = "running"
    base, orphan = _make_orphan(checkout, mode, tmp_path)
    assert _git(checkout, "rev-parse", "HEAD") == base
    assert orphan not in _git(checkout, "for-each-ref", "--format=%(objectname)").split()
    capsys.readouterr()
    assert _main(root, engine, server, "worker-retire", "--worker", "w-a") == 2
    assert checkout.is_dir() and engine.containers["unrelated-svc"] == "running"
    record = _entry(root)["checkpoints"][-1]
    assert orphan in record["retained_reflog"]
    assert _entry(root)["work_at_stop"]["unpublished_total"] >= 1

    # The controller's store remains complete with the original object directory unavailable.
    objects = checkout / ".git" / "objects"
    saved = checkout / ".git" / "objects-fixture-saved"
    objects.rename(saved)
    try:
        checkpoint_repo = layout.epic_dir / "control" / "checkpoints" / "w-a.git"
        result = subprocess.run(
            ["git", "--git-dir", str(checkpoint_repo), "show", f"refs/retained/{orphan}:orphan.txt"],
            capture_output=True, check=True, env={**GIT_ENV, "GIT_ALTERNATE_OBJECT_DIRECTORIES": ""},
        )
        assert result.stdout == b"unique\r\nbytes\r\n"
        assert ew._checkpoint_present(checkout, checkpoint_repo, record, engine, ew.DEFAULT_IMAGE)
    finally:
        saved.rename(objects)

    capsys.readouterr()
    assert _main(root, engine, server, "checkpoint-release", "--worker", "w-a", "--ref", record["ref"], "--published-commit", base) == 2
    assert "retained commits not published" in capsys.readouterr().err
    _publish(root, engine, server, capsys, tmp_path, orphan)
    assert _main(root, engine, server, "checkpoint-release", "--worker", "w-a", "--ref", record["ref"], "--published-commit", orphan) == 0
    capsys.readouterr()
    if mode == "linked":
        assert _main(root, engine, server, "worker-retire", "--worker", "w-a") == 2
        assert checkout.is_dir() and (tmp_path / "linked").is_dir()
    else:
        assert _main(root, engine, server, "worker-retire", "--worker", "w-a") == 0
        assert not checkout.exists()
    assert engine.containers["unrelated-svc"] == "running"


@pytest.mark.parametrize("damage", ["malformed", "malformed-header", "zero-entry", "missing", "unreadable", "unreadable-ref", "missing-object"])
def test_bad_reflog_evidence_fences_takeover_and_retirement(tmp_path, capsys, damage):
    root, engine, server = _setup(tmp_path, capsys)
    layout = ew.Layout(root.resolve(), 6615)
    checkout = layout.checkout("w-a")
    log = checkout / ".git" / "logs" / "HEAD"
    if damage == "malformed":
        with log.open("ab") as out:
            out.write(b"broken entry\n")
    elif damage == "malformed-header":
        head = _git(checkout, "rev-parse", "HEAD")
        with log.open("ab") as out:
            out.write(f"{head} {head} broken-identity\tmessage 1 +0000\n".encode())
    elif damage == "zero-entry":
        with log.open("ab") as out:
            out.write(f"{'0' * 40} {'0' * 40} fixture <f@example.invalid> 1 +0000\n".encode())
    elif damage == "missing":
        log.rename(log.with_name("HEAD.saved"))
    elif damage == "unreadable":
        log.chmod(0)
    elif damage == "unreadable-ref":
        (checkout / ".git" / "refs" / "heads" / "b" / "a").chmod(0)
    else:
        head = _git(checkout, "rev-parse", "HEAD")
        with log.open("ab") as out:
            out.write(f"{head} {'f' * 40} fixture <f@example.invalid> 1 +0000\tmissing\n".encode())
    assert ew.inspect_checkout(layout, "w-a", runner=engine)["readable"] is False
    capsys.readouterr()
    assert _main(root, engine, server, "takeover", "--worker", "w-a", "--reason", "r") == 2
    assert _main(root, engine, server, "worker-retire", "--worker", "w-a") == 2
    assert checkout.is_dir() and not _entry(root).get("checkpoints")


def _unreachable_commit(checkout):
    head = _git(checkout, "rev-parse", "HEAD")
    tree = _git(checkout, "rev-parse", "HEAD^{tree}")
    orphan = _git(checkout, "commit-tree", tree, "-p", head, "-m", "new reflog work")
    return head, orphan


def test_old_side_of_reflog_entry_alone_is_preserved(tmp_path, capsys):
    root, engine, server = _setup(tmp_path, capsys)
    checkout = ew.Layout(root.resolve(), 6615).checkout("w-a")
    _, orphan = _make_orphan(checkout, "named", tmp_path)
    for path in (checkout / ".git" / "logs" / "HEAD", checkout / ".git" / "logs" / "refs" / "heads" / "b" / "a"):
        lines = path.read_bytes().splitlines(keepends=True)
        path.write_bytes(b"".join(line for line in lines if line.split(b" ", 2)[1] != orphan.encode()))
        assert any(line.startswith(orphan.encode() + b" ") for line in path.read_bytes().splitlines())
    capsys.readouterr()
    assert _main(root, engine, server, "worker-retire", "--worker", "w-a") == 2
    assert checkout.is_dir() and orphan in _entry(root)["checkpoints"][-1]["retained_reflog"]


def _name_only_in_reflog(checkout, head, orphan):
    _git(checkout, "update-ref", "-m", "temporary", "refs/heads/b/a", orphan, head)
    _git(checkout, "update-ref", "-m", "restore", "refs/heads/b/a", head, orphan)


@pytest.mark.parametrize("phase", ["checkpoint", "authorization"])
def test_reflog_race_with_same_head_and_refs_requires_new_takeover(tmp_path, capsys, phase):
    root, engine, server = _setup(tmp_path, capsys)
    checkout = ew.Layout(root.resolve(), 6615).checkout("w-a")
    (checkout / "partial.py").write_text("checkpointed\n")
    head, orphan = _unreachable_commit(checkout)

    class RacingEngine(FakeEngine):
        armed = False
        changed = False

        def __call__(self, argv, **kwargs):
            argv = list(argv)
            result = super().__call__(argv, **kwargs)
            if phase == "checkpoint" and not self.changed and argv[:2] == ["docker", "create"] and "--rm" in argv:
                self.changed = True
                _name_only_in_reflog(checkout, head, orphan)
            if phase == "authorization" and "fsck" in argv and any("target=/scratch,readonly" in a for a in argv):
                self.armed = True
            if (phase == "authorization" and self.armed and not self.changed and argv[:2] == ["docker", "ps"]
                    and any("label=epic-workspace.worker=w-a" in a for a in argv)):
                self.changed = True
                _name_only_in_reflog(checkout, head, orphan)
            return result

    racing = RacingEngine()
    capsys.readouterr()
    assert _main(root, racing, server, "takeover", "--worker", "w-a", "--reason", "r") == 2
    assert racing.changed and _git(checkout, "rev-parse", "HEAD") == head
    assert orphan not in _git(checkout, "for-each-ref", "--format=%(objectname)").split()
    assert _entry(root)["takeover"]["status"] == "required"
    assert _main(root, engine, server, "worker-start", "--worker", "w-a", "--", "sleep", "60") == 2
    assert _main(root, engine, server, "takeover", "--worker", "w-a", "--reason", "capture later work") == 0
    assert orphan in _entry(root)["checkpoints"][-1]["retained_reflog"]


def test_reflog_race_before_retirement_keeps_checkout_and_reconciles(tmp_path, capsys):
    root, engine, server = _setup(tmp_path, capsys)
    checkout = ew.Layout(root.resolve(), 6615).checkout("w-a")
    head, orphan = _unreachable_commit(checkout)

    class RacingEngine(FakeEngine):
        changed = False

        def __call__(self, argv, **kwargs):
            result = super().__call__(argv, **kwargs)
            if not self.changed and "rev-list" in argv and "--count" in argv and "--all" in argv:
                self.changed = True
                _name_only_in_reflog(checkout, head, orphan)
            return result

    racing = RacingEngine()
    capsys.readouterr()
    assert _main(root, racing, server, "worker-retire", "--worker", "w-a") == 2
    assert racing.changed and checkout.is_dir() and _git(checkout, "rev-parse", "HEAD") == head
    assert not _entry(root).get("checkpoints")
    assert _main(root, engine, server, "worker-retire", "--worker", "w-a") == 2
    assert checkout.is_dir() and orphan in _entry(root)["checkpoints"][-1]["retained_reflog"]


@pytest.mark.parametrize("caller", ["worker-start", "openhands-start", "worker-create"])
def test_reflog_change_fences_authorized_checkout_consumers(tmp_path, capsys, caller):
    root, engine, server = _setup(tmp_path, capsys)
    checkout = ew.Layout(root.resolve(), 6615).checkout("w-a")
    (checkout / "partial.py").write_text("before\n")
    assert _main(root, engine, server, "takeover", "--worker", "w-a", "--reason", "r") == 0
    head, orphan = _unreachable_commit(checkout)
    _name_only_in_reflog(checkout, head, orphan)
    args = {
        "worker-start": (caller, "--worker", "w-a", "--", "sleep", "60"),
        "openhands-start": (caller, "--worker", "w-a"),
        "worker-create": (caller, "--worker", "w-a", "--issue", "6617", "--branch", "b/a", "--next-action", "implement"),
    }[caller]
    capsys.readouterr()
    assert _main(root, engine, server, *args) == 2
    assert _entry(root)["takeover"]["status"] == "required" and not engine.runs()
    assert _main(root, engine, server, "takeover", "--worker", "w-a", "--reason", "refresh") == 0
    assert orphan in _entry(root)["checkpoints"][-1]["retained_reflog"]


def test_repeated_takeover_reconciles_reflog_only_change(tmp_path, capsys):
    root, engine, server = _setup(tmp_path, capsys)
    checkout = ew.Layout(root.resolve(), 6615).checkout("w-a")
    (checkout / "partial.py").write_text("before\n")
    assert _main(root, engine, server, "takeover", "--worker", "w-a", "--reason", "r") == 0
    generation = _entry(root)["takeover"]["generation"]
    head, orphan = _unreachable_commit(checkout)
    _name_only_in_reflog(checkout, head, orphan)
    capsys.readouterr()
    assert _main(root, engine, server, "takeover", "--worker", "w-a", "--reason", "refresh") == 0
    entry = _entry(root)
    assert entry["takeover"]["generation"] == generation + 1
    assert orphan in entry["checkpoints"][-1]["retained_reflog"]


def test_checkpoint_rejects_mismatched_retained_ref_and_empty_manifest(tmp_path, capsys):
    root, engine, server = _setup(tmp_path, capsys)
    layout = ew.Layout(root.resolve(), 6615)
    checkout = layout.checkout("w-a")
    base, orphan = _make_orphan(checkout, "named", tmp_path)
    assert _main(root, engine, server, "worker-stop", "--worker", "w-a", "--reason", "r") == 0
    record = _entry(root)["checkpoints"][-1]
    _publish(root, engine, server, capsys, tmp_path, orphan)
    ew._mutate_mapping(layout, "w-a", lambda entry: entry["checkpoints"][-1].update(
        retained_reflog=[], reflog_fingerprint=ew._reflog_identity(record["reflog_content_fingerprint"], []),
    ))
    assert _main(root, engine, server, "checkpoint-release", "--worker", "w-a", "--ref", record["ref"], "--published-commit", orphan) == 2
    assert "unreadable" in capsys.readouterr().err
    ew._mutate_mapping(layout, "w-a", lambda entry: entry["checkpoints"].__setitem__(-1, record))
    ew._mutate_mapping(layout, "w-a", lambda entry: entry["checkpoints"][-1].update(retained_refs=[]))
    assert _main(root, engine, server, "checkpoint-release", "--worker", "w-a", "--ref", record["ref"], "--published-commit", orphan) == 2
    assert "unreadable" in capsys.readouterr().err
    ew._mutate_mapping(layout, "w-a", lambda entry: entry["checkpoints"].__setitem__(-1, record))
    repo = layout.epic_dir / "control" / "checkpoints" / "w-a.git"
    subprocess.run(["git", "--git-dir", str(repo), "update-ref", f"refs/retained/{orphan}", base], check=True, env=GIT_ENV)
    assert _main(root, engine, server, "checkpoint-release", "--worker", "w-a", "--ref", record["ref"], "--published-commit", orphan) == 2
    assert "unreadable" in capsys.readouterr().err
    assert _main(root, engine, server, "worker-retire", "--worker", "w-a") == 2
    assert checkout.is_dir() and _entry(root)["checkpoints"][-1]["status"] == "preserved"


def test_interrupted_checkpoint_adopts_only_after_reflog_objects_are_retained(tmp_path, capsys):
    root, engine, server = _setup(tmp_path, capsys)
    checkout = ew.Layout(root.resolve(), 6615).checkout("w-a")
    _, orphan = _make_orphan(checkout, "named", tmp_path)

    class InterruptedEngine(FakeEngine):
        failed = False

        def __call__(self, argv, **kwargs):
            if not self.failed and "fsck" in argv and "--rm" in argv:
                self.failed = True
                return subprocess.CompletedProcess(argv, 1, "", "interrupted")
            return super().__call__(argv, **kwargs)

    interrupted = InterruptedEngine()
    capsys.readouterr()
    assert _main(root, interrupted, server, "worker-checkpoint", "--worker", "w-a", "--reason", "r") == 2
    assert interrupted.failed and checkout.is_dir() and not _entry(root).get("checkpoints")
    assert _main(root, engine, server, "worker-checkpoint", "--worker", "w-a", "--reason", "retry") == 0
    record = _entry(root)["checkpoints"][-1]
    assert record["adopted"] is True and orphan in record["retained_reflog"]
