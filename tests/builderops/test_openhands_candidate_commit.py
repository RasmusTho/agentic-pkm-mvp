"""Real publisher Git, checkpoint and branch gate; synthetic authority/container ports."""

import json
import os
import subprocess
import sys

import pytest

from app.builderops import epic_workspace as ew
from app.builderops import openhands_pr_completion as completion
from app.builderops import openhands_pr_cycle as cycle
from app.builderops import publication
from tests.builderops.test_epic_workspace_isolation import FakeEngine, _cli, _seed_repo
from tests.builderops.test_epic_workspace_lifecycle import _ckpt, _git, _new_worker


def fixture(tmp_path, capsys, monkeypatch, *, directory_transition=False, configured_filter=False,
            test_source="def test_example(): pass\n"):
    monkeypatch.setenv("GIT_AUTHOR_NAME", "Synthetic Builder")
    monkeypatch.setenv("GIT_AUTHOR_EMAIL", "builder@example.invalid")
    monkeypatch.setenv("GIT_COMMITTER_NAME", "Synthetic Builder")
    monkeypatch.setenv("GIT_COMMITTER_EMAIL", "builder@example.invalid")
    repo = _seed_repo(tmp_path)
    origin = tmp_path / "origin"
    (origin / "remove.py").write_text("original\n")
    (origin / ".gitignore").write_text("*.cache\n")
    (origin / "tests").mkdir()
    (origin / "tests" / "example.py").write_text(test_source)
    _git(origin, "add", "remove.py", ".gitignore", "tests/example.py")
    _git(origin, "commit", "-m", "fixture base")
    main = tmp_path / "publisher-main"
    publisher = tmp_path / "publisher"
    subprocess.run(["git", "clone", "--quiet", repo, str(main)], check=True)
    _git(main, "worktree", "add", "-b", "b/a", str(publisher), "origin/main")
    (publisher / "publisher.cache").write_text("publisher ignored work\n")
    root, engine = tmp_path / "ws", FakeEngine()
    assert _cli(root, 6615, engine, "init", "--repo-url", repo) == 0
    checkout = _new_worker(root, engine, repo, "w-a", 6617)
    assert _cli(root, 6615, engine, "worker-start", "--worker", "w-a", "--", "sleep", "60") == 0
    (checkout / "README.md").write_bytes(b"physical\r\nrepair\r\n")
    (checkout / "remove.py").unlink()
    if directory_transition:
        (checkout / "remove.py").mkdir()
        (checkout / "remove.py" / "child.py").write_text("child\n")
    (checkout / "new.py").write_text("candidate\n")
    (checkout / "new.py").chmod(0o755)
    (checkout / "link.py").symlink_to("new.py")
    (checkout / ".gitignore").write_text("*.cache\n")
    (checkout / "private.cache").write_text("ignored unique work\n")
    if configured_filter:
        cleaner = tmp_path / "filter.sh"
        cleaner.write_text(f"#!/bin/sh\ntouch {tmp_path / 'filter-ran'}\ncat\n")
        cleaner.chmod(0o755)
        _git(main, "config", "filter.evil.clean", str(cleaner))
        (checkout / ".gitattributes").write_text("* filter=evil\n")
    capsys.readouterr()
    assert _cli(root, 6615, engine, "worker-stop", "--worker", "w-a", "--reason", "repair complete") == 0
    work = json.loads(capsys.readouterr().out)["work_at_stop"]
    layout = ew.Layout(root.resolve(), 6615)
    conversation = {"id": "author-1", "operation_id": "repair-1", "status": ew.CONVERSATION_ENDED}
    ew._record_worker(layout, 6617, conversation=conversation, lifecycle_owner="owner-6617",
                      builder_session="session-6617")
    mapping = cycle._mapping(layout, "w-a")
    old = work["head"]
    assert _git(publisher, "rev-parse", "HEAD") == old
    issue_body = "## Acceptance Criteria\n\n- [ ] Works.\n  - Verify: `tests/example.py::test_example`\n"
    body = "Governing-Issue: #6617\nFixes #6617\n"
    pr = {"number": 10, "head_sha": old, "title": "Repair", "body": body, "labels": [],
          "draft": False, "restrictions": [], "governing_issue": {"body": issue_body, "state": "open"}}
    entry = {"number": 10, "worker": "w-a", "claimant": "owner-6617", "session": "session-6617",
             "lease_id": "lease-1", "owner_worktree": str(publisher.resolve()), "lifecycle_repo": str(main.resolve())}
    registration = {"path": str(publisher.resolve()), "branch": "b/a", "owner": "session-6617",
                    "generation": "1" * 32, "registration_epoch": "2" * 32,
                    "expires_at": 9999999999, "registered_at": 100.0}
    task_id = cycle.github_issue_task_id(completion.REPOSITORY, 6617)
    task = {"task_id": task_id, "repo": completion.REPOSITORY, "issue_number": 6617, "status": "claimed",
            "claimed_by": "owner-6617", "lease_id": "lease-1", "lease_expires_at": "2099-01-01T00:00:00Z",
            "linked_pr": 10}
    lease = {"lease_id": "lease-1", "holder": "owner-6617", "resource": "issue:6617",
             "expires_at": task["lease_expires_at"], "released_at": None}
    events = [{"task_id": task_id, "event_type": "task.claimed", "actor": "owner-6617", "lease_id": "lease-1",
               "timestamp": "2026-11-13T00:00:00Z", "payload": {"session": "session-6617", "ttl_minutes": 90}}]

    class ExternalAuthority:
        def __init__(self, **kwargs):
            pass

        def run(self, argv, *, cwd, input_text=None):
            if argv[0] == "gh" and "user" in argv:
                return publication.CommandResult(tuple(argv), 0, "RasmusTho\n", "")
            if argv[0] == sys.executable and "verification-status" in argv:
                return publication.CommandResult(tuple(argv), 0, '{"ok":true,"runs":[]}', "")
            raise AssertionError(argv)

    monkeypatch.setattr(cycle, "SubprocessExecutor", ExternalAuthority)
    monkeypatch.setattr(cycle, "_worker_runner", engine)
    monkeypatch.setattr(cycle, "_lifecycle_owner", lambda *args: (registration, {}))
    monkeypatch.setattr(cycle, "_api_pages", lambda *args: [])
    monkeypatch.setattr(cycle.closure, "_api", lambda *args: {"full_name": completion.REPOSITORY,
                                                               "default_branch": "main"})
    monkeypatch.setattr(cycle.closure, "_pr", lambda *args: {"number": 10, "state": "open", "draft": False,
        "title": "Repair", "body": body, "labels": [],
        "head": {"sha": old, "ref": "b/a", "repo": {"full_name": completion.REPOSITORY}},
        "base": {"ref": "main", "sha": old}})
    monkeypatch.setattr(cycle.closure, "_issue", lambda *args: {"number": 6617, "state": "open",
        "title": "Repair", "body": issue_body, "labels": [{"name": "agent:in-progress"}]})
    monkeypatch.setattr(cycle.closure, "_closing_issue_references", lambda *args: [6617])
    monkeypatch.setattr(cycle.closure, "_dispatcher_inspect", lambda *args: (task, events, lease))
    actual_run = subprocess.run

    def transport(argv, **kwargs):
        if argv[0] == "docker":
            if argv[1] == "inspect" and "--format" not in argv:
                return subprocess.CompletedProcess(argv, 1, "", "No such object: synthetic")
            return engine(argv, **kwargs)
        return actual_run(argv, **kwargs)

    monkeypatch.setattr(subprocess, "run", transport)
    authority = cycle.native_authority(layout, pr, entry, purpose="repair")
    stop = {"stop_id": work["stop_id"], "previous_stop_id": None, "checkpoint": work["checkpoint"],
            "container_id": mapping["container_id"], "assignment": ew.assignment_of(mapping)}
    proof = {"container_id": mapping["container_id"], "conversation_id": "author-1", "operation_id": "repair-1"}
    saved = {"kind": "pr_cycle", "number": 10, "identity": "fixture-identity", "repair_operation": "repair-1",
             "repair_stop_intent": stop, "repair_stop_verified": True, "repair_authority_binding": authority,
             "repair_owner_binding": {"lifecycle_owner": "owner-6617", "owner": None,
                                      "builder_session": "session-6617"}, "repair_execution_proof": proof,
             "repair_result": {"status": "pending_trusted_publication", "identity": "fixture-identity",
                               "head_sha": old, "operation_id": "repair-1", "work_at_stop": work,
                               "native_proof": proof}}
    cycle._save(layout, saved, expected_worker="w-a", expected_assignment=mapping)
    return layout, checkout, publisher, engine, pr, entry, saved, mapping, lease


