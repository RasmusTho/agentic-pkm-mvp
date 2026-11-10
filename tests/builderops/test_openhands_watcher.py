import fcntl
import hashlib
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
REAL_WAIT_FOR_CI = watcher._wait_for_ci
REAL_CONVERSATION = delivery._conversation


@pytest.mark.parametrize("checks,statuses,expected", [
    ([{"name": "unit", "status": "completed", "conclusion": "success"}], [], "checks_successful"),
    ([{"name": "unit", "status": "in_progress", "conclusion": None}], [], "pending"),
    ([{"name": "unit", "status": "completed", "conclusion": "failure"}], [], "failed"),
    ([{"name": "unit", "status": "completed", "conclusion": "skipped"}], [], "pending"),
    ([], [], "pending"),
    ([], [{"context": "ci", "state": "success"}], "checks_successful"),
    ([], [{"context": "ci", "state": "failure"}], "failed"),
    ([{"name": "unit", "status": "completed", "conclusion": "success"}], [{"context": "ci", "state": "pending"}], "pending"),
])
def test_fresh_ci_readback_is_head_bound_and_read_only(tmp_path, checks, statuses, expected):
    head = "a" * 40
    branch = "codex/issue-123-openhands"
    state = {"repository": delivery.REPOSITORY, "root": str(tmp_path), "issue": 123, "branch": branch,
             "full_publication": {"pr_number": 77, "candidate": {"head": head}}}
    recorded = {"pr_number": 77, "head": head}
    pr = {"number": 77, "state": "open", "draft": True,
          "head": {"sha": head, "ref": branch, "repo": {"full_name": delivery.REPOSITORY}},
          "base": {"ref": "main", "repo": {"full_name": delivery.REPOSITORY}}}
    class ReadOnly:
        calls = []
        def run(self, argv, *, cwd, input_text=None):
            command = list(argv)
            self.calls.append(command)
            assert command[:6] == ["gh", "api", "--hostname", "github.com", "--method", "GET"]
            endpoint = command[6]
            if endpoint.endswith("/pulls"):
                body = [pr]
            elif endpoint.endswith("/check-runs"):
                items = [{**check, "head_sha": head, "id": i + 1} for i, check in enumerate(checks)]
                body = {"total_count": len(items), "check_runs": items}
            elif endpoint.endswith("/status"):
                body = {"sha": head, "state": "pending", "total_count": len(statuses), "statuses": statuses}
            else:
                pytest.fail("unexpected GitHub endpoint")
            return publication.CommandResult(tuple(command), 0, json.dumps(body), "")
    runner = ReadOnly()
    assert watcher.fresh_ci_status(state, recorded, tmp_path, 123, runner) == {
        "status": expected, "head": head, "pr_number": 77}
    assert len(runner.calls) == 4
    if expected == "checks_successful":
        assert watcher.fresh_ci_status(state, {}, tmp_path, 123, ReadOnly()) == {
            "status": expected, "head": head, "pr_number": 77}


def test_fresh_ci_does_not_hide_a_same_named_failure(tmp_path, monkeypatch):
    head = "a" * 40
    branch = "codex/issue-123-openhands"
    state = {"repository": delivery.REPOSITORY, "root": str(tmp_path), "issue": 123, "branch": branch,
             "full_publication": {"pr_number": 77, "candidate": {"head": head}}}
    pr = {"number": 77, "state": "open", "draft": True,
          "head": {"sha": head, "ref": branch, "repo": {"full_name": delivery.REPOSITORY}},
          "base": {"ref": "main", "repo": {"full_name": delivery.REPOSITORY}}}
    monkeypatch.setattr(publication, "_read_pr_history", lambda *args: [pr])
    monkeypatch.setattr(delivery, "_check_readback", lambda *args: {"check_runs": [
        {"name": "settings", "status": "completed", "conclusion": "failure"},
        {"name": "settings", "status": "completed", "conclusion": "success"}], "statuses": []})
    assert watcher.fresh_ci_status(state, {}, tmp_path, 123) == {"status": "unavailable"}


