import fcntl
import json
import threading
from datetime import datetime, timedelta, timezone
from pathlib import Path
from types import SimpleNamespace

import pytest

from app.builderops import openhands_delivery as delivery
from app.builderops import openhands_factory as factory
from app.builderops import openhands_service as service
from app.builderops import openhands_watcher as watcher
from app.builderops import publication
from tests.scripts.test_publication import BODY_INPUTS

REAL_KEEPER = watcher._LeaseKeeper


def test_authorized_worker_prompt_requests_only_local_handoff():
    plan = {"repository": delivery.REPOSITORY, "issue": {"number": 5230, "title": "Feature",
            "body": "Issue scope"}, "instructions": {"AGENTS.md": {"content": "Instructions"}}}
    prompt = delivery._task_prompt(plan, auto_finish=True)
    assert watcher.HANDOFF in prompt and "risk_surfaces" in prompt and "paths" in prompt
    assert "Do not claim, commit, push, publish, merge" in prompt
    assert "Issue scope" in prompt and "Instructions" in prompt
    assert watcher.HANDOFF not in delivery._task_prompt(plan)


def test_launch_preserves_dispatcher_paths_without_provider_keys(tmp_path, monkeypatch):
    directory = tmp_path / "run"
    directory.mkdir(mode=0o700)
    monkeypatch.setenv("DISPATCHER_DB_PATH", "/host/dispatcher.sqlite3")
    monkeypatch.setenv("OPENAI_API_KEY", "must-not-be-forwarded")
    captured = {}
    monkeypatch.setattr(watcher.subprocess, "Popen", lambda command, **kwargs: captured.update(kwargs))
    watcher.launch(tmp_path, directory, 5230, tmp_path, tmp_path)
    assert captured["env"]["DISPATCHER_DB_PATH"] == "/host/dispatcher.sqlite3"
    assert "OPENAI_API_KEY" not in captured["env"]
    assert captured["start_new_session"] is True


@pytest.fixture
def authorized_run(tmp_path, monkeypatch):
    directory = tmp_path / "run"
    directory.mkdir(mode=0o700)
    worktree = tmp_path / "worktrees" / "issue-5230"
    worktree.mkdir(parents=True)
    local = worktree / ".codex-tmp"
    local.mkdir()
    branch = "codex/publication-test"
    receipt = BODY_INPUTS["pickup_receipt"].replace("/tmp/publication-test", str(worktree))
    state = {"version": 1, "kind": "openhands_delivery_run.v1", "phase": "active",
             "auto_finish": True, "issue": 5230, "repository": delivery.REPOSITORY,
             "root": str(factory.FACTORY_ROOT), "worktree": str(worktree), "branch": branch,
             "base_commit": "a" * 40, "pickup_receipt": receipt}
    service._write(directory, state)
    handoff = {"version": 1, "issue": 5230, "title": "Implement feature", "paths": ["feature.py"],
               "risk_surfaces": ["auth"], "body": {key: BODY_INPUTS[key] for key in watcher.BODY_FIELDS}}
    path = local / "openhands-finish.json"
    path.write_text(json.dumps(handoff))
    path.chmod(0o600)
    (worktree / "feature.py").write_text("change\n")
    calls = []

    class Runner:
        staged = False
        committed = False

        def run(self, argv, *, cwd, input_text=None):
            command = tuple(argv)
            calls.append(command)
            output, code = "", 0
            if command[-2:] == ("rev-parse", "--show-toplevel"):
                output = str(worktree)
            elif command[-2:] == ("branch", "--show-current"):
                output = branch
            elif command[-2:] == ("rev-parse", "HEAD"):
                output = "a" * 40
            elif command[:2] == ("git", "check-ignore"):
                pass
            elif command[:2] == ("git", "ls-files") and "--error-unmatch" in command:
                code = 1
            elif command[:3] == ("git", "diff", "--name-only"):
                cached = "--cached" in command
                output = "feature.py\0" if self.staged == cached else ""
            elif command[:2] == ("git", "ls-files") and "--others" in command:
                pass
            elif "check-attr" in command:
                output = "feature.py\0filter\0unspecified\0"
            elif "add" in command:
                self.staged = True
            elif "commit" in command:
                self.committed = True
            elif "agent_workspace_preflight.sh" in command[0]:
                pass
            else:
                pytest.fail(f"Unexpected command: {command}")
            return publication.CommandResult(command, code, output, "")

    runner = Runner()
    monkeypatch.setattr(delivery, "DraftOnlyExecutor", lambda *args: runner)
    monkeypatch.setattr(delivery, "_conversation", lambda *args: {"execution_status": "finished"})
    monkeypatch.setattr(delivery, "_finished_run", lambda *args: state)
    monkeypatch.setattr(delivery, "_full_claim_readback", lambda *args: calls.append(("claim-readback",)))
    monkeypatch.setattr(factory, "_candidate_head", lambda *args: "b" * 40)

    class Keeper:
        def __init__(self, state, watch_dir):
            self.state = state
            self.error = None
            self.lock = threading.RLock()

        def start(self):
            pass

        def check(self):
            pass

        def close(self):
            pass

    monkeypatch.setattr(watcher, "_LeaseKeeper", Keeper)
    return directory, worktree, state, handoff, runner, calls


