"""Exercise the scoped operator transition with isolated Git and dispatcher state."""
from __future__ import annotations

import copy
import hashlib
import json
import subprocess
import sys
import time
import threading
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone
from pathlib import Path
from types import SimpleNamespace

import pytest

from app.builderops import legacy_owner_recovery as recovery
from app.dispatcher import leases
from app.dispatcher.events import JsonlEventWriter
from app.dispatcher.models import TaskRecord
from app.dispatcher.models import EventRecord
from app.dispatcher.store import SqliteStore
from scripts import agent_worktree

_real_operator_dispatcher_paths = recovery._operator_dispatcher_paths


def _portable_test_host_config():
    """Screen fixture config while simulating the platform-specific host identity."""
    config = recovery.legacy_git_config
    config._check_environment()
    data = config._read(config._qualified_home() / '.gitconfig')
    assert data is not None
    config._screen(data, global_config=True)


def _git(cwd, *args):
    return subprocess.check_output(["git", "-C", str(cwd), *args], text=True).strip()


def _comment(body, ident, timestamp):
    at = datetime.fromtimestamp(timestamp, timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    return {"id": ident, "user": {"login": "RasmusTho"}, "author_association": "OWNER",
            "created_at": at, "updated_at": at,
            "issue_url": f"https://api.github.com/repos/RasmusTho/agentic-pkm-mvp/issues/{body['issue']}",
            "body": json.dumps({"operator_reconciliation.v1": body}, sort_keys=True)}


@pytest.fixture
def operator_case(tmp_path, monkeypatch, request):
    issue, pr_number, old_agent, heartbeat_count = getattr(request, "param", (6601, 6602, "old-agent", 0))
    old_owner = old_agent.removeprefix("openhands-") if heartbeat_count else "old-session"
    repo = tmp_path / "agentic-pkm-mvp"
    repo.mkdir()
    _git(repo, "init", "-b", "main")
    _git(repo, "config", "user.name", "Fixture")
    _git(repo, "config", "user.email", "fixture@example.invalid")
    (repo / "file.txt").write_text("base\n")
    (repo / "tests").mkdir()
    (repo / "tests/test_fixture.py").write_text("def test_fixture(): pass\n")
    _git(repo, "add", "file.txt", "tests/test_fixture.py")
    _git(repo, "commit", "-m", "base")
    base = _git(repo, "rev-parse", "HEAD")
    checkout = tmp_path / "checkout"
    _git(repo, "worktree", "add", "-b", "codex/example", str(checkout))
    (checkout / "file.txt").write_text("candidate\n")
    _git(checkout, "add", "file.txt")
    _git(checkout, "commit", "-m", "candidate")
    head = _git(checkout, "rev-parse", "HEAD")

    now = time.time()
    agent_worktree.register_worktree(checkout, worktree=checkout, owner=old_owner, now=now - 7200, ttl_seconds=60)
    if heartbeat_count:
        registry = agent_worktree._default_registry_path(checkout)
        with agent_worktree._locked_registry(registry) as payload:
            row = payload["worktrees"][str(checkout)]
            for key in list(row):
                if key not in {"path", "branch", "generation", "owner", "status", "registered_at", "heartbeat_at", "expires_at"}:
                    del row[key]
    state_dir = tmp_path / "dispatcher"
    state_dir.mkdir()
    db_path = state_dir / "dispatcher.sqlite3"
    store = SqliteStore(db_path, JsonlEventWriter(state_dir / "events.jsonl"))
    store.initialize()
    task_id = f"github-RasmusTho--agentic-pkm-mvp-issue-{issue}"
    old_time = (datetime.now(timezone.utc) - timedelta(hours=4 if heartbeat_count else 2)).isoformat(timespec="microseconds")
    store.upsert_task(TaskRecord(task_id=task_id, issue_number=issue, title="fixture", status="ready", priority="high",
                                source_anchor_refs=[], created_at=old_time, updated_at=old_time,
                                repo="RasmusTho/agentic-pkm-mvp"))
    with monkeypatch.context() as patch:
        patch.setattr(leases, "_utc_now", lambda: old_time)
        _, old_lease = leases.claim(store, task_id, old_agent)
        minutes_list = ([225, 210, 195, 180, 165, 150] if heartbeat_count == 6 else
                        [195, 150] if heartbeat_count == 2 else [110, 100])
        for minutes in minutes_list:
            heartbeat_at = (datetime.now(timezone.utc) - timedelta(minutes=minutes)).isoformat(timespec="microseconds")
            patch.setattr(leases, "_utc_now", lambda: heartbeat_at)
            leases.heartbeat(store, task_id, old_agent)

    monkeypatch.setattr(recovery, "_operator_dispatcher_paths", lambda *_args, **_kwargs: SimpleNamespace(
        state_dir=state_dir, db_path=db_path, events_path=state_dir / "events.jsonl"))
    monkeypatch.setenv("CODEX_SESSION_ID", "new-session")
    from app.builderops import legacy_git_config
    monkeypatch.setattr(legacy_git_config, "QUALIFIED_COMMON", (repo / ".git").resolve())
    monkeypatch.setattr(legacy_git_config, "_qualified_home", lambda: tmp_path)
    monkeypatch.setattr(legacy_git_config, "check_host_config", lambda: None)
    source_root = str(Path(recovery.__file__).resolve().parents[2])
    monkeypatch.setenv("PYTHONPATH", source_root)
    predecessor = recovery.read_live_predecessor(cwd=checkout, issue=issue)
    candidate = recovery.read_clean_candidate(cwd=checkout, worktree=checkout)
    registration = recovery.read_expired_registration(cwd=checkout, candidate=candidate)
    old_record = agent_worktree._locked_lifecycle_snapshot(agent_worktree._default_registry_path(checkout))[str(checkout)]
    sources = {"attempts": ["fixture:attempts"], "github": ["fixture:github"]}
    writer = {"state": "stopped", "delegations": "stopped", "restart": "reconciled",
              "last_activity": (datetime.now(timezone.utc) - timedelta(hours=2)).isoformat(),
              "boot": (datetime.now(timezone.utc) - timedelta(hours=1)).isoformat(),
              "sources": {"execution": ["fixture:execution"], "delegations": ["fixture:delegations"],
                          "restart": ["fixture:restart"]}}
    origin_receipt = (f"pickup-claim-complete issue={issue} branch=codex/example worktree={checkout} "
                      f"coordination_mode=dispatcher-backed fallback_reason=none task_id={task_id} "
                      f"lease_id={old_lease.lease_id} holder={old_agent} evidence=verified-dispatcher-lease")
    pr_body = f"Governing-Issue: #{issue}\n\nPickup-Receipt: {origin_receipt}\n\nCloses #{issue}\n"
    publication = {"state": "reconciled", "pr": pr_number, "head": head, "repo": "RasmusTho/agentic-pkm-mvp",
                   "branch": "codex/example", "pr_state": "OPEN", "sources": sources}
    publication["body_sha256"] = hashlib.sha256(pr_body.encode()).hexdigest()
    receipt = {"issue": issue, "mode": "operator", "account": "RasmusTho",
               "mandate": {"reference": "fixture:explicit-user-direction", "repo": "RasmusTho/agentic-pkm-mvp",
                           "issue": issue, "effects": ["reconcile", "claim", "register", "acknowledge"]},
               "successor": {"agent": "new-agent", "session": "new-session"}, "predecessor": predecessor,
               "registration": registration, "candidate": candidate, "writer": writer, "publication": publication,
               "branch": "codex/example", "writable_worktree": str(checkout), "predecessor_registration": old_record,
               "branch_history_digest": registration["branch_history_digest"], "base": base,
               "unpublished_candidate_head": head, "changed_files": ["file.txt"]}
    comments = {1: _comment(receipt, 1, now - 5)}
    pr = {"number": pr_number, "state": "open", "body": pr_body, "head": {"ref": "codex/example", "sha": head,
          "repo": {"full_name": "RasmusTho/agentic-pkm-mvp"}},
          "base": {"ref": "main", "repo": {"full_name": "RasmusTho/agentic-pkm-mvp"}}}

    body = (Path(__file__).resolve().parents[1] / "fixtures/issue_readiness/valid_ready_candidate.md").read_text()
    body = body.replace("tests/scripts/test_validate_issue_readiness.py::test_fixture_classifications",
                        "tests/test_fixture.py::test_fixture")
    body = body.replace("tests/governance/test_issue_pr_governance.py::test_issue_readiness_workflow_is_strict_for_agent_ready_only",
                        "tests/test_fixture.py::test_fixture")
    issue_data = {"number": issue, "state": "open", "labels": [{"name": "agent:in-progress"}], "body": body}

    def github_read(args, *, cwd):
        if args == [f"repos/RasmusTho/agentic-pkm-mvp/issues/{issue}"]:
            return json.dumps(issue_data)
        if "user" in args:
            return "RasmusTho\n"
        if "--slurp" in args and any(f"/issues/{issue}/comments" in arg for arg in args):
            return json.dumps([list(comments.values())])
        if "--slurp" in args:
            return json.dumps([[pr]])
        if any(f"/pulls/{pr_number}" in arg for arg in args):
            return json.dumps(pr)
        if any("/git/ref/heads/" in arg for arg in args):
            return json.dumps({"ref": "refs/heads/codex/example", "object": {"sha": head}})
        return json.dumps({"full_name": "RasmusTho/agentic-pkm-mvp", "default_branch": "main"})

    monkeypatch.setattr(recovery, "_github_read", github_read)
    monkeypatch.setattr(agent_worktree, "_read_github_transfer_comment", lambda ident, *, cwd: comments[ident])
    real_run = subprocess.run

    def run(args, **kwargs):
        if args[0] == "gh" and "POST" in args:
            body = json.loads(kwargs["input"])["body"]
            comments[2] = _comment(json.loads(body)["operator_reconciliation.v1"], 2, time.time())
            comments[2]["body"] = body
            return subprocess.CompletedProcess(args, 0, stdout=json.dumps({"id": 2}), stderr="")
        return real_run(args, **kwargs)

    monkeypatch.setattr(recovery.subprocess, "run", run)
    from app.builderops import legacy_run_fence
    run_state_root = tmp_path / "runs"
    run_dir = run_state_root / f"issue-{issue}"
    server_dir = run_dir / "server"
    server_dir.mkdir(parents=True)
    (run_dir / "service.json").write_text(json.dumps({"version": 1, "issue": issue, "worktree": str(checkout)}))
    (server_dir / "service.json").write_text(json.dumps({"version": 1, "state": "stopped"}))
    (run_dir / "service.lock").touch()
    (server_dir / "service.lock").touch()
    monkeypatch.setattr(legacy_run_fence, "QUALIFIED_STATE_ROOT", run_state_root)
    monkeypatch.setattr(legacy_run_fence, "_check_processes", lambda *_args: None)
    return {"run_state_root": run_state_root, "cwd": checkout, "issue": issue, "pr": pr_number, "worktree": checkout, "agent": "new-agent",
            "session": "new-session", "comment_id": 1, "workspace_root": tmp_path / "model", "store": store,
            "old_lease": old_lease, "comments": comments, "old_record": old_record, "receipt": receipt, "pr_data": pr,
            "issue_data": issue_data}


def _args(case):
    return {key: case[key] for key in ("cwd", "issue", "pr", "worktree", "agent", "session", "comment_id", "workspace_root", "run_state_root")}


def test_operator_cli_emits_the_existing_pickup_receipt_line(monkeypatch, capsys, tmp_path):
    receipt = "pickup-claim-complete issue=6601 branch=codex/example worktree=/fixture coordination_mode=dispatcher-backed"
    monkeypatch.setattr(recovery, "execute_operator_pickup", lambda **_kwargs: {"state": "pinned", "pickup_receipt": receipt})
    monkeypatch.setattr(sys, "argv", ["legacy_owner_recovery", "pickup", "--issue", "6601", "--pr", "6602",
                                   "--worktree", str(tmp_path), "--agent", "new", "--session", "s",
                                   "--comment-id", "1", "--workspace-root", str(tmp_path / "model"),
                                   "--legacy-run-state-root", str(tmp_path / "runs")])
    assert recovery._main() == 0
    assert receipt in capsys.readouterr().out.splitlines()


def test_authorized_sessionless_task_transfers_to_actual_successor(operator_case):
    case = operator_case
    result = recovery.execute_operator_pickup(**_args(case))
    assert result["state"] == "pinned" and result["session"] == "new-session"
    events = case["store"].list_events(result["task_id"])
    assert events[0].lease_id == case["old_lease"].lease_id and "session" not in events[0].payload
    assert [event.event_type for event in events[1:-1]] == ["task.heartbeat", "task.heartbeat"]
    assert events[-1].payload["session"] == "new-session"
    row = agent_worktree._locked_lifecycle_snapshot(agent_worktree._default_registry_path(case["cwd"]))[str(case["worktree"])]
    assert row["operator_registration"]["predecessor"] == case["old_record"]
    assert row["operator_registration"]["state"] == "pinned"
    assert row["prior_owner"]["released_at"] is None
    assert (case["worktree"] / "file.txt").read_text() == "candidate\n"


@pytest.mark.parametrize("drift", ["candidate", "session", "scope"])
def test_recovery_refuses_authority_or_candidate_drift(operator_case, drift):
    case = operator_case
    if drift == "candidate":
        (case["worktree"] / "file.txt").write_text("changed\n")
    elif drift == "session":
        case["session"] = "different-session"
    else:
        receipt = copy.deepcopy(case["receipt"])
        receipt["mandate"]["issue"] = 9999
        case["comments"][1] = _comment(receipt, 1, time.time() - 5)
    with pytest.raises(recovery.RecoveryEvidenceError):
        recovery.execute_operator_pickup(**_args(case))
    assert case["store"].get_task(case["receipt"]["predecessor"]["task_id"]).lease_id == case["old_lease"].lease_id
    assert 2 not in case["comments"]


@pytest.mark.parametrize("kind", ["root", "relative", "overlap", "nested"])
def test_operator_rejects_workspace_before_read_or_claim(operator_case, monkeypatch, kind):
    case = operator_case
    args = _args(case)
    args["workspace_root"] = Path("/") if kind == "root" else (
        Path("relative") if kind == "relative" else (
        case["worktree"] / "model" if kind == "nested" else case["worktree"]))

    def unexpected_read(*_args, **_kwargs):
        pytest.fail("workspace boundary was checked after a host read")

    monkeypatch.setattr(recovery, "_github_read", unexpected_read)
    monkeypatch.setattr(recovery, "read_live_predecessor", unexpected_read)
    with pytest.raises(recovery.RecoveryEvidenceError, match="workspace boundary"):
        recovery.execute_operator_pickup(**args)
    assert case["store"].get_task(case["receipt"]["predecessor"]["task_id"]).lease_id == case["old_lease"].lease_id
    assert 2 not in case["comments"]


@pytest.mark.parametrize("unknown", ["execution", "delegations", "restart", "publication"])
def test_unknown_writer_or_publication_blocks_recovery(operator_case, unknown):
    case = operator_case
    receipt = copy.deepcopy(case["receipt"])
    if unknown == "publication":
        receipt["publication"]["state"] = "unknown"
    else:
        receipt["writer"]["state" if unknown == "execution" else unknown] = "unknown"
    case["comments"][1] = _comment(receipt, 1, time.time() - 5)
    with pytest.raises(recovery.RecoveryEvidenceError, match="outcome is unknown"):
        recovery.execute_operator_pickup(**_args(case))
    assert case["store"].get_task(receipt["predecessor"]["task_id"]).lease_id == case["old_lease"].lease_id
    assert 2 not in case["comments"]


def test_lost_ack_response_retains_prepared_state_and_never_reposts(operator_case, monkeypatch):
    case = operator_case
    delegate = recovery.subprocess.run
    post_count = []

    def ambiguous_post(args, **kwargs):
        if args[0] == "gh" and "POST" in args:
            post_count.append(1)
            delegate(args, **kwargs)  # The server created the ACK, but its response is lost.
            return subprocess.CompletedProcess(args, 1, stdout="", stderr="response lost")
        return delegate(args, **kwargs)

    monkeypatch.setattr(recovery.subprocess, "run", ambiguous_post)
    with pytest.raises(recovery.RecoveryEvidenceError, match="ACK publication outcome unknown"):
        recovery.execute_operator_pickup(**_args(case))
    row = agent_worktree._locked_lifecycle_snapshot(agent_worktree._default_registry_path(case["cwd"]))[str(case["worktree"])]
    assert row["operator_registration"]["state"] == "prepared"
    with pytest.raises(agent_worktree.WorktreeLifecycleError, match="unpinned"):
        agent_worktree.assert_operator_registration_pinned(row)
    with pytest.raises(recovery.RecoveryEvidenceError):
        recovery.execute_operator_pickup(**_args(case))
    assert len(post_count) == 1
    assert 2 in case["comments"]
    duplicate = copy.deepcopy(case["comments"][2])
    duplicate["id"] = 3
    case["comments"][3] = duplicate
    with pytest.raises(recovery.RecoveryEvidenceError, match="ambiguous"):
        recovery.resume_operator_pickup(**_args(case))
    assert agent_worktree._locked_lifecycle_snapshot(agent_worktree._default_registry_path(case["cwd"]))[str(case["worktree"])]["operator_registration"]["state"] == "prepared"
    del case["comments"][3]  # The duplicate exists only in this synthetic fixture.
    leases.heartbeat(case["store"], case["receipt"]["predecessor"]["task_id"], "new-agent")
    resumed = recovery.resume_operator_pickup(**_args(case))
    assert resumed["state"] == "pinned" and resumed["ack_comment_id"] == 2
    assert len(post_count) == 1


def test_unknown_ack_without_a_readable_match_never_reposts(operator_case, monkeypatch):
    case = operator_case
    delegate = recovery.subprocess.run
    post_count = []

    def lost_post(args, **kwargs):
        if args[0] == "gh" and "POST" in args:
            post_count.append(1)
            return subprocess.CompletedProcess(args, 1, stdout="", stderr="unknown")
        return delegate(args, **kwargs)

    monkeypatch.setattr(recovery.subprocess, "run", lost_post)
    with pytest.raises(recovery.RecoveryEvidenceError, match="ACK publication outcome unknown"):
        recovery.execute_operator_pickup(**_args(case))
    with pytest.raises(recovery.RecoveryEvidenceError, match="unknown or ambiguous"):
        recovery.resume_operator_pickup(**_args(case))
    row = agent_worktree._locked_lifecycle_snapshot(agent_worktree._default_registry_path(case["cwd"]))[str(case["worktree"])]
    assert row["operator_registration"]["state"] == "prepared"
    assert row["operator_registration"]["ack_intent"] is not None
    assert len(post_count) == 1


def test_lost_claim_response_is_reconciled_without_another_claim(operator_case, monkeypatch):
    case = operator_case
    delegate = recovery.subprocess.run
    claim_attempts = []

    def lost_claim_response(args, **kwargs):
        if len(args) > 3 and args[1:4] == ["-m", "app.dispatcher", "claim"]:
            claim_attempts.append(1)
            delegate(args, **kwargs)  # The claim committed; only its response is lost.
            return subprocess.CompletedProcess(args, 1, stdout="", stderr="response lost")
        return delegate(args, **kwargs)

    monkeypatch.setattr(recovery.subprocess, "run", lost_claim_response)
    result = recovery.execute_operator_pickup(**_args(case))
    assert result["state"] == "pinned" and result["claim_exit"] == 1
    assert len(claim_attempts) == 1
    assert len([e for e in case["store"].list_events(result["task_id"]) if e.event_type == "task.claimed"]) == 2


def test_resume_after_claim_before_registration_uses_the_existing_claim(operator_case, monkeypatch):
    case = operator_case
    original_prepare = agent_worktree.prepare_operator_registration

    def interrupted_prepare(*_args, **_kwargs):
        raise agent_worktree.WorktreeLifecycleError("fixture interruption before registration")

    monkeypatch.setattr(agent_worktree, "prepare_operator_registration", interrupted_prepare)
    with pytest.raises(recovery.RecoveryEvidenceError, match="registration failed; retain claim"):
        recovery.execute_operator_pickup(**_args(case))
    task_id = case["receipt"]["predecessor"]["task_id"]
    new_lease = case["store"].get_task(task_id).lease_id
    assert new_lease != case["old_lease"].lease_id
    assert agent_worktree._locked_lifecycle_snapshot(agent_worktree._default_registry_path(case["cwd"]))[str(case["worktree"])] == case["old_record"]
    assert 2 not in case["comments"]
    monkeypatch.setattr(agent_worktree, "prepare_operator_registration", original_prepare)
    result = recovery.resume_operator_pickup(**_args(case))
    assert result["state"] == "pinned" and result["lease_id"] == new_lease
    assert len([e for e in case["store"].list_events(task_id) if e.event_type == "task.claimed"]) == 2
    assert result["ack_comment_id"] == 2


def test_resume_after_registration_before_ack_intent_posts_once(operator_case, monkeypatch):
    case = operator_case
    post_and_pin = recovery._post_and_pin_operator_ack

    def interrupted_before_intent(**_kwargs):
        raise recovery.RecoveryEvidenceError("fixture interruption before ACK intent")

    monkeypatch.setattr(recovery, "_post_and_pin_operator_ack", interrupted_before_intent)
    with pytest.raises(recovery.RecoveryEvidenceError, match="before ACK intent"):
        recovery.execute_operator_pickup(**_args(case))
    row = agent_worktree._locked_lifecycle_snapshot(agent_worktree._default_registry_path(case["cwd"]))[str(case["worktree"])]
    assert row["operator_registration"]["state"] == "prepared"
    assert row["operator_registration"].get("ack_intent") is None
    assert 2 not in case["comments"]
    monkeypatch.setattr(recovery, "_post_and_pin_operator_ack", post_and_pin)
    result = recovery.resume_operator_pickup(**_args(case))
    assert result["state"] == "pinned" and result["ack_comment_id"] == 2
    assert len([e for e in case["store"].list_events(result["task_id"]) if e.event_type == "task.claimed"]) == 2


@pytest.mark.parametrize("history", ["session-bound", "earlier-claim"])
def test_unsupported_predecessor_history_is_refused_before_claim(operator_case, history):
    case = operator_case
    task_id = case["receipt"]["predecessor"]["task_id"]
    old = case["store"].list_events(task_id)[0]
    if history == "session-bound":
        payload = {**old.payload, "session": "old-session"}
        with case["store"]._connect() as connection:
            connection.execute("UPDATE dispatcher_events SET payload = ? WHERE event_id = ?",
                               (json.dumps(payload), old.event_id))
            connection.commit()
    else:
        previous_time = (datetime.fromisoformat(old.timestamp.replace("Z", "+00:00")) - timedelta(seconds=1)).isoformat()
        case["store"].append_event(EventRecord(event_id="older-claim", timestamp=previous_time, task_id=task_id,
             event_type="task.claimed", actor="earlier-agent", lease_id="older-lease", payload={"ttl_minutes": 90}))
    receipt = copy.deepcopy(case["receipt"])
    receipt["predecessor"] = recovery.read_live_predecessor(cwd=case["cwd"], issue=6601)
    case["comments"][1] = _comment(receipt, 1, time.time() - 5)
    with pytest.raises(recovery.RecoveryEvidenceError, match="not eligible"):
        recovery.execute_operator_pickup(**_args(case))
    assert case["store"].get_task(task_id).lease_id == case["old_lease"].lease_id
    assert 2 not in case["comments"]


@pytest.mark.parametrize("problem", ["governing-issue", "old-registry", "diverged-head"])
def test_unusable_pr_or_registry_is_refused_before_claim(operator_case, tmp_path, problem):
    case = operator_case
    receipt = copy.deepcopy(case["receipt"])
    if problem == "governing-issue":
        case["pr_data"]["body"] = case["pr_data"]["body"].replace("Governing-Issue: #6601", "Governing-Issue: #9999")
        receipt["publication"]["body_sha256"] = hashlib.sha256(case["pr_data"]["body"].encode()).hexdigest()
    elif problem == "old-registry":
        other = copy.deepcopy(case["old_record"])
        other["path"] = str(tmp_path / "old-checkout")
        other["registered_at"] -= 1000
        other["heartbeat_at"] -= 1000
        other["expires_at"] -= 1000
        with agent_worktree._locked_registry(agent_worktree._default_registry_path(case["cwd"])) as payload:
            payload["worktrees"][other["path"]] = other
    else:
        tree = _git(case["cwd"], "rev-parse", "HEAD^{tree}")
        unrelated = _git(case["cwd"], "commit-tree", tree, "-m", "unrelated fixture")
        _git(case["cwd"], "reset", "--hard", unrelated)
        receipt["candidate"] = recovery.read_clean_candidate(cwd=case["cwd"], worktree=case["worktree"])
        receipt["unpublished_candidate_head"] = unrelated
    case["comments"][1] = _comment(receipt, 1, time.time() - 5)
    with pytest.raises(recovery.RecoveryEvidenceError):
        recovery.execute_operator_pickup(**_args(case))
    assert case["store"].get_task(case["receipt"]["predecessor"]["task_id"]).lease_id == case["old_lease"].lease_id
    assert 2 not in case["comments"]


def test_operator_preflight_allows_unpublished_descendant(operator_case):
    case = operator_case
    (case["worktree"] / "file.txt").write_text("unpublished descendant\n")
    _git(case["worktree"], "add", "file.txt")
    _git(case["worktree"], "commit", "-m", "unpublished descendant")
    receipt = copy.deepcopy(case["receipt"])
    receipt["candidate"] = recovery.read_clean_candidate(cwd=case["cwd"], worktree=case["worktree"])
    receipt["unpublished_candidate_head"] = receipt["candidate"]["head"]
    case["comments"][1] = _comment(receipt, 1, time.time() - 5)
    observed = recovery.preflight_operator_pickup(**{k: v for k, v in _args(case).items() if k != "run_state_root"})
    assert observed["candidate"]["head"] != observed["publication"]["head"]


def test_competing_operator_invocations_only_one_can_claim(operator_case, monkeypatch):
    case = operator_case
    rival = copy.deepcopy(case["receipt"])
    rival["successor"]["agent"] = "rival-agent"
    case["comments"][4] = _comment(rival, 4, time.time() - 5)
    original = recovery.preflight_operator_pickup
    entered, proceed = threading.Event(), threading.Event()

    def held_preflight(**kwargs):
        observed = original(**kwargs)
        entered.set()
        if not proceed.wait(timeout=15):
            raise AssertionError("competing pickup did not finish")
        return observed

    monkeypatch.setattr(recovery, "preflight_operator_pickup", held_preflight)
    def attempt(index):
        args = _args(case)
        if index:
            args.update(agent="rival-agent", comment_id=4)
        try:
            return recovery.execute_operator_pickup(**args)
        except recovery.RecoveryEvidenceError:
            return None

    with ThreadPoolExecutor(max_workers=2) as pool:
        first = pool.submit(attempt, 0)
        assert entered.wait(timeout=15)
        second = pool.submit(attempt, 1)
        try:
            rival_result = second.result(timeout=10)
        finally:
            proceed.set()
        results = [first.result(timeout=15), rival_result]
    successes = [item for item in results if item is not None]
    assert len(successes) == 1 and successes[0]["state"] == "pinned"
    events = case["store"].list_events(case["receipt"]["predecessor"]["task_id"])
    assert len([item for item in events if item.event_type == "task.claimed"]) == 2
    assert sorted(case["comments"]) == [1, 2, 4]


def test_successor_preserves_delivery_gates(operator_case):
    from app.builderops import closure, openhands_pr_cycle

    case = operator_case
    result = recovery.execute_operator_pickup(**_args(case))
    row = agent_worktree._locked_lifecycle_snapshot(agent_worktree._default_registry_path(case["cwd"]))[str(case["worktree"])]
    entry = {"claimant": "new-agent", "session": "new-session", "lease_id": result["lease_id"],
             "base_sha": case["receipt"]["base"], "lifecycle_repo": str(case["cwd"])}
    openhands_pr_cycle._operator_lineage(
        events=[event.to_dict() for event in case["store"].list_events(result["task_id"])],
        owner={"task_id": result["task_id"], "lease_id": result["lease_id"], "lease_holder": "new-agent"},
        origin={"mode": "dispatcher-backed", "lease_id": result["lease_id"], "agent": "new-agent", "path": str(case["worktree"])},
        registration=row, records={str(case["worktree"]): row}, comments=list(case["comments"].values()),
        issue_comments=[], issue=6601, pr_number=6602, branch="codex/example", head=case["receipt"]["candidate"]["head"],
        files=["file.txt"], entry=entry,
    )
    required = [{"kind": "check", "name": "Unit tests", "app_id": None}]
    failed = [{"id": 1, "name": "Unit tests", "app": {"id": 123}, "status": "completed", "conclusion": "failure"}]
    with pytest.raises(closure.ClosureError, match="not successful"):
        closure._required_check_evidence(failed, [], required)


def test_successor_can_commit_a_repair_and_renew_its_lease(operator_case):
    from app.builderops import openhands_pr_cycle

    case = operator_case
    result = recovery.execute_operator_pickup(**_args(case))
    leases.heartbeat(case["store"], result["task_id"], "new-agent")
    (case["worktree"] / "file.txt").write_text("candidate plus reviewed repair\n")
    _git(case["worktree"], "add", "file.txt")
    _git(case["worktree"], "commit", "-m", "repair")
    head = _git(case["worktree"], "rev-parse", "HEAD")
    assert head != case["receipt"]["candidate"]["head"]
    row = agent_worktree._locked_lifecycle_snapshot(agent_worktree._default_registry_path(case["cwd"]))[str(case["worktree"])]
    entry = {"claimant": "new-agent", "session": "new-session", "lease_id": result["lease_id"],
             "base_sha": case["receipt"]["base"], "lifecycle_repo": str(case["cwd"])}
    openhands_pr_cycle._operator_lineage(
        events=[event.to_dict() for event in case["store"].list_events(result["task_id"])],
        owner={"task_id": result["task_id"], "lease_id": result["lease_id"], "lease_holder": "new-agent"},
        origin={"mode": "dispatcher-backed", "lease_id": result["lease_id"], "agent": "new-agent", "path": str(case["worktree"])},
        registration=row, records={str(case["worktree"]): row}, comments=list(case["comments"].values()),
        issue_comments=[], issue=6601, pr_number=6602, branch="codex/example", head=head, files=["file.txt"], entry=entry,
    )
    assert case["store"].get_lease(result["lease_id"]).heartbeat_at is not None
    with pytest.raises(openhands_pr_cycle.CycleError, match="verification is incomplete"):
        openhands_pr_cycle._premerge(None, {"head_sha": head}, {"engine": "codex"}, {})


@pytest.mark.parametrize("action", ["pickup", "resume"])
@pytest.mark.parametrize("drift", ["closed", "wrong_number", "labels", "invalid_contract", "unavailable"])
def test_direct_operator_entries_fail_closed_on_issue_drift(operator_case, monkeypatch, action, drift):
    case = operator_case
    if drift == "closed": case["issue_data"]["state"] = "closed"
    if drift == "wrong_number": case["issue_data"]["number"] = 42
    if drift == "labels": case["issue_data"]["labels"].append({"name": "agent:ready"})
    if drift == "invalid_contract": case["issue_data"]["body"] = "invalid"
    if drift == "unavailable":
        original = recovery._github_read
        def unavailable(args, *, cwd):
            if args == ["repos/RasmusTho/agentic-pkm-mvp/issues/6601"]:
                raise recovery.RecoveryEvidenceError("authenticated GitHub readback is unavailable")
            return original(args, cwd=cwd)
        monkeypatch.setattr(recovery, "_github_read", unavailable)
    operation = recovery.execute_operator_pickup if action == "pickup" else recovery.resume_operator_pickup
    with pytest.raises(recovery.RecoveryEvidenceError):
        operation(**_args(case))
    task_id = case["receipt"]["predecessor"]["task_id"]
    assert case["store"].get_task(task_id).lease_id == case["old_lease"].lease_id
    assert 2 not in case["comments"]


@pytest.mark.parametrize("at_read", list(range(2, 13)))
def test_issue_drift_at_effect_boundary_retains_exact_state(operator_case, monkeypatch, at_read):
    case = operator_case
    original = recovery._github_read
    reads = 0
    def drift(args, *, cwd):
        nonlocal reads
        if args == ["repos/RasmusTho/agentic-pkm-mvp/issues/6601"]:
            reads += 1
            if reads == at_read:
                case["issue_data"]["state"] = "closed"
        return original(args, cwd=cwd)
    monkeypatch.setattr(recovery, "_github_read", drift)
    with pytest.raises(recovery.RecoveryEvidenceError, match="current issue validation"):
        recovery.execute_operator_pickup(**_args(case))
    task_id = case["receipt"]["predecessor"]["task_id"]
    claims = [e for e in case["store"].list_events(task_id) if e.event_type == "task.claimed"]
    assert len(claims) == (1 if at_read <= 3 else 2)
    assert (2 in case["comments"]) == (at_read >= 10)
    case["issue_data"]["state"] = "open"
    if at_read in (8, 9):
        # An established intent with no readable ACK is ambiguous; never repost.
        with pytest.raises(recovery.RecoveryEvidenceError, match="ACK outcome is unknown or ambiguous"):
            recovery.resume_operator_pickup(**_args(case))
        assert 2 not in case["comments"]
    elif at_read >= 4:
        result = recovery.resume_operator_pickup(**_args(case))
        assert result["state"] == "pinned"
        assert len([e for e in case["store"].list_events(task_id) if e.event_type == "task.claimed"]) == 2
        assert sorted(case["comments"]) == [1, 2]


def test_direct_preflight_refuses_poisoned_config_before_source_git(operator_case, monkeypatch):
    case = operator_case
    config = case['cwd'].parent / 'agentic-pkm-mvp' / '.git/config'
    with config.open('a') as output:
        output.write('\n[include]\n  path = /tmp/unsupported-config\n')
    calls = []
    def source_git(*args, **kwargs):
        calls.append(args)
        raise AssertionError('source Git ran before configuration screening')
    monkeypatch.setattr(agent_worktree.git_hygiene, 'run_git', source_git)
    args = {k: v for k, v in _args(case).items() if k != 'run_state_root'}
    with pytest.raises(recovery.RecoveryEvidenceError, match='Git configuration'):
        recovery.preflight_operator_pickup(**args)
    assert not calls


@pytest.mark.parametrize('point', ['before_intent', 'after_intent'])
def test_ack_rechecks_publication_before_effect(operator_case, monkeypatch, point):
    case = operator_case
    if point == 'before_intent':
        original = agent_worktree.prepare_operator_registration
        def drift(*args, **kwargs):
            prepared = original(*args, **kwargs)
            case['pr_data']['head']['sha'] = '0' * 40
            return prepared
        monkeypatch.setattr(agent_worktree, 'prepare_operator_registration', drift)
    else:
        original = agent_worktree.begin_operator_ack
        def drift(*args, **kwargs):
            intent = original(*args, **kwargs)
            case['pr_data']['head']['sha'] = '0' * 40
            return intent
        monkeypatch.setattr(agent_worktree, 'begin_operator_ack', drift)
    with pytest.raises(recovery.RecoveryEvidenceError):
        recovery.execute_operator_pickup(**_args(case))
    registry = agent_worktree._default_registry_path(case['cwd'])
    proof = agent_worktree._locked_lifecycle_snapshot(registry)[str(case['worktree'])]['operator_registration']
    assert proof['state'] == 'prepared'
    assert (proof.get('ack_intent') is not None) == (point == 'after_intent')
    assert 2 not in case['comments']


@pytest.mark.parametrize('operator_case', [
    (6601, 6602, 'openhands-11111111-1111-4111-8111-111111111111', 6),
    (6597, 6603, 'openhands-22222222-2222-4222-8222-222222222222', 2),
], indirect=True, ids=['legacy-six-heartbeats', 'legacy-two-heartbeats'])
def test_legacy_shapes_draft_pickup_ack_repair_and_native_proof(operator_case, monkeypatch, capsys):
    """Exercise unlinked legacy tasks through qualified primary discovery and native proof."""
    import shutil
    from app.builderops import openhands_pr_cycle as cycle
    from scripts import legacy_operator_evidence, verify_operator_successor

    case = operator_case
    primary = recovery.legacy_git_config.QUALIFIED_COMMON.parent
    state_dir = primary / 'runtime/dispatcher'
    state_dir.mkdir(parents=True)
    shutil.copy2(case['store'].db_path, state_dir / 'dispatcher.sqlite3')
    shutil.copy2(case['store']._event_writer.path, state_dir / 'events.jsonl')
    case['store'] = SqliteStore(state_dir / 'dispatcher.sqlite3', JsonlEventWriter(state_dir / 'events.jsonl'))
    (primary.parent / '.gitconfig').write_text('[user]\n\tname = Fixture\n\temail = fixture@example.invalid\n')
    monkeypatch.setenv('HOME', str(primary.parent))
    monkeypatch.setattr(recovery.legacy_git_config, 'check_host_config', _portable_test_host_config)
    monkeypatch.setattr(recovery, '_operator_dispatcher_paths', _real_operator_dispatcher_paths)
    paths = recovery._operator_dispatcher_paths(cwd=case['cwd'])
    assert paths.db_path == case['store'].db_path and paths.events_path == state_dir / 'events.jsonl'
    task_id = case['receipt']['predecessor']['task_id']
    prior = case['store'].get_task(task_id)
    assert prior.linked_pr is None and prior.blocked_reason is None
    history = case['store'].list_events(task_id)
    count = 6 if case['issue'] == 6601 else 2
    assert len(history) == 1 + count
    assert history[0].payload == {'ttl_minutes': 90}
    assert history[0].actor.startswith('openhands-')
    assert all(event.event_type == 'task.heartbeat' for event in history[1:])
    assert set(case['old_record']) == {'branch', 'expires_at', 'generation', 'heartbeat_at', 'owner', 'path', 'registered_at', 'status'}
    assert case['old_record']['owner'] == history[0].actor.removeprefix('openhands-')
    draft = legacy_operator_evidence.build_draft(cwd=case['cwd'], issue=case['issue'], pr=case['pr'],
        worktree=case['worktree'], base=case['receipt']['base'], agent=case['agent'], session=case['session'])['operator_reconciliation.v1']
    assert draft['mandate']['reference'] is None
    assert draft['writer']['state'] is None and draft['publication']['state'] is None
    assert draft['predecessor']['session'] is None
    assert draft['candidate']['status_digest'] == hashlib.sha256(b'').hexdigest()
    run = recovery.subprocess.run
    posts = []
    def lost_ack(args, **kwargs):
        if args[0] == 'gh' and 'POST' in args:
            posts.append(1)
            run(args, **kwargs)
            return subprocess.CompletedProcess(args, 1, stdout='', stderr='response lost')
        return run(args, **kwargs)
    monkeypatch.setattr(recovery.subprocess, 'run', lost_ack)
    with pytest.raises(recovery.RecoveryEvidenceError, match='ACK publication outcome unknown'):
        recovery.execute_operator_pickup(**_args(case))
    monkeypatch.setattr(recovery.subprocess, 'run', run)
    result = recovery.resume_operator_pickup(**_args(case))
    assert result['state'] == 'pinned' and 2 in case['comments'] and len(posts) == 1
    assert case['store'].get_task(task_id).linked_pr is None
    assert len([event for event in case['store'].list_events(task_id) if event.event_type == 'task.claimed']) == 2
    (case['worktree'] / 'file.txt').write_text('repair\n')
    _git(case['worktree'], 'commit', '-am', 'reviewed repair')
    head = _git(case['worktree'], 'rev-parse', 'HEAD')
    live = case['pr_data']
    live['head']['sha'] = head
    live['base']['sha'] = case['receipt']['base']
    live['draft'] = False
    live['title'] = 'Synthetic recovered delivery'
    live['body'] = (f"Governing-Issue: #{case['issue']}\nFixes #{case['issue']}\n"
                    f"Pickup-Receipt: {result['pickup_receipt']}\n")
    class Executor:
        def __init__(self, **kwargs): pass
        def run(self, args, *, cwd):
            return subprocess.CompletedProcess(args, 0, 'RasmusTho\n', '')
    monkeypatch.setattr(cycle, 'SubprocessExecutor', Executor)
    monkeypatch.setattr(cycle.closure, '_api', lambda *args: {'full_name': 'RasmusTho/agentic-pkm-mvp', 'default_branch': 'main'})
    monkeypatch.setattr(cycle.closure, '_pr', lambda *args: live)
    monkeypatch.setattr(cycle.closure, '_closing_issue_references', lambda *args: [case['issue']])
    def pages(executor, cwd, endpoint):
        if endpoint == f"/issues/{case['issue']}/comments": return list(case['comments'].values())
        if endpoint == f"/issues/{case['pr']}/comments": return []
        if endpoint == f"/pulls/{case['pr']}/files": return [{'filename': 'file.txt'}]
        raise AssertionError(endpoint)
    monkeypatch.setattr(cycle, '_api_pages', pages)
    monkeypatch.chdir(case['cwd'])
    monkeypatch.setattr(sys, 'argv', ['verify_operator_successor', '--issue', str(case['issue']), '--pr', str(case['pr']),
        '--worktree', str(case['worktree']), '--workspace-root', str(case['workspace_root']),
        '--agent', case['agent'], '--session', case['session']])
    assert verify_operator_successor.main() == 0
    proof = json.loads(capsys.readouterr().out)
    assert proof['ok'] is True and proof['head'] == head and proof['task_pr_projection'] is None
    assert len(case['store'].list_tasks()) == 1


@pytest.mark.parametrize('action', ['pickup', 'resume'])
def test_issue_drift_before_prepare_retains_exact_claim_without_registration(operator_case, monkeypatch, action):
    case = operator_case
    if action == 'resume':
        prepare = agent_worktree.prepare_operator_registration
        def interrupted(*args, **kwargs):
            raise agent_worktree.WorktreeLifecycleError('before registration')
        monkeypatch.setattr(agent_worktree, 'prepare_operator_registration', interrupted)
        with pytest.raises(recovery.RecoveryEvidenceError, match='registration failed'):
            recovery.execute_operator_pickup(**_args(case))
        monkeypatch.setattr(agent_worktree, 'prepare_operator_registration', prepare)
        read = recovery.read_expired_registration
        def close_after_read(**kwargs):
            observed = read(**kwargs)
            case['issue_data']['state'] = 'closed'
            return observed
        monkeypatch.setattr(recovery, 'read_expired_registration', close_after_read)
        operation = recovery.resume_operator_pickup
    else:
        read = recovery._successor_claim_readback
        def close_after_claim(**kwargs):
            observed = read(**kwargs)
            case['issue_data']['state'] = 'closed'
            return observed
        monkeypatch.setattr(recovery, '_successor_claim_readback', close_after_claim)
        operation = recovery.execute_operator_pickup
    with pytest.raises(recovery.RecoveryEvidenceError, match='current issue validation'):
        operation(**_args(case))
    task_id = case['receipt']['predecessor']['task_id']
    assert case['store'].get_task(task_id).lease_id != case['old_lease'].lease_id
    assert len([event for event in case['store'].list_events(task_id) if event.event_type == 'task.claimed']) == 2
    registry = agent_worktree._default_registry_path(case['cwd'])
    assert agent_worktree._locked_lifecycle_snapshot(registry)[str(case['worktree'])] == case['old_record']
    assert 2 not in case['comments']


def _add_raw_history_case(case, kind):
    registry = agent_worktree._default_registry_path(case['cwd'])
    extra = str(case['cwd'].parent / 'other-history')
    with agent_worktree._locked_registry(registry) as payload:
        if kind == 'non_dict':
            payload['worktrees'][extra] = 'malformed'
        else:
            row = copy.deepcopy(case['old_record'])
            row['path'] = extra + '-mismatch' if kind == 'path_mismatch' else extra
            row['branch'] = None if kind == 'branch_none' else ('codex/example' if kind == 'same_branch' else 'codex/unrelated')
            if kind in {'prior_binding', 'prior_malformed'}:
                row['prior_bindings'] = [{'branch': 'codex/example',
                    'removed_at': 'bad-time' if kind == 'prior_malformed' else time.time() - 100}]
            payload['worktrees'][extra] = row


@pytest.mark.parametrize('kind', ['non_dict', 'branch_none', 'prior_binding', 'prior_malformed', 'path_mismatch', 'same_branch'])
@pytest.mark.parametrize('entry', ['draft', 'preflight', 'pickup', 'resume'])
def test_raw_history_blocks_real_recovery_entries_without_new_effect(operator_case, monkeypatch, kind, entry):
    from scripts import legacy_operator_evidence
    case = operator_case
    task_id = case['receipt']['predecessor']['task_id']
    if entry == 'resume':
        prepare = agent_worktree.prepare_operator_registration
        def interrupted(*args, **kwargs):
            raise agent_worktree.WorktreeLifecycleError('before registration')
        monkeypatch.setattr(agent_worktree, 'prepare_operator_registration', interrupted)
        with pytest.raises(recovery.RecoveryEvidenceError, match='registration failed'):
            recovery.execute_operator_pickup(**_args(case))
        monkeypatch.setattr(agent_worktree, 'prepare_operator_registration', prepare)
    _add_raw_history_case(case, kind)
    with pytest.raises(recovery.RecoveryEvidenceError):
        if entry == 'draft':
            legacy_operator_evidence.build_draft(cwd=case['cwd'], issue=case['issue'], pr=case['pr'],
                worktree=case['worktree'], base=case['receipt']['base'], agent=case['agent'], session=case['session'])
        elif entry == 'preflight':
            recovery.preflight_operator_pickup(**{k: v for k, v in _args(case).items() if k != 'run_state_root'})
        elif entry == 'pickup':
            recovery.execute_operator_pickup(**_args(case))
        else:
            recovery.resume_operator_pickup(**_args(case))
    claims = [event for event in case['store'].list_events(task_id) if event.event_type == 'task.claimed']
    assert len(claims) == (2 if entry == 'resume' else 1)
    assert 2 not in case['comments']
    registry = agent_worktree._default_registry_path(case['cwd'])
    assert agent_worktree._locked_lifecycle_snapshot(registry)[str(case['worktree'])] == case['old_record']


@pytest.mark.parametrize('kind', ['non_dict', 'branch_none', 'prior_binding', 'prior_malformed', 'path_mismatch', 'same_branch'])
def test_raw_history_inserted_after_preflight_blocks_claim(operator_case, monkeypatch, kind):
    case = operator_case
    preflight = recovery.preflight_operator_pickup
    def drift(**kwargs):
        observed = preflight(**kwargs)
        _add_raw_history_case(case, kind)
        return observed
    monkeypatch.setattr(recovery, 'preflight_operator_pickup', drift)
    with pytest.raises(recovery.RecoveryEvidenceError):
        recovery.execute_operator_pickup(**_args(case))
    task_id = case['receipt']['predecessor']['task_id']
    assert case['store'].get_task(task_id).lease_id == case['old_lease'].lease_id
    assert len([event for event in case['store'].list_events(task_id) if event.event_type == 'task.claimed']) == 1
    assert 2 not in case['comments']


@pytest.mark.parametrize('kind', ['non_dict', 'branch_none', 'prior_binding', 'prior_malformed', 'path_mismatch', 'same_branch'])
@pytest.mark.parametrize('point', ['after_intent', 'after_post'])
def test_raw_history_drift_refuses_ack_or_pin_without_replay(operator_case, monkeypatch, kind, point):
    case = operator_case
    if point == 'after_intent':
        begin = agent_worktree.begin_operator_ack
        def drift(*args, **kwargs):
            intent = begin(*args, **kwargs)
            _add_raw_history_case(case, kind)
            return intent
        monkeypatch.setattr(agent_worktree, 'begin_operator_ack', drift)
    else:
        read_ack = recovery._read_unique_operator_ack
        def drift(**kwargs):
            ack = read_ack(**kwargs)
            _add_raw_history_case(case, kind)
            return ack
        monkeypatch.setattr(recovery, '_read_unique_operator_ack', drift)
    with pytest.raises(recovery.RecoveryEvidenceError):
        recovery.execute_operator_pickup(**_args(case))
    task_id = case['receipt']['predecessor']['task_id']
    assert len([event for event in case['store'].list_events(task_id) if event.event_type == 'task.claimed']) == 2
    registry = agent_worktree._default_registry_path(case['cwd'])
    proof = agent_worktree._locked_lifecycle_snapshot(registry)[str(case['worktree'])]['operator_registration']
    assert proof['state'] == 'prepared' and proof.get('ack_intent') is not None
    assert (2 in case['comments']) == (point == 'after_post')
    with pytest.raises(recovery.RecoveryEvidenceError):
        recovery.resume_operator_pickup(**_args(case))
    assert len([event for event in case['store'].list_events(task_id) if event.event_type == 'task.claimed']) == 2
    assert (2 in case['comments']) == (point == 'after_post')


def test_unrelated_well_formed_history_does_not_block_operator_pickup(operator_case):
    case = operator_case
    _add_raw_history_case(case, 'unrelated')
    assert recovery.execute_operator_pickup(**_args(case))['state'] == 'pinned'


@pytest.mark.parametrize('entry', ['draft', 'preflight', 'pickup', 'resume'])
def test_registry_symlink_refused_without_following_or_new_claim(operator_case, monkeypatch, entry):
    from scripts import legacy_operator_evidence
    case = operator_case
    if entry == 'resume':
        prepare = agent_worktree.prepare_operator_registration
        def interrupted(*args, **kwargs):
            raise agent_worktree.WorktreeLifecycleError('before registration')
        monkeypatch.setattr(agent_worktree, 'prepare_operator_registration', interrupted)
        with pytest.raises(recovery.RecoveryEvidenceError):
            recovery.execute_operator_pickup(**_args(case))
        monkeypatch.setattr(agent_worktree, 'prepare_operator_registration', prepare)
    registry = agent_worktree._default_registry_path(case['cwd'])
    target = registry.with_name('foreign-registry.json')
    registry.rename(target)
    registry.symlink_to(target)
    before = target.read_bytes()
    task_id = case['receipt']['predecessor']['task_id']
    with pytest.raises((recovery.RecoveryEvidenceError, agent_worktree.WorktreeLifecycleError)):
        if entry == 'draft':
            legacy_operator_evidence.build_draft(cwd=case['cwd'], issue=case['issue'], pr=case['pr'],
                worktree=case['worktree'], base=case['receipt']['base'], agent=case['agent'], session=case['session'])
        elif entry == 'preflight':
            recovery.preflight_operator_pickup(**{k: v for k, v in _args(case).items() if k != 'run_state_root'})
        elif entry == 'pickup':
            recovery.execute_operator_pickup(**_args(case))
        else:
            recovery.resume_operator_pickup(**_args(case))
    assert target.read_bytes() == before and registry.is_symlink()
    assert len([event for event in case['store'].list_events(task_id) if event.event_type == 'task.claimed']) == (2 if entry == 'resume' else 1)
    assert 2 not in case['comments']


def test_registry_inode_change_before_claim_is_refused(operator_case, monkeypatch):
    case = operator_case
    original = recovery.preflight_operator_pickup
    def swapped(**kwargs):
        observed = original(**kwargs)
        registry = agent_worktree._default_registry_path(case['cwd'])
        target = registry.with_name('foreign-registry.json')
        registry.rename(target)
        registry.symlink_to(target)
        return observed
    monkeypatch.setattr(recovery, 'preflight_operator_pickup', swapped)
    with pytest.raises((recovery.RecoveryEvidenceError, agent_worktree.WorktreeLifecycleError)):
        recovery.execute_operator_pickup(**_args(case))
    task_id = case['receipt']['predecessor']['task_id']
    assert len([event for event in case['store'].list_events(task_id) if event.event_type == 'task.claimed']) == 1
    assert 2 not in case['comments']


@pytest.mark.parametrize('discovery', ['git_failure', 'relative', 'other'])
def test_operator_refuses_unqualified_primary_without_fallback(operator_case, tmp_path, monkeypatch, discovery):
    import shutil

    case = operator_case
    parent_state = tmp_path / 'runtime/dispatcher'
    child_state = case['worktree'] / 'runtime/dispatcher'
    for state in (parent_state, child_state):
        state.mkdir(parents=True)
        shutil.copy2(case['store'].db_path, state / 'dispatcher.sqlite3')
        shutil.copy2(case['store']._event_writer.path, state / 'events.jsonl')
    originals = {p: p.read_bytes() for state in (parent_state, child_state)
                 for p in (state / 'dispatcher.sqlite3', state / 'events.jsonl')}
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(recovery, '_operator_dispatcher_paths', _real_operator_dispatcher_paths)
    if discovery == 'git_failure':
        run = recovery.subprocess.run
        def fail_worktree_list(args, **kwargs):
            if args == ['git', 'worktree', 'list', '--porcelain']:
                raise subprocess.CalledProcessError(1, args)
            return run(args, **kwargs)
        monkeypatch.setattr(recovery.subprocess, 'run', fail_worktree_list)
    else:
        primary = Path('relative-primary') if discovery == 'relative' else tmp_path
        monkeypatch.setattr(recovery, 'discover_primary_worktree', lambda **kwargs: primary)
    with pytest.raises(recovery.RecoveryEvidenceError, match='primary worktree'):
        recovery.execute_operator_pickup(**_args(case))
    assert all(path.read_bytes() == data for path, data in originals.items())
    task_id = case['receipt']['predecessor']['task_id']
    assert len([e for e in case['store'].list_events(task_id) if e.event_type == 'task.claimed']) == 1
    assert 2 not in case['comments']


def test_operator_uses_exact_qualified_primary_dispatcher_paths(operator_case, monkeypatch):
    case = operator_case
    monkeypatch.setattr(recovery, '_operator_dispatcher_paths', _real_operator_dispatcher_paths)
    primary = recovery.legacy_git_config.QUALIFIED_COMMON.parent
    (primary / 'runtime/dispatcher').mkdir(parents=True)
    paths = recovery._operator_dispatcher_paths(cwd=case['cwd'])
    assert paths.state_dir == primary / 'runtime/dispatcher'
    assert paths.db_path == paths.state_dir / 'dispatcher.sqlite3'
    assert paths.events_path == paths.state_dir / 'events.jsonl'


def test_operator_primary_discovery_with_linux_like_host_boundary(operator_case, monkeypatch):
    case = operator_case
    primary = recovery.legacy_git_config.QUALIFIED_COMMON.parent
    (primary / 'runtime/dispatcher').mkdir(parents=True)
    (primary.parent / '.gitconfig').write_text('[user]\n\tname = Fixture\n')
    monkeypatch.setenv('HOME', str(primary.parent))
    monkeypatch.setattr(sys, 'platform', 'linux')
    monkeypatch.setattr(recovery.legacy_git_config, 'check_host_config', _portable_test_host_config)
    monkeypatch.setattr(recovery, '_operator_dispatcher_paths', _real_operator_dispatcher_paths)
    paths = recovery._operator_dispatcher_paths(cwd=case['cwd'])
    assert paths.db_path == primary / 'runtime/dispatcher/dispatcher.sqlite3'


@pytest.mark.parametrize('kind', ['state', 'database', 'events'])
def test_operator_rejects_symlinked_canonical_dispatcher_path(operator_case, tmp_path, monkeypatch, kind):
    case = operator_case
    monkeypatch.setattr(recovery, '_operator_dispatcher_paths', _real_operator_dispatcher_paths)
    primary = recovery.legacy_git_config.QUALIFIED_COMMON.parent
    state = primary / 'runtime/dispatcher'
    state.parent.mkdir(parents=True)
    if kind == 'state':
        state.symlink_to(case['store'].db_path.parent, target_is_directory=True)
    else:
        state.mkdir()
        name = 'dispatcher.sqlite3' if kind == 'database' else 'events.jsonl'
        (state / name).symlink_to(tmp_path / 'foreign-file')
    with pytest.raises(recovery.RecoveryEvidenceError, match='dispatcher paths'):
        recovery._operator_dispatcher_paths(cwd=case['cwd'])


@pytest.mark.parametrize('lock_kind', ['cleanup', 'sqlite'])
def test_operator_claim_refuses_dispatcher_lock_contention_without_wait(operator_case, lock_kind):
    import sqlite3

    case = operator_case
    task_id = case['receipt']['predecessor']['task_id']
    store = case['store']
    if lock_kind == 'cleanup':
        lock = leases._cleanup_guard_lock(store)
        lock.__enter__()
        connection = None
    else:
        lock = None
        connection = sqlite3.connect(store.db_path)
        connection.execute('BEGIN IMMEDIATE')
    try:
        started = time.monotonic()
        with pytest.raises(recovery.RecoveryEvidenceError):
            recovery.execute_operator_pickup(**_args(case))
        assert time.monotonic() - started < 10
    finally:
        if connection is not None:
            connection.rollback()
            connection.close()
        if lock is not None:
            lock.__exit__(None, None, None)
    assert len([e for e in store.list_events(task_id) if e.event_type == 'task.claimed']) == 1
    assert 2 not in case['comments']


def test_operator_claim_avoids_cleanup_registry_sqlite_lock_inversion(operator_case, monkeypatch):
    import sqlite3

    case = operator_case
    registry = agent_worktree._default_registry_path(case['cwd'])
    sqlite_held, registry_waiting, cleanup_finished = (threading.Event() for _ in range(3))
    threads = []
    def cleanup():
        connection = sqlite3.connect(case['store'].db_path, timeout=2)
        try:
            connection.execute('BEGIN IMMEDIATE')
            sqlite_held.set()
            registry_waiting.set()
            with agent_worktree._registry_lock(registry):
                pass
        finally:
            connection.rollback()
            connection.close()
            cleanup_finished.set()
    original = recovery.subprocess.run
    def claim_with_contended_sqlite(args, **kwargs):
        if len(args) > 3 and args[1:4] == ['-m', 'app.dispatcher', 'claim']:
            thread = threading.Thread(target=cleanup)
            threads.append(thread)
            thread.start()
            assert sqlite_held.wait(10) and registry_waiting.wait(10)
            assert not cleanup_finished.is_set()
        return original(args, **kwargs)
    monkeypatch.setattr(recovery.subprocess, 'run', claim_with_contended_sqlite)
    started = time.monotonic()
    with pytest.raises(recovery.RecoveryEvidenceError):
        recovery.execute_operator_pickup(**_args(case))
    assert time.monotonic() - started < 10
    assert cleanup_finished.wait(10)
    for thread in threads: thread.join(timeout=10)
    task_id = case['receipt']['predecessor']['task_id']
    assert len([e for e in case['store'].list_events(task_id) if e.event_type == 'task.claimed']) == 1
    assert 2 not in case['comments']
    monkeypatch.setattr(recovery.subprocess, 'run', original)
    assert recovery.execute_operator_pickup(**_args(case))['state'] == 'pinned'
    assert len([e for e in case['store'].list_events(task_id) if e.event_type == 'task.claimed']) == 2


@pytest.mark.parametrize('entry', ['pickup', 'resume'])
@pytest.mark.parametrize('mutation', ['edit', 'delete'])
def test_ack_changed_after_readback_before_pin_is_not_pinned(operator_case, monkeypatch, entry, mutation):
    case = operator_case
    if entry == 'resume':
        run = recovery.subprocess.run
        def lost(args, **kwargs):
            if args[0] == 'gh' and 'POST' in args:
                run(args, **kwargs)
                return subprocess.CompletedProcess(args, 1, stdout='', stderr='response lost')
            return run(args, **kwargs)
        monkeypatch.setattr(recovery.subprocess, 'run', lost)
        with pytest.raises(recovery.RecoveryEvidenceError, match='ACK publication outcome unknown'):
            recovery.execute_operator_pickup(**_args(case))
        monkeypatch.setattr(recovery.subprocess, 'run', run)
    observed_ack = False
    read_ack = recovery._read_unique_operator_ack
    def observed(**kwargs):
        nonlocal observed_ack
        value = read_ack(**kwargs)
        observed_ack = True
        return value
    monkeypatch.setattr(recovery, '_read_unique_operator_ack', observed)
    claim_read = recovery._successor_claim_readback
    def alter(**kwargs):
        nonlocal observed_ack
        value = claim_read(**kwargs)
        if observed_ack:
            observed_ack = False
            if mutation == 'edit': case['comments'][2]['body'] += ' '
            else: del case['comments'][2]
        return value
    monkeypatch.setattr(recovery, '_successor_claim_readback', alter)
    operation = recovery.execute_operator_pickup if entry == 'pickup' else recovery.resume_operator_pickup
    with pytest.raises(recovery.RecoveryEvidenceError):
        operation(**_args(case))
    registry = agent_worktree._default_registry_path(case['cwd'])
    proof = agent_worktree._locked_lifecycle_snapshot(registry)[str(case['worktree'])]['operator_registration']
    assert proof['state'] == 'prepared' and proof.get('ack_intent') is not None
    task_id = case['receipt']['predecessor']['task_id']
    assert len([event for event in case['store'].list_events(task_id) if event.event_type == 'task.claimed']) == 2


@pytest.mark.parametrize('entry', ['pickup', 'resume'])
def test_run_drift_during_pin_refuses_success_and_recovers_without_replay(operator_case, monkeypatch, entry):
    from app.builderops import legacy_run_fence
    case = operator_case
    if entry == 'resume':
        run = recovery.subprocess.run
        def lost(args, **kwargs):
            if args[0] == 'gh' and 'POST' in args:
                run(args, **kwargs)
                return subprocess.CompletedProcess(args, 1, stdout='', stderr='response lost')
            return run(args, **kwargs)
        monkeypatch.setattr(recovery.subprocess, 'run', lost)
        with pytest.raises(recovery.RecoveryEvidenceError, match='ACK publication outcome unknown'):
            recovery.execute_operator_pickup(**_args(case))
        monkeypatch.setattr(recovery.subprocess, 'run', run)
    pin = agent_worktree.pin_operator_registration
    check_processes = legacy_run_fence._check_processes
    drifted = False
    def pin_then_drift(*args, **kwargs):
        nonlocal drifted
        result = pin(*args, **kwargs)
        drifted = True
        return result
    def processes(*args, **kwargs):
        if drifted:
            raise legacy_run_fence.RunFenceError('synthetic process drift after pin')
        return check_processes(*args, **kwargs)
    monkeypatch.setattr(agent_worktree, 'pin_operator_registration', pin_then_drift)
    monkeypatch.setattr(legacy_run_fence, '_check_processes', processes)
    operation = recovery.execute_operator_pickup if entry == 'pickup' else recovery.resume_operator_pickup
    with pytest.raises(recovery.RecoveryEvidenceError, match='process drift after pin'):
        operation(**_args(case))
    registry = agent_worktree._default_registry_path(case['cwd'])
    assert agent_worktree._locked_lifecycle_snapshot(registry)[str(case['worktree'])]['operator_registration']['state'] == 'pinned'
    assert sorted(case['comments']) == [1, 2]
    task_id = case['receipt']['predecessor']['task_id']
    assert len([e for e in case['store'].list_events(task_id) if e.event_type == 'task.claimed']) == 2
    monkeypatch.setattr(agent_worktree, 'pin_operator_registration', pin)
    monkeypatch.setattr(legacy_run_fence, '_check_processes', check_processes)
    assert recovery.resume_operator_pickup(**_args(case))['state'] == 'pinned'
    assert sorted(case['comments']) == [1, 2]
    assert len([e for e in case['store'].list_events(task_id) if e.event_type == 'task.claimed']) == 2


@pytest.mark.parametrize('entry', ['draft', 'preflight', 'pickup', 'resume'])
@pytest.mark.parametrize('problem', ['old_schema', 'pending_quarantine'])
def test_recovery_dispatcher_readback_never_migrates_or_quarantines(operator_case, monkeypatch, entry, problem):
    import sqlite3
    from app.dispatcher.verification_dispatch import VerificationDispatchLedger
    from scripts import legacy_operator_evidence
    from tests.dispatcher.test_verification_dispatch import _write_deployed_v1_run
    case = operator_case
    if entry == 'resume':
        prepare = agent_worktree.prepare_operator_registration
        def interrupted(*args, **kwargs):
            raise agent_worktree.WorktreeLifecycleError('before registration')
        monkeypatch.setattr(agent_worktree, 'prepare_operator_registration', interrupted)
        with pytest.raises(recovery.RecoveryEvidenceError):
            recovery.execute_operator_pickup(**_args(case))
        monkeypatch.setattr(agent_worktree, 'prepare_operator_registration', prepare)
    database = case['store'].db_path
    if problem == 'old_schema':
        with sqlite3.connect(database) as conn:
            conn.execute("UPDATE dispatcher_meta SET value='1' WHERE key='schema_version'")
    else:
        state = VerificationDispatchLedger(case['store'])
        _write_deployed_v1_run(state, supporting_issues=[])
    before = database.read_bytes()
    files = sorted(path.name for path in database.parent.iterdir())
    with pytest.raises(recovery.RecoveryEvidenceError):
        if entry == 'draft':
            legacy_operator_evidence.build_draft(cwd=case['cwd'], issue=case['issue'], pr=case['pr'],
                worktree=case['worktree'], base=case['receipt']['base'], agent=case['agent'], session=case['session'])
        elif entry == 'preflight':
            recovery.preflight_operator_pickup(**{k: v for k, v in _args(case).items() if k != 'run_state_root'})
        elif entry == 'pickup':
            recovery.execute_operator_pickup(**_args(case))
        else:
            recovery.resume_operator_pickup(**_args(case))
    assert database.read_bytes() == before
    assert sorted(path.name for path in database.parent.iterdir()) == files
    assert 2 not in case['comments']


def test_registry_identity_swap_inside_preclaim_lock_is_refused(operator_case, monkeypatch):
    case = operator_case
    preflight = recovery.preflight_operator_pickup
    raw = recovery._raw_branch_under_lock
    target = agent_worktree._default_registry_path(case['cwd']).with_name('foreign-registry.json')
    def install_swap(**kwargs):
        observed = preflight(**kwargs)
        def swap(registry, **raw_kwargs):
            rows = raw(registry, **raw_kwargs)
            registry.rename(target)
            registry.symlink_to(target)
            return rows
        monkeypatch.setattr(recovery, '_raw_branch_under_lock', swap)
        return observed
    monkeypatch.setattr(recovery, 'preflight_operator_pickup', install_swap)
    with pytest.raises(recovery.RecoveryEvidenceError):
        recovery.execute_operator_pickup(**_args(case))
    task_id = case['receipt']['predecessor']['task_id']
    assert len([event for event in case['store'].list_events(task_id) if event.event_type == 'task.claimed']) == 1
    assert 2 not in case['comments'] and target.is_file()


@pytest.mark.parametrize('entry', ['pickup', 'resume'])
@pytest.mark.parametrize('drift', ['claim', 'registry'])
def test_post_pin_claim_or_registration_drift_refuses_success(operator_case, monkeypatch, entry, drift):
    case = operator_case
    if entry == 'resume':
        run = recovery.subprocess.run
        def lost(args, **kwargs):
            if args[0] == 'gh' and 'POST' in args:
                run(args, **kwargs)
                return subprocess.CompletedProcess(args, 1, stdout='', stderr='response lost')
            return run(args, **kwargs)
        monkeypatch.setattr(recovery.subprocess, 'run', lost)
        with pytest.raises(recovery.RecoveryEvidenceError, match='ACK publication outcome unknown'):
            recovery.execute_operator_pickup(**_args(case))
        monkeypatch.setattr(recovery.subprocess, 'run', run)
    pin = agent_worktree.pin_operator_registration
    saved = {}
    def change_after_pin(*args, **kwargs):
        result = pin(*args, **kwargs)
        if drift == 'claim':
            task_id = case['receipt']['predecessor']['task_id']
            task = case['store'].get_task(task_id)
            saved['task'] = copy.deepcopy(task)
            task.claimed_by = 'different-agent'
            case['store'].upsert_task(task)
        else:
            registry = agent_worktree._default_registry_path(case['cwd'])
            with agent_worktree._locked_registry(registry) as payload:
                saved['row'] = copy.deepcopy(payload['worktrees'][str(case['worktree'])])
                payload['worktrees'][str(case['worktree'])]['owner'] = 'different-session'
        return result
    monkeypatch.setattr(agent_worktree, 'pin_operator_registration', change_after_pin)
    operation = recovery.execute_operator_pickup if entry == 'pickup' else recovery.resume_operator_pickup
    with pytest.raises(recovery.RecoveryEvidenceError):
        operation(**_args(case))
    assert sorted(case['comments']) == [1, 2]
    task_id = case['receipt']['predecessor']['task_id']
    assert len([e for e in case['store'].list_events(task_id) if e.event_type == 'task.claimed']) == 2
    monkeypatch.setattr(agent_worktree, 'pin_operator_registration', pin)
    if drift == 'claim':
        case['store'].upsert_task(saved['task'])
    else:
        registry = agent_worktree._default_registry_path(case['cwd'])
        with agent_worktree._locked_registry(registry) as payload:
            payload['worktrees'][str(case['worktree'])] = saved['row']
    assert recovery.resume_operator_pickup(**_args(case))['state'] == 'pinned'
    assert sorted(case['comments']) == [1, 2]
    assert len([e for e in case['store'].list_events(task_id) if e.event_type == 'task.claimed']) == 2


@pytest.mark.parametrize('effect', ['claim', 'ack'])
def test_registry_fence_is_held_through_claim_and_ack_effect(operator_case, monkeypatch, effect):
    case = operator_case
    registry = agent_worktree._default_registry_path(case['cwd'])
    original = recovery.subprocess.run
    entered = threading.Event()
    workers = []
    def observed(args, **kwargs):
        is_claim = len(args) > 3 and args[1:4] == ['-m', 'app.dispatcher', 'claim']
        is_ack = args[0] == 'gh' and 'POST' in args
        if (effect == 'claim' and is_claim) or (effect == 'ack' and is_ack):
            def writer():
                with agent_worktree._registry_lock(registry):
                    entered.set()
            thread = threading.Thread(target=writer)
            workers.append(thread)
            thread.start()
            assert not entered.wait(0.25)
        return original(args, **kwargs)
    monkeypatch.setattr(recovery.subprocess, 'run', observed)
    assert recovery.execute_operator_pickup(**_args(case))['state'] == 'pinned'
    assert workers
    for thread in workers:
        thread.join(timeout=10)
        assert not thread.is_alive()
    assert entered.is_set()


def test_registry_lock_identity_swap_inside_preclaim_is_refused(operator_case, monkeypatch):
    case = operator_case
    preflight = recovery.preflight_operator_pickup
    raw = recovery._raw_branch_under_lock
    def install_swap(**kwargs):
        observed = preflight(**kwargs)
        def swap(registry, **raw_kwargs):
            rows = raw(registry, **raw_kwargs)
            lock = registry.with_suffix(registry.suffix + '.lock')
            lock.rename(lock.with_name('displaced-registry.lock'))
            lock.touch()
            return rows
        monkeypatch.setattr(recovery, '_raw_branch_under_lock', swap)
        return observed
    monkeypatch.setattr(recovery, 'preflight_operator_pickup', install_swap)
    with pytest.raises(recovery.RecoveryEvidenceError):
        recovery.execute_operator_pickup(**_args(case))
    task_id = case['receipt']['predecessor']['task_id']
    assert len([event for event in case['store'].list_events(task_id) if event.event_type == 'task.claimed']) == 1
    assert 2 not in case['comments']


def test_lost_ack_resume_refuses_conflicting_authenticated_ack(operator_case, monkeypatch):
    case = operator_case
    run = recovery.subprocess.run
    posts = []
    def lost(args, **kwargs):
        if args[0] == 'gh' and 'POST' in args:
            posts.append(1)
            run(args, **kwargs)
            return subprocess.CompletedProcess(args, 1, stdout='', stderr='response lost')
        return run(args, **kwargs)
    monkeypatch.setattr(recovery.subprocess, 'run', lost)
    with pytest.raises(recovery.RecoveryEvidenceError, match='ACK publication outcome unknown'):
        recovery.execute_operator_pickup(**_args(case))
    duplicate = copy.deepcopy(case['comments'][2])
    duplicate['id'] = 3
    body = json.loads(duplicate['body'])
    body['operator_reconciliation.v1']['successor_acknowledgment']['ack_attempt_id'] = 'f' * 32
    duplicate['body'] = json.dumps(body)
    case['comments'][3] = duplicate
    with pytest.raises(recovery.RecoveryEvidenceError, match='ambiguous'):
        recovery.resume_operator_pickup(**_args(case))
    registry = agent_worktree._default_registry_path(case['cwd'])
    proof = agent_worktree._locked_lifecycle_snapshot(registry)[str(case['worktree'])]['operator_registration']
    assert proof['state'] == 'prepared' and len(posts) == 1


def test_operator_claim_ignores_inherited_dispatcher_path_overrides(operator_case, tmp_path, monkeypatch):
    import shutil
    case = operator_case
    foreign = tmp_path / 'foreign-dispatcher'
    foreign.mkdir()
    foreign_db = foreign / 'alternate.sqlite3'
    foreign_events = foreign / 'alternate-events.jsonl'
    shutil.copy2(case['store'].db_path, foreign_db)
    shutil.copy2(case['store']._event_writer.path, foreign_events)
    before_db, before_events = foreign_db.read_bytes(), foreign_events.read_bytes()
    names = sorted(path.name for path in foreign.iterdir())
    monkeypatch.setenv('DISPATCHER_STATE_DIR', str(foreign))
    monkeypatch.setenv('DISPATCHER_DB_PATH', str(foreign_db))
    monkeypatch.setenv('DISPATCHER_EVENTS_PATH', str(foreign_events))
    result = recovery.execute_operator_pickup(**_args(case))
    assert result['state'] == 'pinned'
    task = case['store'].get_task(result['task_id'])
    assert task.lease_id == result['lease_id'] and task.claimed_by == case['agent']
    assert foreign_db.read_bytes() == before_db and foreign_events.read_bytes() == before_events
    assert sorted(path.name for path in foreign.iterdir()) == names


@pytest.mark.parametrize('entry', ['pickup', 'resume'])
@pytest.mark.parametrize('drift', ['issue', 'lease'])
def test_prepare_rechecks_after_waiting_for_write_lock(operator_case, monkeypatch, entry, drift):
    import contextlib
    import inspect

    case = operator_case
    if entry == 'resume':
        prepare = agent_worktree.prepare_operator_registration
        def stop_after_claim(*args, **kwargs):
            raise agent_worktree.WorktreeLifecycleError('synthetic stop before prepare')
        monkeypatch.setattr(agent_worktree, 'prepare_operator_registration', stop_after_claim)
        with pytest.raises(recovery.RecoveryEvidenceError, match='retain claim'):
            recovery.execute_operator_pickup(**_args(case))
        monkeypatch.setattr(agent_worktree, 'prepare_operator_registration', prepare)

    registry = agent_worktree._default_registry_path(case['cwd'])
    held, release, waiting = (threading.Event() for _ in range(3))
    def holder():
        with agent_worktree._registry_lock(registry):
            held.set()
            assert release.wait(15)
    threads = []
    original = agent_worktree._locked_operator_registry
    @contextlib.contextmanager
    def block_write(*args, **kwargs):
        if any(frame.function == 'register_worktree' for frame in inspect.stack()):
            thread = threading.Thread(target=holder)
            threads.append(thread)
            thread.start()
            assert held.wait(10)
            waiting.set()
        with original(*args, **kwargs) as payload:
            yield payload
    monkeypatch.setattr(agent_worktree, '_locked_operator_registry', block_write)
    operation = recovery.execute_operator_pickup if entry == 'pickup' else recovery.resume_operator_pickup
    task_id = case['receipt']['predecessor']['task_id']
    with ThreadPoolExecutor(max_workers=1) as pool:
        future = pool.submit(operation, **_args(case))
        try:
            assert waiting.wait(15)
            if drift == 'issue':
                case['issue_data']['state'] = 'closed'
            else:
                task = case['store'].get_task(task_id)
                task.claimed_by = 'other-agent'
                case['store'].upsert_task(task)
        finally:
            release.set()
        with pytest.raises(recovery.RecoveryEvidenceError):
            future.result(timeout=30)
    for thread in threads: thread.join(timeout=10)
    row = agent_worktree._locked_lifecycle_snapshot(registry)[str(case['worktree'])]
    assert row == case['receipt']['predecessor_registration']
    assert len([e for e in case['store'].list_events(task_id) if e.event_type == 'task.claimed']) == 2
    assert 2 not in case['comments']


def test_ack_added_during_intent_lock_wait_refuses_intent(operator_case, monkeypatch):
    import contextlib
    import inspect

    case = operator_case
    registry = agent_worktree._default_registry_path(case['cwd'])
    held, release, waiting = (threading.Event() for _ in range(3))
    def holder():
        with agent_worktree._registry_lock(registry):
            held.set()
            assert release.wait(15)
    threads = []
    original = agent_worktree._locked_operator_registry
    @contextlib.contextmanager
    def block_write(*args, **kwargs):
        if any(frame.function == 'begin_operator_ack' for frame in inspect.stack()):
            thread = threading.Thread(target=holder)
            threads.append(thread)
            thread.start()
            assert held.wait(10)
            waiting.set()
        with original(*args, **kwargs) as payload:
            yield payload
    monkeypatch.setattr(agent_worktree, '_locked_operator_registry', block_write)
    with ThreadPoolExecutor(max_workers=1) as pool:
        future = pool.submit(recovery.execute_operator_pickup, **_args(case))
        try:
            assert waiting.wait(15)
            case['comments'][3] = _comment({**case['receipt'], 'successor_acknowledgment': {'attempt': 'conflict'}}, 3, time.time())
        finally:
            release.set()
        with pytest.raises(recovery.RecoveryEvidenceError):
            future.result(timeout=30)
    for thread in threads: thread.join(timeout=10)
    row = agent_worktree._locked_lifecycle_snapshot(registry)[str(case['worktree'])]
    assert row['operator_registration']['state'] == 'prepared'
    assert row['operator_registration'].get('ack_intent') is None
    task_id = case['receipt']['predecessor']['task_id']
    assert len([e for e in case['store'].list_events(task_id) if e.event_type == 'task.claimed']) == 2
    assert 2 not in case['comments']


@pytest.mark.parametrize('replacement', ['symlink', 'regular'])
def test_dispatcher_db_swap_after_header_refuses_without_reading_replacement(operator_case, tmp_path, monkeypatch, replacement):
    import shutil
    case = operator_case
    database = case['store'].db_path
    foreign = tmp_path / 'foreign.sqlite3'
    shutil.copy2(database, foreign)
    displaced = tmp_path / 'displaced.sqlite3'
    before = database.read_bytes()
    read = recovery.os.read
    swapped = False
    def swap_after_header(fd, count):
        nonlocal swapped
        value = read(fd, count)
        if count == 100 and not swapped:
            swapped = True
            database.rename(displaced)
            if replacement == 'symlink': database.symlink_to(foreign)
            else: shutil.copy2(foreign, database)
        return value
    monkeypatch.setattr(recovery.os, 'read', swap_after_header)
    with pytest.raises(recovery.RecoveryEvidenceError):
        recovery.read_live_predecessor(cwd=case['cwd'], issue=case['issue'])
    assert swapped and displaced.read_bytes() == before and foreign.read_bytes() == before
    assert case['store']._event_writer.path.is_file()


@pytest.mark.parametrize('replacement', ['symlink', 'regular'])
def test_dispatcher_db_swap_at_claim_refuses_before_wrong_database_write(operator_case, tmp_path, monkeypatch, replacement):
    import shutil
    case = operator_case
    database = case['store'].db_path
    foreign = tmp_path / 'foreign.sqlite3'
    shutil.copy2(database, foreign)
    displaced = tmp_path / 'displaced.sqlite3'
    before = database.read_bytes()
    events = case['store']._event_writer.path
    before_events = events.read_bytes()
    run = recovery.subprocess.run
    swapped = False
    def swap_at_claim(args, **kwargs):
        nonlocal swapped
        if len(args) > 3 and args[1:4] == ['-m', 'app.dispatcher', 'claim']:
            swapped = True
            database.rename(displaced)
            if replacement == 'symlink': database.symlink_to(foreign)
            else: shutil.copy2(foreign, database)
        return run(args, **kwargs)
    monkeypatch.setattr(recovery.subprocess, 'run', swap_at_claim)
    with pytest.raises(recovery.RecoveryEvidenceError, match='identity'):
        recovery.execute_operator_pickup(**_args(case))
    assert swapped and displaced.read_bytes() == before and foreign.read_bytes() == before
    if replacement == 'regular': assert database.read_bytes() == before
    assert events.read_bytes() == before_events and 2 not in case['comments']


@pytest.mark.parametrize('effect', ['claim', 'ack'])
@pytest.mark.parametrize('identity', ['registry', 'lock'])
def test_registry_identity_drift_during_effect_is_unknown_and_resumed_without_replay(operator_case, monkeypatch, effect, identity):
    case = operator_case
    registry = agent_worktree._default_registry_path(case['cwd'])
    path = registry if identity == 'registry' else registry.with_suffix(registry.suffix + '.lock')
    displaced = path.with_name('displaced-' + path.name)
    run = recovery.subprocess.run
    posts = []
    switched = False
    def mutate(args, **kwargs):
        nonlocal switched
        is_claim = len(args) > 3 and args[1:4] == ['-m', 'app.dispatcher', 'claim']
        is_ack = args[0] == 'gh' and 'POST' in args
        if is_ack: posts.append(1)
        result = run(args, **kwargs)
        if not switched and ((effect == 'claim' and is_claim) or (effect == 'ack' and is_ack)):
            switched = True
            path.rename(displaced)
            if identity == 'registry': path.symlink_to(displaced)
            else: path.touch()
        return result
    monkeypatch.setattr(recovery.subprocess, 'run', mutate)
    with pytest.raises(recovery.RecoveryEvidenceError, match='outcome unknown'):
        recovery.execute_operator_pickup(**_args(case))
    assert switched and len(posts) == (1 if effect == 'ack' else 0)
    path.unlink()
    displaced.rename(path)
    task_id = case['receipt']['predecessor']['task_id']
    assert len([e for e in case['store'].list_events(task_id) if e.event_type == 'task.claimed']) == 2
    result = recovery.resume_operator_pickup(**_args(case))
    assert result['state'] == 'pinned' and len(posts) == 1
    assert len([e for e in case['store'].list_events(task_id) if e.event_type == 'task.claimed']) == 2


@pytest.mark.parametrize('change', ['added', 'changed'])
def test_operator_refuses_relevant_prior_binding_tombstones_before_draft_and_claim(operator_case, tmp_path, change):
    from scripts import legacy_operator_evidence
    case = operator_case
    registry = agent_worktree._default_registry_path(case['cwd'])
    key = str(tmp_path / 'retired-history')
    with agent_worktree._locked_registry(registry) as payload:
        row = copy.deepcopy(case['old_record'])
        row.update(path=key, branch='codex/retired', status='removed', removed_at=time.time() - 50,
                   prior_bindings=[{'branch': 'codex/example', 'removed_at': time.time() - (50 if change == 'added' else 40)}])
        payload['worktrees'][key] = row
    with pytest.raises(recovery.RecoveryEvidenceError):
        legacy_operator_evidence.build_draft(cwd=case['cwd'], issue=case['issue'], pr=case['pr'],
            worktree=case['worktree'], base=case['receipt']['base'], agent=case['agent'], session=case['session'])
    with pytest.raises(recovery.RecoveryEvidenceError):
        recovery.execute_operator_pickup(**_args(case))
    task_id = case['receipt']['predecessor']['task_id']
    assert len([event for event in case['store'].list_events(task_id) if event.event_type == 'task.claimed']) == 1
    with agent_worktree._locked_registry(registry) as payload:
        del payload['worktrees'][key]
    fresh = legacy_operator_evidence.build_draft(cwd=case['cwd'], issue=case['issue'], pr=case['pr'],
        worktree=case['worktree'], base=case['receipt']['base'], agent=case['agent'], session=case['session'])
    assert fresh['operator_reconciliation.v1']['writer']['state'] is None


def test_unrelated_tombstone_does_not_block_operator_pickup(operator_case, tmp_path):
    case = operator_case
    registry = agent_worktree._default_registry_path(case['cwd'])
    key = str(tmp_path / 'unrelated-retired')
    with agent_worktree._locked_registry(registry) as payload:
        row = copy.deepcopy(case['old_record'])
        row.update(path=key, branch='codex/retired', status='removed', removed_at=time.time() - 50,
                   prior_bindings=[{'branch': 'codex/unrelated', 'removed_at': time.time() - 50}])
        payload['worktrees'][key] = row
    assert recovery.execute_operator_pickup(**_args(case))['state'] == 'pinned'


@pytest.mark.parametrize('effect', ['claim', 'ack', 'ack_post', 'pin'])
@pytest.mark.parametrize('drift', ['issue', 'pr', 'lease', 'ack'])
def test_effect_rechecks_after_waiting_for_registry_lock(operator_case, monkeypatch, effect, drift):
    import contextlib
    case = operator_case
    registry = agent_worktree._default_registry_path(case['cwd'])
    held, release, waiting, armed = (threading.Event() for _ in range(4))
    threads = []
    def holder():
        with agent_worktree._registry_lock(registry):
            held.set()
            if not release.wait(15):
                raise AssertionError('test did not release registry lock')
    def arm():
        thread = threading.Thread(target=holder)
        threads.append(thread)
        thread.start()
        assert held.wait(10)
        armed.set()
    original_lock = agent_worktree._locked_existing_registry
    @contextlib.contextmanager
    def observed_lock(*args, **kwargs):
        if effect == 'ack_post' and not armed.is_set():
            import inspect
            if any(frame.function == '_post_and_pin_operator_ack' and frame.code_context
                   and '_locked_existing_registry' in frame.code_context[0] for frame in inspect.stack()):
                arm()
        if armed.is_set(): waiting.set()
        with original_lock(*args, **kwargs) as reader:
            yield reader
    monkeypatch.setattr(agent_worktree, '_locked_existing_registry', observed_lock)
    if effect == 'pin':
        import inspect
        original_write = agent_worktree._locked_operator_registry
        @contextlib.contextmanager
        def observed_write(*args, **kwargs):
            if any(frame.function == 'pin_operator_registration' for frame in inspect.stack()):
                arm()
                waiting.set()
            with original_write(*args, **kwargs) as payload:
                yield payload
        monkeypatch.setattr(agent_worktree, '_locked_operator_registry', observed_write)
    if effect == 'claim':
        preflight = recovery.preflight_operator_pickup
        def preflight_then_hold(**kwargs):
            result = preflight(**kwargs)
            arm()
            return result
        monkeypatch.setattr(recovery, 'preflight_operator_pickup', preflight_then_hold)
    elif effect == 'ack':
        begin = agent_worktree.begin_operator_ack
        def begin_then_hold(*args, **kwargs):
            result = begin(*args, **kwargs)
            arm()
            return result
        monkeypatch.setattr(agent_worktree, 'begin_operator_ack', begin_then_hold)
    with ThreadPoolExecutor(max_workers=1) as pool:
        future = pool.submit(recovery.execute_operator_pickup, **_args(case))
        try:
            assert waiting.wait(15)
            if drift == 'issue': case['issue_data']['state'] = 'closed'
            elif drift == 'pr': case['pr_data']['head']['sha'] = '0' * 40
            elif drift == 'ack':
                case['comments'][3] = _comment({**case['receipt'], 'successor_acknowledgment': {'attempt': 'conflict'}}, 3, time.time())
            else:
                task = case['store'].get_task(case['receipt']['predecessor']['task_id'])
                task.claimed_by = 'other-agent'
                case['store'].upsert_task(task)
        finally:
            release.set()
        with pytest.raises(recovery.RecoveryEvidenceError):
            future.result(timeout=30)
    for thread in threads: thread.join(timeout=10)
    task_id = case['receipt']['predecessor']['task_id']
    assert len([e for e in case['store'].list_events(task_id) if e.event_type == 'task.claimed']) == (1 if effect == 'claim' else 2)
    assert (2 in case['comments']) == (effect == 'pin')


@pytest.mark.parametrize('replacement', ['symlink', 'regular'])
def test_dispatcher_read_uses_original_fd_if_path_swaps_during_sqlite_open(operator_case, tmp_path, monkeypatch, replacement):
    import shutil
    case = operator_case
    database = case['store'].db_path
    foreign = tmp_path / 'foreign.sqlite3'
    shutil.copy2(database, foreign)
    displaced = tmp_path / 'displaced.sqlite3'
    before = database.read_bytes()
    sqlite_open = recovery.sqlite3.connect
    swapped = False
    def swap_then_open(target, *args, **kwargs):
        nonlocal swapped
        if isinstance(target, str) and target.startswith('file:/dev/fd/') and not swapped:
            swapped = True
            database.rename(displaced)
            if replacement == 'symlink': database.symlink_to(foreign)
            else: shutil.copy2(foreign, database)
        return sqlite_open(target, *args, **kwargs)
    monkeypatch.setattr(recovery.sqlite3, 'connect', swap_then_open)
    with pytest.raises(recovery.RecoveryEvidenceError, match='identity'):
        recovery.read_live_predecessor(cwd=case['cwd'], issue=case['issue'])
    assert swapped and displaced.read_bytes() == before and foreign.read_bytes() == before


def test_dispatcher_db_identity_drift_after_claim_is_unknown_and_resumes(operator_case, tmp_path, monkeypatch):
    import shutil
    case = operator_case
    database = case['store'].db_path
    displaced = tmp_path / 'original-dispatcher.sqlite3'
    run = recovery.subprocess.run
    switched = False
    def swap_after_claim(args, **kwargs):
        nonlocal switched
        result = run(args, **kwargs)
        if not switched and len(args) > 3 and args[1:4] == ['-m', 'app.dispatcher', 'claim']:
            switched = True
            database.rename(displaced)
            shutil.copy2(displaced, database)
        return result
    monkeypatch.setattr(recovery.subprocess, 'run', swap_after_claim)
    with pytest.raises(recovery.RecoveryEvidenceError, match='claim outcome unknown'):
        recovery.execute_operator_pickup(**_args(case))
    assert switched and 2 not in case['comments']
    database.unlink()
    displaced.rename(database)
    monkeypatch.setattr(recovery.subprocess, 'run', run)
    task_id = case['receipt']['predecessor']['task_id']
    assert len([e for e in case['store'].list_events(task_id) if e.event_type == 'task.claimed']) == 2
    assert recovery.resume_operator_pickup(**_args(case))['state'] == 'pinned'
    assert len([e for e in case['store'].list_events(task_id) if e.event_type == 'task.claimed']) == 2


def test_lost_ack_resume_refuses_conflicting_ack_on_pr(operator_case, monkeypatch):
    case = operator_case
    run = recovery.subprocess.run
    posts = []
    def lost(args, **kwargs):
        if args[0] == 'gh' and 'POST' in args:
            posts.append(1)
            run(args, **kwargs)
            return subprocess.CompletedProcess(args, 1, stdout='', stderr='response lost')
        return run(args, **kwargs)
    monkeypatch.setattr(recovery.subprocess, 'run', lost)
    with pytest.raises(recovery.RecoveryEvidenceError, match='ACK publication outcome unknown'):
        recovery.execute_operator_pickup(**_args(case))
    duplicate = copy.deepcopy(case['comments'][2])
    duplicate['id'] = 3
    duplicate['issue_url'] = f"https://api.github.com/repos/RasmusTho/agentic-pkm-mvp/issues/{case['pr']}"
    body = json.loads(duplicate['body'])
    body['operator_reconciliation.v1']['successor_acknowledgment']['ack_attempt_id'] = 'f' * 32
    duplicate['body'] = json.dumps(body)
    github = recovery._github_read
    def github_with_pr_ack(args, *, cwd):
        if '--slurp' in args and any(f"/issues/{case['pr']}/comments" in value for value in args):
            return json.dumps([[duplicate]])
        return github(args, cwd=cwd)
    monkeypatch.setattr(recovery, '_github_read', github_with_pr_ack)
    with pytest.raises(recovery.RecoveryEvidenceError, match='ambiguous'):
        recovery.resume_operator_pickup(**_args(case))
    registry = agent_worktree._default_registry_path(case['cwd'])
    assert agent_worktree._locked_lifecycle_snapshot(registry)[str(case['worktree'])]['operator_registration']['state'] == 'prepared'
    assert len(posts) == 1


def test_guarded_claim_refuses_database_swap_during_sqlite_open(operator_case, tmp_path, monkeypatch):
    import shutil
    case = operator_case
    database = case['store'].db_path
    foreign = tmp_path / 'foreign.sqlite3'
    displaced = tmp_path / 'displaced.sqlite3'
    shutil.copy2(database, foreign)
    before = database.read_bytes()
    events = case['store']._event_writer.path
    before_events = events.read_bytes()
    identity = (database.stat().st_dev, database.stat().st_ino)
    connect = leases.sqlite3.connect
    swapped = False
    def swap_then_connect(target, *args, **kwargs):
        nonlocal swapped
        if Path(target) == database and not swapped:
            swapped = True
            database.rename(displaced)
            shutil.copy2(foreign, database)
        return connect(target, *args, **kwargs)
    monkeypatch.setattr(leases.sqlite3, 'connect', swap_then_connect)
    task_id = case['receipt']['predecessor']['task_id']
    with pytest.raises(ValueError, match='identity changed'):
        leases.claim(case['store'], task_id, 'new-agent', takeover_stale=True,
                     expected_lease_id=case['old_lease'].lease_id, expected_db_identity=identity)
    assert swapped and displaced.read_bytes() == before and foreign.read_bytes() == before
    assert database.read_bytes() == before and events.read_bytes() == before_events