def test_fresh_ci_refuses_pr_head_drift_and_unavailable_readback(tmp_path, monkeypatch):
    head = "a" * 40
    branch = "codex/issue-123-openhands"
    state = {"repository": delivery.REPOSITORY, "root": str(tmp_path), "issue": 123, "branch": branch,
             "full_publication": {"pr_number": 77, "candidate": {"head": head}}}
    pr = {"number": 77, "state": "open", "draft": True,
          "head": {"sha": head, "ref": branch, "repo": {"full_name": delivery.REPOSITORY}},
          "base": {"ref": "main", "repo": {"full_name": delivery.REPOSITORY}}}
    snapshots = iter([[pr], [{**pr, "head": {**pr["head"], "sha": "b" * 40}}]])
    monkeypatch.setattr(publication, "_read_pr_history", lambda *args: next(snapshots))
    monkeypatch.setattr(delivery, "_check_readback", lambda *args: {"check_runs": [], "statuses": []})
    assert watcher.fresh_ci_status(state, {"head": head, "pr_number": 77}, tmp_path, 123) == {"status": "unavailable"}
    monkeypatch.setattr(publication, "_read_pr_history", lambda *args: (_ for _ in ()).throw(OSError("private detail")))
    assert watcher.fresh_ci_status(state, {"head": head, "pr_number": 77}, tmp_path, 123) == {"status": "unavailable"}
    assert watcher.fresh_ci_status(state, {"head": head, "pr_number": 78}, tmp_path, 123) == {"status": "unavailable"}


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
             "base_commit": "a" * 40, "pickup_receipt": receipt, "port": 8123,
             "conversation_id": "conversation-1", "session_id": "session-1", "agent_id": "worker-agent"}
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
        head = "a" * 40
        commits = 0

        def run(self, argv, *, cwd, input_text=None):
            command = tuple(argv)
            calls.append(command)
            output, code = "", 0
            if command[-2:] == ("rev-parse", "--show-toplevel"):
                output = str(worktree)
            elif command[-2:] == ("branch", "--show-current"):
                output = branch
            elif command[-2:] == ("rev-parse", "HEAD"):
                output = self.head
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
                self.commits += 1
                self.head = "b" * 40 if self.commits == 1 else "c" * 40
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
    monkeypatch.setattr(factory, "_candidate_head", lambda *args: runner.head)
    monkeypatch.setattr(factory, "_stop", lambda *args: calls.append(("worker-stopped",)))

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
    monkeypatch.setattr(watcher, "_wait_for_ci", lambda state, observation, *args: {
        "status": "passed", "checks": observation.get("checks", {}),
    })
    return directory, worktree, state, handoff, runner, calls


@pytest.mark.parametrize(
    ("exit_code", "runs", "expected"),
    [
        (0, [{"id": 1, "name": "CI", "status": "completed", "conclusion": "success"}], "passed"),
        (0, [{"id": 1, "name": "CI", "status": "completed", "conclusion": "failure"},
             {"id": 2, "name": "CI", "status": "completed", "conclusion": "success"}], "passed"),
        (0, [{"id": 1, "name": "CI", "status": "completed", "conclusion": "success"},
             {"id": 2, "name": "CI", "status": "in_progress", "conclusion": None}], "pending"),
        (1, [{"id": 1, "name": "CI", "status": "completed", "conclusion": "failure"}], "failed"),
        (2, [{"id": 1, "name": "CI", "status": "completed", "conclusion": "failure"},
             {"id": 2, "name": "lint", "status": "in_progress", "conclusion": None}], "failed"),
        (2, [{"id": 1, "name": "CI", "status": "in_progress", "conclusion": None}], "pending"),
        (0, [], "pending"),
    ],
)
def test_ci_wait_uses_current_head_and_latest_executed_checks(tmp_path, monkeypatch, exit_code, runs, expected):
    worktree = tmp_path / "worktree"
    worktree.mkdir()
    watch_dir = tmp_path / "watcher"
    watch_dir.mkdir()
    head = "a" * 40
    state = {"worktree": str(worktree), "branch": "codex/example"}
    observation = {"pr_number": 42, "head": head}
    pr = {"number": 42, "state": "open", "draft": True,
          "head": {"sha": head, "repo": {"full_name": delivery.REPOSITORY}},
          "base": {"ref": "main", "repo": {"full_name": delivery.REPOSITORY}}}
    reads = []
    monkeypatch.setattr(publication, "_read_pr_history", lambda *args: reads.append("pr") or [pr])
    monkeypatch.setattr(delivery, "_check_readback", lambda *args: {
        "commit": head, "check_runs": runs, "statuses": [], "combined_status": "pending",
    })
    monkeypatch.setattr(watcher.subprocess, "run", lambda *args, **kwargs: SimpleNamespace(returncode=exit_code))
    result = REAL_WAIT_FOR_CI(state, observation, watch_dir, SimpleNamespace(check=lambda: None), object())
    assert result["status"] == expected
    assert result["head"] == head and result["pr_number"] == 42
    assert reads == ["pr", "pr", "pr"]