def test_watcher_commits_scoped_changes_and_runs_finish_once(authorized_run, monkeypatch):
    directory, worktree, state, handoff, runner, calls = authorized_run
    finished = []

    def finish(*args, **kwargs):
        finished.append(args)
        return {"pr_number": 1234, "commit_sha": "b" * 40, "checks": {"combined_status": "pending"}}

    monkeypatch.setattr(factory, "_finish", finish)
    arguments = (Path("/install"), directory, state["issue"], factory.FACTORY_ROOT, worktree.parent)
    watcher.run(*arguments)
    assert runner.committed and len(finished) == 1
    assert finished[0][-4:-1] == (handoff["title"], {**handoff["body"], "lane": "implementation",
        "final_review_rounds": 1, "issue_number": 5230, "pickup_receipt": state["pickup_receipt"]},
        handoff["risk_surfaces"])
    assert calls.index(("claim-readback",)) < next(i for i, call in enumerate(calls) if "add" in call)
    assert any("agent_workspace_preflight.sh" in call[0] and "--allow-dirty" in call for call in calls)
    assert any("commit" in call and "core.hooksPath=/dev/null" in call for call in calls)
    assert watcher.status(directory)["status"] == "finished"
    watcher.run(*arguments)
    assert len(finished) == 1 and sum("commit" in call for call in calls) == 1


def test_watcher_accepts_explicit_empty_risk_assessment(authorized_run, monkeypatch):
    directory, worktree, state, handoff, _, _ = authorized_run
    handoff["risk_surfaces"] = []
    (worktree / watcher.HANDOFF).write_text(json.dumps(handoff))
    received = []

    def finish(*args, **kwargs):
        received.append(args[-2])
        return {"pr_number": 1234, "commit_sha": "b" * 40, "checks": {}}

    monkeypatch.setattr(factory, "_finish", finish)
    watcher.run(Path("/install"), directory, state["issue"], factory.FACTORY_ROOT, worktree.parent)
    assert received == [[]] and watcher.status(directory)["status"] == "finished"


def test_watcher_retries_publication_without_repeating_commit(authorized_run, monkeypatch):
    directory, worktree, state, _, _, calls = authorized_run
    attempts = []

    def finish(*args, **kwargs):
        attempts.append(args)
        if len(attempts) == 1:
            raise delivery.DeliveryError("Publication outcome needs reconciliation")
        return {"pr_number": 1234, "commit_sha": "b" * 40, "checks": {}}

    monkeypatch.setattr(factory, "_finish", finish)
    arguments = (Path("/install"), directory, state["issue"], factory.FACTORY_ROOT, worktree.parent)
    watcher.run(*arguments)
    assert watcher.status(directory)["status"] == "pending"
    watcher.run(*arguments)
    assert watcher.status(directory)["status"] == "finished"
    assert len(attempts) == 2 and sum("commit" in call for call in calls) == 1


def test_watcher_reports_failed_verification_without_publication(authorized_run, monkeypatch):
    directory, worktree, state, _, _, calls = authorized_run

    def failed(*args, **kwargs):
        raise factory.FinishEvidenceError("Verification failed; publication refused")

    monkeypatch.setattr(factory, "_finish", failed)
    watcher.run(Path("/install"), directory, state["issue"], factory.FACTORY_ROOT, worktree.parent)
    result = watcher.status(directory)
    assert result["status"] == "failed" and "Verification failed" in result["reason"]
    assert sum("commit" in call for call in calls) == 1