def run_commit(data, executor=None):
    layout, _, _, _, pr, entry, saved, mapping, _ = data
    with cycle._single_advancement(layout), ew._worker_lifecycle_lock(layout, "w-a"):
        return cycle._prepare_stopped_repair_commit_locked(layout, "w-a", pr, entry, saved, mapping,
                                                           executor=executor or publication.SubprocessExecutor())


def test_real_candidate_commit_and_replay_preserve_ignored_source(tmp_path, capsys, monkeypatch):
    data = fixture(tmp_path, capsys, monkeypatch)
    result = run_commit(data)
    assert result["status"] == "complete"
    assert _git(data[2], "rev-parse", "HEAD") == result["head"]
    assert _git(data[2], "rev-parse", "HEAD^{tree}") == result["intent"]["tree"]
    assert _git(data[2], "rev-list", "--count", f"{data[4]['head_sha']}..HEAD") == "1"
    assert _git(data[2], "rev-parse", "HEAD^") == data[4]["head_sha"]
    assert (data[2] / "README.md").read_bytes() == b"physical\r\nrepair\r\n"
    assert (data[2] / "new.py").stat().st_mode & 0o111
    assert (data[2] / "link.py").is_symlink() and os.readlink(data[2] / "link.py") == "new.py"
    assert not (data[2] / "remove.py").exists()
    assert not (data[2] / "private.cache").exists()
    assert (data[2] / "publisher.cache").read_text() == "publisher ignored work\n"
    assert (data[1] / "private.cache").read_text() == "ignored unique work\n"
    ref = data[6]["repair_stop_intent"]["checkpoint"]["ref"]
    assert _ckpt(data[0].root, "w-a", "show", f"{ref}:private.cache") == "ignored unique work"
    assert run_commit(data)["head"] == result["head"]
    assert _git(data[2], "rev-list", "--count", f"{data[4]['head_sha']}..HEAD") == "1"