def test_ci_wait_refuses_head_change_during_readback(tmp_path, monkeypatch):
    worktree = tmp_path / "worktree"
    worktree.mkdir()
    watch_dir = tmp_path / "watcher"
    watch_dir.mkdir()
    head = "a" * 40
    pr = {"number": 42, "state": "open", "draft": True,
          "head": {"sha": head, "repo": {"full_name": delivery.REPOSITORY}},
          "base": {"ref": "main", "repo": {"full_name": delivery.REPOSITORY}}}
    monkeypatch.setattr(watcher.subprocess, "run", lambda *args, **kwargs: SimpleNamespace(returncode=0))
    monkeypatch.setattr(publication, "_read_pr_history", lambda *args: [pr])

    def changed(*args):
        pr["head"]["sha"] = "b" * 40
        return {"check_runs": [], "statuses": []}

    monkeypatch.setattr(delivery, "_check_readback", changed)
    with pytest.raises(delivery.DeliveryError, match="Draft PR changed"):
        REAL_WAIT_FOR_CI({"worktree": str(worktree), "branch": "codex/example"},
                         {"pr_number": 42, "head": head}, watch_dir, SimpleNamespace(check=lambda: None), object())


@pytest.mark.parametrize("prior_status", ["pending", "failed"])
def test_ci_wait_resumes_without_repeating_publication(authorized_run, monkeypatch, prior_status):
    directory, worktree, state, _, runner, _ = authorized_run
    watch_dir = directory / "watcher"
    watch_dir.mkdir()
    service._write(watch_dir, {"version": 1, "status": prior_status, "phase": "ci_wait",
                               "pr_number": 1234, "head": "b" * 40})
    monkeypatch.setattr(factory, "_finish", lambda *args, **kwargs: pytest.fail("publication repeated"))
    watcher.run(Path("/install"), directory, state["issue"], factory.FACTORY_ROOT, worktree.parent)
    assert watcher.status(directory)["status"] == "finished"
    assert runner.commits == 0


def test_shutdown_failure_after_publication_resumes_ci_without_republishing(authorized_run, monkeypatch):
    directory, worktree, state, _, runner, _ = authorized_run
    calls = []
    monkeypatch.setattr(factory, "_finish", lambda *args, **kwargs: calls.append("published") or {
        "pr_number": 1234, "commit_sha": "b" * 40, "checks": {},
    })

    def stop(*args):
        calls.append("stop")
        if calls.count("stop") == 1:
            raise delivery.DeliveryError("Interrupted shutdown")

    monkeypatch.setattr(factory, "_stop", stop)
    args = (Path("/install"), directory, state["issue"], factory.FACTORY_ROOT, worktree.parent)
    watcher.run(*args)
    assert watcher.status(directory)["phase"] == "ci_wait"
    assert watcher.status(directory)["status"] == "pending"
    watcher.run(*args)
    assert watcher.status(directory)["status"] == "finished"
    assert calls == ["published", "stop", "stop"] and runner.commits == 1


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