def test_watcher_duplicate_process_cannot_repeat_work(authorized_run, monkeypatch):
    directory, worktree, state, _, runner, calls = authorized_run
    watch_dir = directory / "watcher"
    watch_dir.mkdir(mode=0o700)
    with (watch_dir / "watch.lock").open("w") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX)
        monkeypatch.setattr(factory, "_finish", lambda *args, **kwargs: pytest.fail("duplicate publication"))
        watcher.run(Path("/install"), directory, state["issue"], factory.FACTORY_ROOT, worktree.parent)
    assert not calls and not runner.committed


def test_status_exposes_heartbeat_failure_while_watcher_is_still_running(tmp_path):
    directory = tmp_path / "run"
    watch_dir = directory / "watcher"
    heartbeat_dir = watch_dir / "heartbeat"
    heartbeat_dir.mkdir(mode=0o700, parents=True)
    service._write(watch_dir, {"version": 1, "status": "running", "phase": "publishing"})
    service._write(heartbeat_dir, {"version": 1, "status": "failed", "reason": "claim lost"})
    with (watch_dir / "watch.lock").open("w") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX)
        observed = watcher.status(directory)
    assert observed["status"] == "pending" and observed["heartbeat"]["reason"] == "claim lost"


def test_stalled_heartbeat_exposes_expiry_and_fences_commands(tmp_path):
    directory = tmp_path / "run"
    watch_dir = directory / "watcher"
    watch_dir.mkdir(mode=0o700, parents=True)
    keeper = REAL_KEEPER({}, watch_dir)
    service._write(watch_dir, {"version": 1, "status": "running", "phase": "publishing"})
    service._write(keeper.heartbeat_dir, {"version": 1, "status": "healthy", "worktree_expires_at": 1,
                                         "dispatcher_expires_at": None})
    with (watch_dir / "watch.lock").open("w") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX)
        assert watcher.status(directory)["status"] == "pending"
    keeper.valid_until = watcher.time.monotonic() - 1
    with pytest.raises(delivery.DeliveryError, match="Lease renewal failed"):
        keeper.check()
    assert service._read(keeper.heartbeat_dir)["status"] == "failed"
    keeper.error = None
    keeper.valid_until = watcher.time.monotonic() + 60
    keeper.expires_at = watcher.time.time() - 1
    with pytest.raises(delivery.DeliveryError, match="Lease renewal failed"):
        keeper.check()


def test_watcher_stops_after_bounded_readback_failures(authorized_run, monkeypatch):
    directory, worktree, state, _, runner, calls = authorized_run
    attempts = []

    def unavailable(*args):
        attempts.append(True)
        raise delivery.DeliveryError("readback unavailable")

    monkeypatch.setattr(delivery, "_conversation", unavailable)
    monkeypatch.setattr(watcher.time, "sleep", lambda seconds: None)
    watcher.run(Path("/install"), directory, state["issue"], factory.FACTORY_ROOT, worktree.parent)
    assert len(attempts) == 3 and watcher.status(directory)["status"] == "pending"
    assert not runner.committed and not calls


def test_watcher_keeps_observing_a_healthy_task_after_45_minutes(authorized_run, monkeypatch):
    directory, worktree, state, _, _, _ = authorized_run
    observations = []

    def conversation(*args):
        observations.append(True)
        return {"execution_status": "running" if len(observations) <= 271 else "finished"}

    monkeypatch.setattr(delivery, "_conversation", conversation)
    monkeypatch.setattr(watcher.time, "sleep", lambda seconds: None)
    monkeypatch.setattr(factory, "_finish", lambda *args, **kwargs: {
        "pr_number": 1234, "commit_sha": "b" * 40, "checks": {},
    })
    watcher.run(Path("/install"), directory, state["issue"], factory.FACTORY_ROOT, worktree.parent)
    assert len(observations) == 272 and watcher.status(directory)["status"] == "finished"