def test_file_directory_transition_holds_without_publisher_loss(tmp_path, capsys, monkeypatch):
    data = fixture(tmp_path, capsys, monkeypatch, directory_transition=True)
    with pytest.raises(cycle.CycleError, match="file/directory transition"):
        run_commit(data)
    assert _git(data[2], "rev-parse", "HEAD") == data[4]["head_sha"]
    assert (data[2] / "remove.py").read_text() == "original\n"
    assert (data[2] / "publisher.cache").read_text() == "publisher ignored work\n"


def test_unresolved_prior_publication_holds_without_publisher_write(tmp_path, capsys, monkeypatch):
    data = fixture(tmp_path, capsys, monkeypatch)
    ew._record_worker(data[0], 6617, publication_ops=[{"id": "prior", "status": "intended"}])
    with pytest.raises(cycle.CycleError, match="publication remains unresolved"):
        run_commit(data)
    assert _git(data[2], "rev-parse", "HEAD") == data[4]["head_sha"]
    assert (data[2] / "README.md").read_text() == "fixture\n"
    assert (data[2] / "publisher.cache").read_text() == "publisher ignored work\n"


def test_configured_filter_holds_without_running_host_filter(tmp_path, capsys, monkeypatch):
    data = fixture(tmp_path, capsys, monkeypatch, configured_filter=True)
    with pytest.raises(cycle.CycleError, match="filter requires contained"):
        run_commit(data)
    assert not (tmp_path / "filter-ran").exists()
    assert _git(data[2], "rev-parse", "HEAD") == data[4]["head_sha"]
    assert (data[2] / "publisher.cache").read_text() == "publisher ignored work\n"


def test_applied_commit_with_lost_reply_is_reconciled(tmp_path, capsys, monkeypatch):
    data = fixture(tmp_path, capsys, monkeypatch)

    class LostReply(publication.SubprocessExecutor):
        def run(self, argv, *, cwd, input_text=None):
            result = super().run(argv, cwd=cwd, input_text=input_text)
            if "commit" in argv and result.returncode == 0:
                return publication.CommandResult(tuple(argv), 125, "", "synthetic reply lost")
            return result

    result = run_commit(data, LostReply())
    assert run_commit(data)["head"] == result["head"]
    assert _git(data[2], "rev-list", "--count", f"{data[4]['head_sha']}..HEAD") == "1"


def test_unknown_unapplied_commit_is_held_without_duplicate(tmp_path, capsys, monkeypatch):
    data = fixture(tmp_path, capsys, monkeypatch)

    class UnknownReply(publication.SubprocessExecutor):
        def run(self, argv, *, cwd, input_text=None):
            if "commit" in argv:
                return publication.CommandResult(tuple(argv), 125, "", "synthetic unknown commit")
            return super().run(argv, cwd=cwd, input_text=input_text)

    with pytest.raises(cycle.CycleError, match="commit outcome unresolved"):
        run_commit(data, UnknownReply())
    assert _git(data[2], "rev-parse", "HEAD") == data[4]["head_sha"]
    with pytest.raises(cycle.CycleError, match="commit outcome is unresolved"):
        run_commit(data)
    assert _git(data[2], "rev-parse", "HEAD") == data[4]["head_sha"]
    assert (data[2] / "publisher.cache").read_text() == "publisher ignored work\n"