@pytest.mark.parametrize("initial_phase", ["interrupting", "interrupted", "resuming"])
def test_watcher_waits_for_resumed_delivery_and_finishes_once(authorized_run, monkeypatch, initial_phase):
    directory, worktree, state, _, runner, _ = authorized_run
    service._write(directory, {**state, "phase": initial_phase})
    polls = []
    observations = []

    def resume_on_poll(seconds):
        polls.append(seconds)
        assert not runner.committed
        service._write(directory, state)

    monkeypatch.setattr(watcher.time, "sleep", resume_on_poll)
    monkeypatch.setattr(delivery, "_conversation", lambda *args: observations.append("active") or {
        "execution_status": "finished",
    })
    finished = []
    monkeypatch.setattr(factory, "_finish", lambda *args, **kwargs: finished.append(True) or {
        "pr_number": 1234, "commit_sha": "b" * 40, "checks": {},
    })
    watcher.run(Path("/install"), directory, state["issue"], factory.FACTORY_ROOT, worktree.parent)
    assert len(polls) == 1 and observations == ["active"]
    assert runner.commits == 1 and finished == [True]
    assert watcher.status(directory)["status"] == "finished"


@pytest.mark.parametrize("reason", [
    "Run is interrupted or its state requires inspection",
    "Watcher does not match an active authorized delivery",
])
def test_watcher_recovers_legacy_interruption_failure_after_identity_check(authorized_run, monkeypatch, reason):
    directory, worktree, state, _, runner, _ = authorized_run
    watch_dir = directory / "watcher"
    watch_dir.mkdir(mode=0o700)
    service._write(watch_dir, {"version": 1, "status": "failed", "phase": "watching", "reason": reason})
    monkeypatch.setattr(factory, "_finish", lambda *args, **kwargs: {
        "pr_number": 1234, "commit_sha": "b" * 40, "checks": {},
    })
    watcher.run(Path("/install"), directory, state["issue"], factory.FACTORY_ROOT, worktree.parent)
    assert runner.commits == 1 and watcher.status(directory)["status"] == "finished"


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