def test_lease_keeper_renews_exact_recorded_dispatcher_and_worktree_leases(tmp_path, monkeypatch):
    watch_dir = tmp_path / "watcher"
    watch_dir.mkdir(mode=0o700)
    worktree = tmp_path / "worktree"
    worktree.mkdir()
    state = {"worktree": str(worktree), "root": str(tmp_path), "issue": 5230, "session_id": "session",
             "issue_body_sha256": "contract-hash",
             "agent_id": "codex-slice-implementer", "pickup_receipt": BODY_INPUTS["pickup_receipt"]}
    calls = []
    monkeypatch.setattr(delivery, "_full_claim_readback", lambda *args: calls.append("readback"))
    monkeypatch.setattr(publication, "_read_issue", lambda *args: {
        "number": 5230, "state": "open", "labels": ["agent:in-progress"], "body_sha256": "contract-hash",
    })
    def worktree_heartbeat(root, **kwargs):
        calls.append(kwargs)
        return {"expires_at": watcher.time.time() + 3600}

    def dispatcher_heartbeat(store, task_id, holder):
        calls.append((task_id, holder))
        expiry = (datetime.now(timezone.utc) + timedelta(seconds=90)).isoformat()
        return SimpleNamespace(lease_id="lease-5230", holder=holder, resource="issue:5230", expires_at=expiry)

    monkeypatch.setattr(watcher.agent_worktree, "heartbeat_worktree", worktree_heartbeat)
    monkeypatch.setattr(watcher, "_make_store", lambda: object())
    monkeypatch.setattr(watcher.leases, "heartbeat", dispatcher_heartbeat)
    keeper = REAL_KEEPER(state, watch_dir)
    interval = keeper.renew()
    assert calls[0] == "readback"
    assert calls[1] == {"worktree": worktree, "owner": "session"}
    assert calls[2] == ("github-RasmusTho--agentic-pkm-mvp-issue-5230", "codex-slice-implementer")
    assert 0 < interval <= 30


def test_lease_keeper_renews_real_sqlite_and_worktree_registration(tmp_path, monkeypatch):
    import sqlite3

    if not hasattr(sqlite3, "connect"):
        pytest.skip("SQLite is unavailable in the sandbox test workaround")
    from app.dispatcher.models import TaskRecord
    from app.dispatcher.store import SqliteStore

    worktree = tmp_path / "worktree"
    worktree.mkdir()
    watch_dir = tmp_path / "watcher"
    watch_dir.mkdir(mode=0o700)
    registry = tmp_path / "worktrees.json"
    monkeypatch.setattr(watcher.agent_worktree, "_default_registry_path", lambda root: registry)
    monkeypatch.setattr(watcher.agent_worktree, "_worktree_identity", lambda *args: (worktree, "codex/publication-test"))
    monkeypatch.setattr(watcher.agent_worktree, "_worktree_generation", lambda *args, **kwargs: "a" * 32)
    registered = watcher.agent_worktree.register_worktree(tmp_path, worktree=worktree, owner="session")
    store = SqliteStore(tmp_path / "dispatcher.sqlite3")
    store.initialize()
    task_id = "github-RasmusTho--agentic-pkm-mvp-issue-5230"
    holder = "codex-slice-implementer"
    store.upsert_task(TaskRecord(task_id=task_id, issue_number=5230, title="feature", status="ready",
                                priority="high", source_anchor_refs=[], created_at="2026-01-01T00:00:00Z",
                                updated_at="2026-01-01T00:00:00Z"))
    _, claimed = watcher.leases.claim(store, task_id, holder, ttl_minutes=60)
    receipt = BODY_INPUTS["pickup_receipt"].replace("lease-5230", claimed.lease_id)
    state = {"worktree": str(worktree), "root": str(tmp_path), "issue": 5230, "session_id": "session",
             "issue_body_sha256": "contract-hash", "agent_id": holder, "pickup_receipt": receipt}
    monkeypatch.setattr(delivery, "_full_claim_readback", lambda *args: None)
    monkeypatch.setattr(publication, "_read_issue", lambda *args: {
        "number": 5230, "state": "open", "labels": ["agent:in-progress"], "body_sha256": "contract-hash",
    })
    monkeypatch.setattr(watcher, "_make_store", lambda: store)
    keeper = REAL_KEEPER(state, watch_dir)
    keeper.renew()
    renewed = store.get_lease(claimed.lease_id)
    assert renewed is not None and renewed.lease_id == claimed.lease_id and renewed.ttl_seconds == 3600
    assert renewed.heartbeat_at >= claimed.heartbeat_at
    current = watcher.agent_worktree.load_lifecycle_records(tmp_path)[str(worktree)]
    assert current["generation"] == registered["generation"] and current["heartbeat_at"] >= registered["heartbeat_at"]