def test_interrupted_new_file_link_reconciles_owned_temporary(tmp_path, capsys, monkeypatch):
    data = fixture(tmp_path, capsys, monkeypatch)
    original_link = os.link
    failed = False

    def lost_link_reply(src, dst, **kwargs):
        nonlocal failed
        result = original_link(src, dst, **kwargs)
        if not failed and os.fsdecode(src).startswith(".6618-prep-"):
            failed = True
            raise OSError("synthetic interruption after link")
        return result

    monkeypatch.setattr(os, "link", lost_link_reply)
    with pytest.raises(cycle.CycleError, match="materialization stopped"):
        run_commit(data)
    monkeypatch.setattr(os, "link", original_link)
    data[6].clear()
    data[6].update(cycle._find(data[0], 10, "fixture-identity"))
    result = run_commit(data)
    assert result["status"] == "complete"
    assert _git(data[2], "rev-list", "--count", f"{data[4]['head_sha']}..HEAD") == "1"
    assert (data[2] / "publisher.cache").read_text() == "publisher ignored work\n"


def test_replacing_tracked_file_preserves_ignored_hardlink(tmp_path, capsys, monkeypatch):
    data = fixture(tmp_path, capsys, monkeypatch)
    ignored = data[2] / "publisher.cache"
    ignored.unlink()
    os.link(data[2] / "README.md", ignored)
    before = ignored.read_bytes()
    assert run_commit(data)["status"] == "complete"
    assert ignored.read_bytes() == before
    assert (data[2] / "README.md").read_bytes() == b"physical\r\nrepair\r\n"


@pytest.mark.parametrize("phase", ["materialized", "staged"])
def test_interrupted_materialization_or_staging_resumes_same_intent(tmp_path, capsys, monkeypatch, phase):
    data = fixture(tmp_path, capsys, monkeypatch)

    class Interrupt(publication.SubprocessExecutor):
        gates = 0
        interrupted = False

        def run(self, argv, *, cwd, input_text=None):
            result = super().run(argv, cwd=cwd, input_text=input_text)
            if argv[0] == "env" and any("agent_workspace_preflight.sh" in part for part in argv):
                self.gates += 1
                if phase == "materialized" and self.gates == 2 and result.returncode == 0:
                    return publication.CommandResult(tuple(argv), 125, "", "synthetic interrupted gate reply")
            if phase == "staged" and "update-index" in argv and not self.interrupted and result.returncode == 0:
                self.interrupted = True
                return publication.CommandResult(tuple(argv), 125, "", "synthetic interrupted staging reply")
            return result

    with pytest.raises(publication.PublicationCommandError):
        run_commit(data, Interrupt())
    assert _git(data[2], "rev-parse", "HEAD") == data[4]["head_sha"]
    data[6].clear()
    data[6].update(cycle._find(data[0], 10, "fixture-identity"))
    result = run_commit(data)
    assert result["status"] == "complete"
    assert _git(data[2], "rev-list", "--count", f"{data[4]['head_sha']}..HEAD") == "1"
    assert (data[2] / "publisher.cache").read_text() == "publisher ignored work\n"


@pytest.mark.parametrize("drift", ["dirty", "authority", "ignored-collision"])
def test_dirty_or_foreign_authority_refuses_without_overwrite(tmp_path, capsys, monkeypatch, drift):
    data = fixture(tmp_path, capsys, monkeypatch)
    if drift == "dirty":
        (data[2] / "README.md").write_text("publisher unique work\n")
    elif drift == "authority":
        data[8]["holder"] = "foreign-owner"
    else:
        (tmp_path / "publisher-main" / ".git" / "info" / "exclude").write_text("new.py\n")
        (data[2] / "new.py").write_text("publisher ignored collision\n")
    with pytest.raises((cycle.CycleError, publication.PublicationRefusal)):
        run_commit(data)
    assert _git(data[2], "rev-parse", "HEAD") == data[4]["head_sha"]
    if drift == "dirty":
        assert (data[2] / "README.md").read_text() == "publisher unique work\n"
    if drift == "ignored-collision":
        assert (data[2] / "new.py").read_text() == "publisher ignored collision\n"
    assert (data[1] / "private.cache").read_text() == "ignored unique work\n"