@pytest.mark.parametrize("mode", ["success", "ambiguous", "replay", "repeated", "session_drift"])
@pytest.mark.parametrize("kind", ["review", "verification"])
def test_watcher_repairs_actionable_feedback_once_and_preserves_replay(authorized_run, monkeypatch, mode, kind):
    directory, worktree, state, _, runner, calls = authorized_run
    review = {"head_sha": "b" * 40, "verdict": "unresolved", "summary": "A concrete defect needs repair",
              "findings": [{"severity": "P1", "description": "Handle the missing value in this branch.",
                            "file": "feature.py", "line": 3}]}
    raw = json.dumps(review)
    artifact = directory / "review.txt"
    artifact.write_text(raw)
    if kind == "review":
        failure = factory.FinishEvidenceError("review unresolved", kind="review", evidence={
            "status": "unresolved", "head_sha": "b" * 40, "reason": None,
            "review": {"head_sha": "b" * 40, "evidence": {"path": str(artifact),
                       "sha256": hashlib.sha256(raw.encode()).hexdigest()}},
        })
    else:
        tests = worktree / "tests"
        tests.mkdir()
        (tests / "test_feature.py").write_text("# target\n")
        raw = "FAILED test_feature.py::test_bug - AssertionError: actual failure\n1 failed\n"
        artifact.write_text(raw)
        failure = factory.FinishEvidenceError("test failed", kind="verification", evidence={
            "status": "failed", "head_sha": "b" * 40, "unresolved": [], "failed": [{
                "target": "tests/test_feature.py::test_bug", "head_sha": "b" * 40, "result": "fail",
                "exit_code": 1, "evidence": {"path": str(artifact), "sha256": hashlib.sha256(raw.encode()).hexdigest()},
            }],
        })
    messages, finish_calls, reads = [], [], []
    worker_id = "b51e5cc1-d1d3-4f2c-996f-80a405e2cf6b"

    def finish(*args, **kwargs):
        finish_calls.append(runner.head)
        if len(finish_calls) == 2:
            assert service._read(directory / "watcher")["handoff"]["paths"] == ["added.py", "feature.py"]
        if len(finish_calls) == 1 or mode == "repeated":
            raise failure
        return {"pr_number": 1234, "commit_sha": runner.head, "checks": {}}

    def conversation(*args):
        if not messages:
            return {"execution_status": "finished", "last_user_message_id": "old-message",
                    "agent_state": {"acp_session_id": worker_id, "acp_session_cwd": str(worktree)}}
        return {"execution_status": "finished", "last_user_message_id": "repair-message",
                "leaf_event_id": "agent-response", "agent_state": {
                    "acp_session_id": ("5218525d-28ae-4c89-8b18-1827b234e046" if mode == "session_drift"
                                       else worker_id), "acp_session_cwd": str(worktree)}}

    def http(port, key, method, path, payload=None, **kwargs):
        assert port == state["port"] and state["conversation_id"] in path
        if method == "POST":
            assert service._read(directory / "watcher")["phase"] == "repair_sending"
            messages.append(payload)
            if mode == "ambiguous":
                raise delivery.DeliveryError("OpenHands API unavailable or outcome uncertain")
            runner.staged = False
            return 200, {"success": True}
        reads.append(path)
        if mode == "replay" and len(reads) == 2:
            raise delivery.DeliveryError("Temporary event readback failure")
        return 200, {"id": "repair-message", "source": "user", "llm_message": {
            "role": "user", "content": messages[0]["content"],
        }}

    monkeypatch.setattr(factory, "_finish", finish)
    monkeypatch.setattr(delivery, "_conversation", conversation)
    monkeypatch.setattr(publication, "_read_pr_history", lambda *args: [])
    monkeypatch.setattr(publication, "_candidate_paths", lambda *args: {"feature.py", "added.py"})
    monkeypatch.setattr(delivery, "_server_key", lambda *args: "local-test-key")
    monkeypatch.setattr(delivery, "_http", http)
    arguments = (Path("/install"), directory, state["issue"], factory.FACTORY_ROOT, worktree.parent)
    watcher.run(*arguments)
    result = watcher.status(directory)
    if mode in {"ambiguous", "session_drift"}:
        assert result["status"] == "pending" and result["phase"] == "repair_sending"
        watcher.run(*arguments)
        assert len(messages) == 1 and runner.commits == 1
        return
    if mode == "replay":
        assert result["status"] == "pending" and result["phase"] == "repair_sent"
        watcher.run(*arguments)
        result = watcher.status(directory)
    assert len(messages) == 1 and runner.commits == 2
    expected = "Handle the missing value" if kind == "review" else "AssertionError: actual failure"
    assert messages[0]["run"] is True and expected in messages[0]["content"][0]["text"]
    prompt = messages[0]["content"][0]["text"]
    assert "Preserve the Issue's exclusions and existing behavior outside the authorized fix" in prompt
    assert "actual acceptance criteria and examples and relevant regressions" in prompt
    assert "pre-existing behavior as a blocker merely because it could be improved" in prompt
    assert "regressions and failed acceptance criteria within scope" in prompt
    assert "smallest in-scope fix" in prompt and "leave it unresolved" in prompt
    assert "paths to exactly the files changed or deleted in this repair only" in prompt
    assert "title and body to truthfully describe the full candidate" in prompt
    assert finish_calls == ["b" * 40, "c" * 40]
    assert result["status"] == ("failed" if mode == "repeated" else "finished")
    watcher.run(*arguments)
    assert len(messages) == 1 and runner.commits == 2