def test_heartbeat_failure_during_finish_fences_publication(authorized_run, monkeypatch):
    directory, worktree, state, _, _, calls = authorized_run
    heartbeat_failed = threading.Event()
    renewals = []
    monkeypatch.setattr(watcher, "_LeaseKeeper", REAL_KEEPER)

    def renew(self):
        renewals.append(True)
        if len(renewals) > 1:
            heartbeat_failed.set()
            raise ValueError("lease expired")
        return 0.01

    def finish(*args, **kwargs):
        assert heartbeat_failed.wait(2)
        with kwargs["executor"].keeper.lock:
            kwargs["guard"]()
        pytest.fail("publication continued after lease failure")

    monkeypatch.setattr(REAL_KEEPER, "renew", renew)
    monkeypatch.setattr(factory, "_finish", finish)
    watcher.run(Path("/install"), directory, state["issue"], factory.FACTORY_ROOT, worktree.parent)
    result = watcher.status(directory)
    assert len(renewals) >= 2 and result["status"] == "pending"
    assert result["heartbeat"]["status"] == "failed" and "lease expired" in result["heartbeat"]["reason"]
    assert sum("commit" in call for call in calls) == 1


def test_guarded_executor_refuses_an_effect_after_heartbeat_failure(tmp_path, monkeypatch):
    watch_dir = tmp_path / "watcher"
    watch_dir.mkdir(mode=0o700)
    keeper = REAL_KEEPER({}, watch_dir)
    keeper.error = "claim lost"
    invoked = []

    class Delegate:
        def run(self, *args, **kwargs):
            invoked.append(args)

    monkeypatch.setattr(publication, "SubprocessExecutor", Delegate)
    executor = watcher._GuardedExecutor(keeper)
    with pytest.raises(delivery.DeliveryError, match="Lease renewal failed"):
        executor.run(["git", "push"], cwd=tmp_path)
    assert not invoked


def test_heartbeat_continues_during_a_long_publication_command(tmp_path, monkeypatch):
    watch_dir = tmp_path / "watcher"
    watch_dir.mkdir(mode=0o700)
    keeper = REAL_KEEPER({}, watch_dir)
    renewed = threading.Event()
    calls = []

    def renew(self):
        calls.append(True)
        if len(calls) > 1:
            renewed.set()
        return 0.01

    class Delegate:
        def run(self, argv, *, cwd, input_text=None):
            assert renewed.wait(2)
            return publication.CommandResult(tuple(argv), 0, "", "")

    monkeypatch.setattr(REAL_KEEPER, "renew", renew)
    monkeypatch.setattr(publication, "SubprocessExecutor", Delegate)
    executor = watcher._GuardedExecutor(keeper)
    keeper.start()
    try:
        assert executor.run(["git", "push"], cwd=tmp_path).returncode == 0
    finally:
        keeper.close()
    assert len(calls) >= 2


def test_heartbeat_failure_during_an_effect_requires_reconciliation(tmp_path, monkeypatch):
    watch_dir = tmp_path / "watcher"
    watch_dir.mkdir(mode=0o700)
    keeper = REAL_KEEPER({}, watch_dir)

    class Delegate:
        def run(self, argv, *, cwd, input_text=None):
            keeper.error = "lease lost during command"
            return publication.CommandResult(tuple(argv), 0, "", "")

    monkeypatch.setattr(publication, "SubprocessExecutor", Delegate)
    with pytest.raises(delivery.DeliveryError, match="Lease renewal failed"):
        watcher._GuardedExecutor(keeper).run(["git", "push"], cwd=tmp_path)


@pytest.mark.parametrize("case", ["extra_change", "untrusted_handoff", "ambiguous_commit"])
def test_watcher_refuses_unscoped_or_ambiguous_work(authorized_run, monkeypatch, case):
    directory, worktree, state, handoff, runner, calls = authorized_run
    if case == "extra_change":
        handoff["paths"] = ["other.py"]
    elif case == "untrusted_handoff":
        handoff["body"]["pickup_receipt"] = "forged"
    else:
        watch_dir = directory / "watcher"
        watch_dir.mkdir(mode=0o700)
        service._write(watch_dir, {"version": 1, "status": "running", "phase": "committing"})
    (worktree / watcher.HANDOFF).write_text(json.dumps(handoff))
    monkeypatch.setattr(factory, "_finish", lambda *args, **kwargs: pytest.fail("published unsafe work"))
    watcher.run(Path("/install"), directory, state["issue"], factory.FACTORY_ROOT, worktree.parent)
    result = watcher.status(directory)
    assert result["status"] == ("pending" if case == "ambiguous_commit" else "failed")
    assert not runner.committed and not any("add" in call for call in calls)