def test_test_failure_feedback_uses_actual_bound_output(authorized_run):
    directory, worktree, state, handoff, _, _ = authorized_run
    tests = worktree / "tests"
    tests.mkdir()
    (tests / "test_feature.py").write_text("# target\n")
    source = "FAILED tests/test_feature.py::test_bug - AssertionError: actual failure\n1 failed\n"
    log = directory / "failure.log"
    log.write_text(source)
    failure = factory.FinishEvidenceError("failed", kind="verification", evidence={
        "status": "failed", "head_sha": "b" * 40, "unresolved": [], "failed": [{
            "target": "tests/test_feature.py::test_bug", "head_sha": "b" * 40, "result": "fail",
            "exit_code": 1, "evidence": {"path": str(log), "sha256": hashlib.sha256(source.encode()).hexdigest()},
        }],
    })
    assert "AssertionError: actual failure" in watcher._repair_feedback(failure, state, handoff, "b" * 40, directory)
    failure.evidence["unresolved"] = [{"reason": "another target was not run"}]
    assert watcher._repair_feedback(failure, state, handoff, "b" * 40, directory) is None


def test_unresolved_review_without_actionable_findings_is_not_resent(authorized_run):
    directory, _, state, handoff, _, _ = authorized_run
    raw = json.dumps({"head_sha": "b" * 40, "verdict": "unresolved", "summary": "Review unavailable", "findings": []})
    artifact = directory / "review.txt"
    artifact.write_text(raw)
    error = factory.FinishEvidenceError("unresolved", kind="review", evidence={
        "status": "unresolved", "head_sha": "b" * 40, "reason": None,
        "review": {"head_sha": "b" * 40, "evidence": {"path": str(artifact),
                   "sha256": hashlib.sha256(raw.encode()).hexdigest()}},
    })
    assert watcher._repair_feedback(error, state, handoff, "b" * 40, directory) is None


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


def test_watcher_retries_service_lock_timeouts_as_readback_failures(authorized_run, monkeypatch):
    directory, worktree, state, _, runner, calls = authorized_run
    attempts = []
    def busy(*args, **kwargs):
        attempts.append(True)
        raise service.ServiceError("Delivery input is still being processed")
    monkeypatch.setattr(delivery, "_conversation", REAL_CONVERSATION)
    monkeypatch.setattr(service, "status", busy)
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


def test_unresolved_feedback_is_bound_to_current_issue_and_safe_targets(authorized_run, monkeypatch):
    directory, worktree, state, handoff, _, _ = authorized_run
    body = '## Acceptance Criteria\n- [ ] Behavior\n  - Verify: `tests/test_missing.py::test_behavior`\n- [ ] Docs\n  - Verify: doc writeback at `docs/OWNER.md :: State`\n'
    state.update(repository=delivery.REPOSITORY, issue_body_sha256=delivery._sha(body))
    issue = {"number": state["issue"], "state": "OPEN", "body": body,
             "url": f"https://github.com/{delivery.REPOSITORY}/issues/{state['issue']}"}
    monkeypatch.setattr(delivery, "_json_result", lambda *args: issue)
    evidence = {"repository": delivery.REPOSITORY, "issue": state["issue"],
                "head_sha": "b" * 40, "issue_body_sha256": state["issue_body_sha256"],
                "status": "unresolved", "failed": [], "unresolved": [
                    {"target": "`tests/test_missing.py::test_behavior`", "reason": "Not a concrete local pytest target"},
                    {"target": "doc writeback at `docs/OWNER.md :: State`", "reason": "Not a concrete local pytest target"},
                ]}
    error = factory.FinishEvidenceError("unresolved", kind="verification", evidence=evidence)
    assert watcher._repair_feedback(error, state, handoff, "b" * 40, directory) is None
    evidence["unresolved"].pop()
    assert "test_missing.py::test_behavior" in watcher._repair_feedback(error, state, handoff, "b" * 40, directory)
    evidence["unresolved"].append({"target": "tests/injected.py::test_x", "reason": "Not a concrete local pytest target"})
    assert watcher._repair_feedback(error, state, handoff, "b" * 40, directory) is None
    evidence["unresolved"].pop()
    issue["body"] += "changed"
    assert watcher._repair_feedback(error, state, handoff, "b" * 40, directory) is None
    issue["body"] = body
    evidence["unresolved"][0]["reason"] = "Command unavailable or timed out"
    assert watcher._repair_feedback(error, state, handoff, "b" * 40, directory) is None



def test_failed_publishing_remains_stopped_without_native_completion_proof(authorized_run, monkeypatch):
    directory, worktree, state, handoff, runner, _ = authorized_run
    watch_dir = directory / "watcher"
    watch_dir.mkdir(mode=0o700)
    service._write(watch_dir, {"version": 1, "status": "failed", "phase": "publishing",
                              "head": "b" * 40, "handoff": handoff,
                              "failed_evidence": {"kind": "verification", "status": "unresolved"}})
    monkeypatch.setattr(factory, "_finish", lambda *args, **kwargs: pytest.fail("must not restart"))
    watcher.run(Path("/install"), directory, state["issue"], factory.FACTORY_ROOT, worktree.parent)
    assert runner.commits == 0
    assert watcher.status(directory)["status"] == "failed"


def test_repair_handoff_retains_original_and_expands_risks_and_candidate_paths(authorized_run, monkeypatch):
    directory, worktree, state, handoff, runner, _ = authorized_run
    watch_dir = directory / "watcher"
    watch_dir.mkdir(mode=0o700)
    runner.head = "b" * 40
    runner.commits = 1
    original = {"title": "Original", "body": {}, "risks": ["auth"], "paths": ["old.py"]}
    updated = {"title": "Updated", "body": {}, "risks": ["auth", "data"], "paths": ["feature.py"]}
    monkeypatch.setattr(watcher, "_handoff", lambda *args: updated)
    monkeypatch.setattr(publication, "_candidate_paths", lambda *args: {"old.py", "feature.py"})
    record = {"version": 1, "phase": "repair_sent", "repair_base": runner.head, "handoff": original}
    result = watcher._commit(directory, state, record, watch_dir, runner)
    assert result["paths"] == ["feature.py", "old.py"]
    assert result["risks"] == ["auth", "data"]
    assert service._read(watch_dir)["original_handoff"] == original


def test_real_git_repair_handoff_uses_delta_and_preserves_cumulative_paths(tmp_path, monkeypatch):
    import subprocess

    repo = tmp_path / "repo"
    repo.mkdir()
    def git(*args):
        return subprocess.run(["git", *args], cwd=repo, check=True, capture_output=True, text=True).stdout.strip()
    git("init", "-b", "codex/repair")
    git("config", "user.name", "Test")
    git("config", "user.email", "test@example.invalid")
    (repo / ".gitignore").write_text(".codex-tmp/\n")
    git("add", ".gitignore")
    git("commit", "-m", "base")
    base = git("rev-parse", "HEAD")
    (repo / "original.py").write_text("original\n")
    git("add", "original.py")
    git("commit", "-m", "original candidate")
    repair_base = git("rev-parse", "HEAD")
    (repo / "new.py").write_text("repair\n")
    local = repo / ".codex-tmp"
    local.mkdir()
    receipt = BODY_INPUTS["pickup_receipt"].replace("/tmp/publication-test", str(repo))
    state = {"issue": 5230, "worktree": str(repo), "branch": "codex/repair", "base_commit": base,
             "pickup_receipt": receipt}
    handoff = {"version": 1, "issue": 5230, "title": "Full candidate", "paths": ["new.py"],
               "risk_surfaces": ["auth", "data"], "body": {key: BODY_INPUTS[key] for key in watcher.BODY_FIELDS}}
    handoff_file = local / "openhands-finish.json"
    handoff_file.write_text(json.dumps(handoff))
    handoff_file.chmod(0o600)
    run_dir = tmp_path / "run"
    run_dir.mkdir()
    watch_dir = run_dir / "watcher"
    watch_dir.mkdir()
    previous = {"title": "Original", "body": {}, "risks": ["auth"], "paths": ["original.py"]}
    record = {"version": 1, "phase": "repair_sent", "repair_base": repair_base, "handoff": previous}
    monkeypatch.setattr(delivery, "_full_claim_readback", lambda *args: None)
    monkeypatch.setattr(delivery, "_finished_run", lambda *args: state)
    class LocalGit:
        def run(self, argv, *, cwd, input_text=None):
            if str(argv[0]).endswith("agent_workspace_preflight.sh"):
                return publication.CommandResult(tuple(argv), 0, "", "")
            assert argv[0] == "git"
            return publication.SubprocessExecutor().run(argv, cwd=cwd, input_text=input_text)
    result = watcher._commit(run_dir, state, record, watch_dir, LocalGit())
    assert result["paths"] == ["new.py", "original.py"]
    assert result["title"] == "Full candidate" and result["risks"] == ["auth", "data"]
    assert service._read(watch_dir)["original_handoff"] == previous
    assert git("status", "--porcelain") == ""


def test_unresolved_bare_pytest_file_target_is_actionable(authorized_run, monkeypatch):
    directory, worktree, state, handoff, _, _ = authorized_run
    body = "## Acceptance Criteria\n- [ ] Coverage\n  - Verify: `tests/test_missing.py`\n"
    state.update(repository=delivery.REPOSITORY, issue_body_sha256=delivery._sha(body))
    monkeypatch.setattr(delivery, "_json_result", lambda *args: {
        "number": state["issue"], "state": "OPEN", "body": body,
        "url": f"https://github.com/{delivery.REPOSITORY}/issues/{state['issue']}"})
    error = factory.FinishEvidenceError("unresolved", kind="verification", evidence={
        "repository": delivery.REPOSITORY, "issue": state["issue"], "head_sha": "b" * 40,
        "issue_body_sha256": state["issue_body_sha256"], "status": "unresolved", "failed": [],
        "unresolved": [{"target": "`tests/test_missing.py`", "reason": "Not a concrete local pytest target"}]})
    assert "tests/test_missing.py" in watcher._repair_feedback(error, state, handoff, "b" * 40, directory)
    (worktree / "tests").mkdir()
    (worktree / "tests/test_missing.py").write_text("pass\n")
    assert watcher._repair_feedback(error, state, handoff, "b" * 40, directory) is None


def test_missing_selector_diagnostic_must_name_exact_requested_target(authorized_run, monkeypatch):
    directory, worktree, state, handoff, _, _ = authorized_run
    target = "tests/architecture/test_multi_vault_context_boundaries.py::test_production_consumers_use_context_seam"
    file = worktree / target.split("::")[0]
    file.parent.mkdir(parents=True)
    file.write_text("def test_other(): pass\n")
    body = f"## Acceptance Criteria\n- [ ] Coverage\n  - Verify: `{target}`\n"
    state.update(repository=delivery.REPOSITORY, issue_body_sha256=delivery._sha(body))
    monkeypatch.setattr(delivery, "_json_result", lambda *args: {
        "number": state["issue"], "state": "OPEN", "body": body,
        "url": f"https://github.com/{delivery.REPOSITORY}/issues/{state['issue']}"})
    log = directory / "pytest.log"
    # Same diagnostic shape as issue-3867's target-001.log, with only the fixture root changed.
    text = f"[verification runner] Target: {target}\nERROR: not found: {worktree / target}\n(no match in any of [<Module test_multi_vault_context_boundaries.py>])\n"
    log.write_text(text)
    entry = {"target": target, "head_sha": "b" * 40, "exit_code": 4,
             "reason": "Command failed before test results were established",
             "evidence": {"path": str(log), "sha256": hashlib.sha256(text.encode()).hexdigest()}}
    evidence = {"repository": delivery.REPOSITORY, "issue": state["issue"], "head_sha": "b" * 40,
                "issue_body_sha256": state["issue_body_sha256"], "status": "unresolved",
                "failed": [], "unresolved": [entry]}
    error = factory.FinishEvidenceError("unresolved", kind="verification", evidence=evidence)
    assert target in watcher._repair_feedback(error, state, handoff, "b" * 40, directory)
    text = "ERROR: file or directory not found: tests/from-addopts.py\n"
    log.write_text(text)
    entry["evidence"]["sha256"] = hashlib.sha256(text.encode()).hexdigest()
    assert watcher._repair_feedback(error, state, handoff, "b" * 40, directory) is None
