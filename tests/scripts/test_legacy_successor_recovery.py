"""Exercise the scoped operator transition with isolated Git and dispatcher state."""
from __future__ import annotations

import copy
import hashlib
import json
import os
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
from app.dispatcher import store as dispatcher_store
from app.dispatcher.store import SqliteStore
from scripts import agent_worktree
from tests.builderops import test_legacy_run_fence_6561 as sources_6561


@pytest.fixture
def codex_6561_source(tmp_path, monkeypatch):
    return sources_6561.source_bound.__wrapped__(tmp_path, monkeypatch)

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
    return {"id": ident, "node_id": f"IC_{ident}", "performed_via_github_app": None,
            "user": {"login": "RasmusTho", "id": 123, "node_id": "U_example", "type": "User"},
            "author_association": "OWNER",
            "created_at": at, "updated_at": at,
            "issue_url": f"https://api.github.com/repos/RasmusTho/agentic-pkm-mvp/issues/{body['issue']}",
            "body": json.dumps({"operator_reconciliation.v1": body}, sort_keys=True)}


@pytest.fixture
def operator_case(tmp_path, monkeypatch, request):
    params = getattr(request, "param", (6601, 6602, "old-agent", 0))
    if isinstance(params, int):
        params = (params, 6602, "old-agent", 0)
    issue, pr_number, old_agent, heartbeat_count = params[:4]
    overlapping_main = len(params) == 5 and params[4] == "overlapping-main"
    old_owner = (f"{old_agent}-20261102" if heartbeat_count == 11 else
                 old_agent.removeprefix("openhands-") if heartbeat_count else "old-session")
    repo = tmp_path / "agentic-pkm-mvp"
    repo.mkdir()
    _git(repo, "init", "-b", "main")
    _git(repo, "config", "user.name", "Fixture")
    _git(repo, "config", "user.email", "fixture@example.invalid")
    (repo / "file.txt").write_text("base\n")
    (repo / "tests/properties").mkdir(parents=True)
    (repo / "tests/test_fixture.py").write_text("def test_fixture(): pass\n")
    for name in ("_machinery.py", "test_guard_at_seam.py"):
        content = ''.join(f'base line {i}\n' for i in range(30)) if overlapping_main else 'base\n'
        (repo / "tests/properties" / name).write_text(content)
    _git(repo, "add", "file.txt", "tests")
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
        minutes_list = ([225, 218, 211, 204, 197, 190, 183, 176, 169, 162, 155] if heartbeat_count == 11 else
                        [225, 210, 195, 180, 165, 150, 135, 120, 105] if heartbeat_count == 9 else
                        [225, 210, 195, 180, 165, 150] if heartbeat_count == 6 else
                        [195, 150] if heartbeat_count == 2 else [110, 100])
        for position, minutes in enumerate(minutes_list):
            heartbeat_time = datetime.now(timezone.utc) - timedelta(minutes=minutes)
            heartbeat_at = heartbeat_time.isoformat(timespec="microseconds")
            patch.setattr(leases, "_utc_now", lambda: heartbeat_at)
            leases.heartbeat(store, task_id, old_agent)
            if (heartbeat_count == 11 and position == 5) or (heartbeat_count == 9 and position == 1):
                updated_at = (heartbeat_time + timedelta(minutes=3)).isoformat(timespec="microseconds")
                task = store.get_task(task_id)
                task.linked_pr = str(pr_number)
                task.updated_at = updated_at
                store.upsert_task(task)
                store.append_event(EventRecord(event_id="fixture-linked-pr", timestamp=updated_at,
                    task_id=task_id, event_type="task.updated", actor=old_agent,
                    payload={"linked_pr": pr_number}))

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
    pr = {"number": pr_number, "state": "open", "draft": False, "body": pr_body,
          "updated_at": datetime.fromtimestamp(now, timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"), "head": {"ref": "codex/example", "sha": head,
          "repo": {"full_name": "RasmusTho/agentic-pkm-mvp"}},
          "base": {"ref": "main", "sha": base, "repo": {"full_name": "RasmusTho/agentic-pkm-mvp"}}}

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
            "issue_data": issue_data, "github_read": github_read}


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


@pytest.mark.parametrize("drift", ["closed", "label_removed"])
def test_issue_drift_during_final_run_check_refuses_before_claim(operator_case, monkeypatch, drift):
    from app.builderops import legacy_run_fence

    case = operator_case
    check = legacy_run_fence.check_locked
    calls = 0

    def drift_during_check(**kwargs):
        nonlocal calls
        check(**kwargs)
        calls += 1
        if calls == 2:  # The held run is rechecked immediately before the claim.
            if drift == "closed":
                case["issue_data"]["state"] = "closed"
            else:
                case["issue_data"]["labels"] = []

    monkeypatch.setattr(legacy_run_fence, "check_locked", drift_during_check)
    with pytest.raises(recovery.RecoveryEvidenceError, match="current issue validation"):
        recovery.execute_operator_pickup(**_args(case))
    task_id = case["receipt"]["predecessor"]["task_id"]
    claims = [event for event in case["store"].list_events(task_id) if event.event_type == "task.claimed"]
    assert calls == 2
    assert len(claims) == 1
    assert case["store"].get_task(task_id).lease_id == case["old_lease"].lease_id
    assert 2 not in case["comments"]


def test_operator_refuses_workspace_overlap_before_claim(operator_case):
    case = operator_case
    case["workspace_root"].mkdir()
    overlapping = case["workspace_root"] / "other-checkout"
    _git(case["cwd"], "worktree", "add", "--detach", str(overlapping))
    with pytest.raises(recovery.RecoveryEvidenceError, match="outside model workspaces"):
        recovery.execute_operator_pickup(**_args(case))
    task_id = case["receipt"]["predecessor"]["task_id"]
    claims = [event for event in case["store"].list_events(task_id) if event.event_type == "task.claimed"]
    assert len(claims) == 1
    assert case["store"].get_task(task_id).lease_id == case["old_lease"].lease_id
    assert 2 not in case["comments"]


def test_operator_refuses_workspace_overlap_during_final_run_check(operator_case, monkeypatch):
    from app.builderops import legacy_run_fence

    case = operator_case
    case["workspace_root"].mkdir()
    check = legacy_run_fence.check_locked
    calls = 0

    def add_worktree_during_check(**kwargs):
        nonlocal calls
        check(**kwargs)
        calls += 1
        if calls == 2:
            _git(case["cwd"], "worktree", "add", "--detach", str(case["workspace_root"] / "late-checkout"))

    monkeypatch.setattr(legacy_run_fence, "check_locked", add_worktree_during_check)
    with pytest.raises(recovery.RecoveryEvidenceError, match="outside model workspaces"):
        recovery.execute_operator_pickup(**_args(case))
    task_id = case["receipt"]["predecessor"]["task_id"]
    claims = [event for event in case["store"].list_events(task_id) if event.event_type == "task.claimed"]
    assert calls == 2
    assert len(claims) == 1
    assert case["store"].get_task(task_id).lease_id == case["old_lease"].lease_id
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


@pytest.mark.parametrize("at_read", list(range(2, 14)))
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
    assert len(claims) == (1 if at_read <= 4 else 2)
    assert (2 in case["comments"]) == (at_read >= 11)
    case["issue_data"]["state"] = "open"
    if at_read in (9, 10):
        # An established intent with no readable ACK is ambiguous; never repost.
        with pytest.raises(recovery.RecoveryEvidenceError, match="ACK outcome is unknown or ambiguous"):
            recovery.resume_operator_pickup(**_args(case))
        assert 2 not in case["comments"]
    elif at_read >= 5:
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
    import select

    case = operator_case
    task_id = case['receipt']['predecessor']['task_id']
    store = case['store']
    if lock_kind == 'cleanup':
        lock = leases._cleanup_guard_lock(store)
        lock.__enter__()
        holder = None
    else:
        lock = None
        # Hold the SQLite lock in another process, as a real competing
        # dispatcher does. On POSIX, closing another descriptor for the same
        # file can release this process's fcntl locks, so a connection held by
        # the test process is not a reliable contention fixture on Linux.
        holder = subprocess.Popen(
            [sys.executable, '-u', '-c',
             "import sqlite3,sys; c=sqlite3.connect(sys.argv[1]); "
             "c.execute('BEGIN IMMEDIATE'); print('locked', flush=True); "
             "sys.stdin.readline(); c.rollback(); c.close()", str(store.db_path)],
            stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True,
        )
    try:
        if holder is not None:
            assert holder.stdout is not None
            assert select.select([holder.stdout], [], [], 10)[0], 'lock holder did not start'
            assert holder.stdout.readline().strip() == 'locked'
        started = time.monotonic()
        with pytest.raises(recovery.RecoveryEvidenceError):
            recovery.execute_operator_pickup(**_args(case))
        assert time.monotonic() - started < 10
    finally:
        if holder is not None:
            try:
                holder.communicate(input='release\n', timeout=10)
            except subprocess.TimeoutExpired:
                holder.kill()
                holder.communicate()
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
    sqlite_open = dispatcher_store.sqlite3.connect
    swapped = False
    def swap_then_open(target, *args, **kwargs):
        nonlocal swapped
        if isinstance(target, str) and target.startswith('file:/dev/fd/') and not swapped:
            swapped = True
            database.rename(displaced)
            if replacement == 'symlink': database.symlink_to(foreign)
            else: shutil.copy2(foreign, database)
        return sqlite_open(target, *args, **kwargs)
    monkeypatch.setattr(dispatcher_store.sqlite3, 'connect', swap_then_open)
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

def _make_dirty_6560(case, tmp_path, monkeypatch, *, overlapping_main=False):
    from app.builderops import legacy_codex_6560_guard as guard
    monkeypatch.setattr(guard, "WORKTREE", str(case["worktree"]))
    monkeypatch.setattr(guard, "PR", case["pr"])
    monkeypatch.setattr(guard, "GENERATION", case["old_record"]["generation"])
    monkeypatch.setattr(guard, "OWNER", case["old_record"]["owner"])
    monkeypatch.setattr(guard, "HOLDER", case["receipt"]["predecessor"]["holder"])
    monkeypatch.setattr(guard, "LEASE", case["receipt"]["predecessor"]["lease_id"])
    monkeypatch.setattr(guard, "PR_HEAD", case["receipt"]["publication"]["head"])
    boot = case["receipt"]["writer"]["boot"]
    monkeypatch.setattr(guard, "_host_readback", lambda: (int(datetime.fromisoformat(boot).timestamp()), "", "", ""))
    root = case["worktree"]
    names = ("tests/properties/_machinery.py", "tests/properties/test_guard_at_seam.py")
    blobs = {name: _git(root, "rev-parse", f"HEAD:{name}") for name in names}
    for name in names:
        if overlapping_main:
            lines = (root / name).read_text().splitlines(keepends=True)
            lines[2] = f"dirty {name}\n"
            (root / name).write_text(''.join(lines))
        else:
            (root / name).write_text(f"dirty {name}\n")
    patch = subprocess.check_output(["git", "-C", str(root), "diff", "--binary"])
    backup = tmp_path / "preserved.patch"
    backup.write_bytes(patch)
    receipt = case["receipt"]
    material = {"index_blobs": blobs,
        "file_sha256": {name: hashlib.sha256((root / name).read_bytes()).hexdigest() for name in names},
        "backup": str(backup), "patch_sha256": hashlib.sha256(patch).hexdigest()}
    from scripts import legacy_operator_evidence
    from contextlib import redirect_stdout
    from io import StringIO
    contract_path = tmp_path / "dirty-material.json"
    contract_path.write_text(json.dumps(material))
    output = StringIO()
    with monkeypatch.context() as patcher, redirect_stdout(output):
        patcher.chdir(root)
        patcher.setattr(sys, "argv", ["legacy_operator_evidence", "--issue", "6560", "--pr", str(case["pr"]),
                        "--worktree", str(root), "--base", receipt["base"], "--agent", case["agent"],
                        "--dirty-material-json", str(contract_path)])
        assert legacy_operator_evidence.main() == 0
    draft = json.loads(output.getvalue())["operator_reconciliation.v1"]
    assert draft["dirty_candidate"] == material and draft["writer"]["state"] is None
    assert draft["codex_custody"]["no_new_manual_starts"] is None
    for key in ("mandate", "writer", "publication"):
        draft[key] = copy.deepcopy(receipt[key])
    receipt.clear()
    receipt.update(draft)
    receipt["codex_custody"] = {"issue": 6560, "pr": case["pr"], "worktree": str(root),
        "successor_session": case["session"], "child": guard.CHILD, "delegates": dict(guard.DELEGATES),
        "publication_commands": list(guard.PUBLICATION_COMMANDS),
        "observed_at": (datetime.now(timezone.utc) - timedelta(seconds=10)).isoformat(), "boot": boot,
        "rejected_postboot_resume": -32600, "identified_commands_terminal": True,
        "identified_writes_reconciled": True, "historical_push_outputs": "unknown",
        "historical_edited_bodies": "unknown", "postboot_identified_activity_reconciled": True,
        "no_new_manual_starts": True, "sources": {"app_child_and_delegates": guard.CHILD,
            "sqlite_parent_links": "state_5.sqlite", "available_journal": guard.CHILD,
            "rejected_resume": "-32600", "boot": "kern.boottime", "processes": "ps",
            "launchctl": "launchctl", "crontab": "crontab", "publication": str(case["pr"])}}
    receipt["candidate"] = recovery._read_operator_candidate(cwd=root, worktree=root, receipt=receipt)
    case["comments"][1] = _comment(receipt, 1, time.time() - 5)
    return backup


@pytest.mark.parametrize('operator_case', [(6560, 6565, 'codex-issue-6560', 11)], indirect=True)
@pytest.mark.parametrize('fault', ['lost_claim', 'lost_ack', 'unknown_ack', 'before_prepare'])
def test_6560_cli_recovers_exact_effect_without_replay(operator_case, tmp_path, monkeypatch, capsys, fault):
    case = operator_case
    _make_dirty_6560(case, tmp_path, monkeypatch)
    delegate = recovery.subprocess.run
    original_prepare = agent_worktree.prepare_operator_registration
    posts, claims = [], []

    def transport(args, **kwargs):
        if len(args) > 3 and args[1:4] == ['-m', 'app.dispatcher', 'claim']:
            claims.append(1)
            if fault == 'lost_claim':
                delegate(args, **kwargs)
                return subprocess.CompletedProcess(args, 1, stdout='', stderr='lost claim response')
        if args[0] == 'gh' and 'POST' in args:
            posts.append(1)
            if fault == 'lost_ack':
                delegate(args, **kwargs)
                return subprocess.CompletedProcess(args, 1, stdout='', stderr='lost ACK response')
            if fault == 'unknown_ack':
                return subprocess.CompletedProcess(args, 1, stdout='', stderr='unknown ACK outcome')
        return delegate(args, **kwargs)

    def interrupted_prepare(*_args, **_kwargs):
        raise agent_worktree.WorktreeLifecycleError('fixture interruption before registration')

    monkeypatch.setattr(recovery.subprocess, 'run', transport)
    if fault == 'before_prepare':
        monkeypatch.setattr(agent_worktree, 'prepare_operator_registration', interrupted_prepare)

    def run_cli(action):
        with monkeypatch.context() as patch:
            patch.chdir(case['cwd'])
            patch.setattr(sys, 'argv', ['legacy_owner_recovery', action, '--issue', '6560', '--pr', '6565',
                '--worktree', str(case['worktree']), '--agent', case['agent'], '--session', case['session'],
                '--comment-id', str(case['comment_id']), '--workspace-root', str(case['workspace_root']),
                '--legacy-run-state-root', str(case['run_state_root'])])
            code = recovery._main()
        return code, json.loads(capsys.readouterr().out.splitlines()[0])

    code, result = run_cli('pickup')
    assert code == (0 if fault == 'lost_claim' else 1)
    if fault != 'lost_claim':
        if fault == 'before_prepare':
            monkeypatch.setattr(agent_worktree, 'prepare_operator_registration', original_prepare)
        else:
            row = agent_worktree._locked_lifecycle_snapshot(agent_worktree._default_registry_path(case['cwd']))[str(case['worktree'])]
            assert row['operator_registration']['state'] == 'prepared'
            with pytest.raises(agent_worktree.WorktreeLifecycleError):
                agent_worktree.assert_operator_registration_pinned(row)
        code, result = run_cli('resume')
        assert code == (1 if fault == 'unknown_ack' else 0)
    task_id = case['receipt']['predecessor']['task_id']
    history = case['store'].list_events(task_id)
    assert len([event for event in history if event.event_type == 'task.claimed']) == 2
    assert len(claims) == 1 and len(posts) == 1
    if fault == 'unknown_ack':
        assert 'unknown or ambiguous' in result['error'] and 2 not in case['comments']
    else:
        assert result['state'] == 'pinned' and result['ack_comment_id'] == 2
        if fault == 'lost_claim':
            assert result['claim_exit'] == 1


@pytest.mark.parametrize('operator_case', [(6560, 6565, 'codex-issue-6560', 11, 'overlapping-main')], indirect=True)
@pytest.mark.parametrize('unrelated_staged', [False, True])
def test_6560_first_commit_uses_real_shell_gate_before_main_integration(operator_case, tmp_path, monkeypatch,
                                                                            unrelated_staged):
    """Exercise the actual shell gate and Git; only host/GitHub ports are simulated."""
    from app.builderops.legacy_patch_tree import verify_first_patch_commit

    case = operator_case
    if unrelated_staged:
        (case['worktree'] / 'file.txt').write_text('preserved staged work\n')
        _git(case['worktree'], 'add', 'file.txt')
    _make_dirty_6560(case, tmp_path, monkeypatch, overlapping_main=True)
    result = recovery.execute_operator_pickup(**_args(case))
    assert result['state'] == 'pinned'
    worktree = case['worktree']
    parent = _git(worktree, 'rev-parse', 'HEAD')
    ordinary_index_path = Path(_git(worktree, 'rev-parse', '--path-format=absolute', '--git-path', 'index'))
    original_index_sha256 = hashlib.sha256(ordinary_index_path.read_bytes()).hexdigest()
    names = sorted(case['receipt']['dirty_candidate']['index_blobs'])
    selected = {name: (worktree / name).read_bytes() for name in names}
    ordinary_before = {name: _git(worktree, 'rev-parse', f':{name}') for name in names}
    unrelated_blob = _git(worktree, 'rev-parse', ':file.txt')
    unrelated_bytes = (worktree / 'file.txt').read_bytes()

    primary = tmp_path / 'agentic-pkm-mvp'
    remote = tmp_path / 'remote.git'
    _git(primary, 'init', '--bare', str(remote))
    _git(primary, 'remote', 'add', 'origin', str(remote))
    main_file = primary / 'tests/properties/_machinery.py'
    main_lines = main_file.read_text().splitlines(keepends=True)
    main_lines[27] = 'main change in the selected file\n'
    main_file.write_text(''.join(main_lines))
    _git(primary, 'add', '--', 'tests/properties/_machinery.py')
    _git(primary, 'commit', '-m', 'advance main')
    _git(primary, 'push', '-u', 'origin', 'main')
    main_head = _git(primary, 'rev-parse', 'main')

    scenario = {
        'worktree': str(worktree), 'common': str(primary / '.git'), 'home': str(tmp_path),
        'db': str(case['store'].db_path), 'comments': case['comments'], 'pr': case['pr_data'],
        'issue': case['issue_data'], 'generation': case['old_record']['generation'],
        'owner': case['old_record']['owner'], 'holder': case['receipt']['predecessor']['holder'],
        'lease': case['old_lease'].lease_id, 'head': parent,
        'successor_lease': result['lease_id'], 'task_id': result['task_id'],
        'pending_id': case['comment_id'], 'ack_id': result['ack_comment_id'],
        'boot': int(datetime.fromisoformat(case['receipt']['writer']['boot']).timestamp()),
    }
    scenario_file = tmp_path / 'scenario.json'
    scenario_file.write_text(json.dumps(scenario))
    site = tmp_path / 'python-site'
    site.mkdir()
    (site / 'sitecustomize.py').write_text('''\
import json, os, sys
from pathlib import Path
from types import SimpleNamespace
from app.builderops import legacy_codex_6560_guard as guard, legacy_git_config as config
from app.builderops import legacy_owner_recovery as recovery, openhands_pr_cycle as cycle
from scripts import agent_worktree
s = json.loads(Path(os.environ["SYNTHETIC_6560_SCENARIO"]).read_text())
if os.environ.get("SYNTHETIC_6560_CLOSE_DURING_PREFLIGHT") and sys.argv[0].endswith("git_hygiene_preflight.py"):
    s["issue"]["state"] = "closed"
    Path(os.environ["SYNTHETIC_6560_SCENARIO"]).write_text(json.dumps(s))
config.QUALIFIED_COMMON = Path(s["common"])
config._qualified_home = lambda: Path(s["home"])
config.check_host_config = lambda: None
guard.WORKTREE = s["worktree"]
guard.GENERATION = s["generation"]
guard.OWNER = s["owner"]
guard.HOLDER = s["holder"]
guard.LEASE = s["lease"]
guard.PR_HEAD = s["head"]
guard._host_readback = lambda: (s["boot"], "", "", "")
if os.environ.get("SYNTHETIC_6560_LATE_COMMENT") in {"pending", "ack", "duplicate"}:
    old_guard_check = guard.check
    guard_calls = []
    def late_comment_guard(**kwargs):
        result = old_guard_check(**kwargs)
        guard_calls.append(1)
        if len(guard_calls) == 2:
            kind = os.environ["SYNTHETIC_6560_LATE_COMMENT"]
            if kind == "duplicate":
                duplicate = dict(s["comments"][str(s["ack_id"])])
                duplicate["id"] = 999999
                s["comments"]["999999"] = duplicate
            else:
                key = "pending_id" if kind == "pending" else "ack_id"
                s["comments"][str(s[key])]["updated_at"] = "2001-01-01T00:00:00Z"
            Path(os.environ["SYNTHETIC_6560_SCENARIO"]).with_name("late-" + kind).write_text("injected")
        return result
    guard.check = late_comment_guard
recovery._operator_dispatcher_paths = lambda **kw: SimpleNamespace(db_path=Path(s["db"]))
agent_worktree._read_github_transfer_comment = lambda ident, **kw: s["comments"][str(ident)]
cycle.closure._closing_issue_references = lambda *args, **kw: [6560]
def github(args, *, cwd):
    if args == ["user", "--jq", ".login"]: return "RasmusTho\\n"
    if args == ["repos/RasmusTho/agentic-pkm-mvp/issues/6560"]: return json.dumps(s["issue"])
    if "--slurp" in args and any("/issues/6560/comments" in x for x in args):
        return json.dumps([list(s["comments"].values())])
    if "--slurp" in args and any("/issues/6565/comments" in x for x in args): return json.dumps([[]])
    if "--slurp" in args: return json.dumps([[s["pr"]]])
    if any("/pulls/6565" in x for x in args): return json.dumps(s["pr"])
    if any("/git/ref/heads/" in x for x in args):
        return json.dumps({"ref": "refs/heads/codex/example", "object": {"sha": s["head"]}})
    return json.dumps({"full_name": "RasmusTho/agentic-pkm-mvp", "default_branch": "main"})
recovery._github_read = github
if os.environ.get("SYNTHETIC_6560_LATE_COMMENT") == "index_ack":
    from app.builderops import legacy_patch_tree
    original_index_check = legacy_patch_tree.verify_first_patch_index
    def late_ack_after_index(**kwargs):
        result = original_index_check(**kwargs)
        s["comments"][str(s["ack_id"])]["updated_at"] = "2001-01-01T00:00:00Z"
        Path(os.environ["SYNTHETIC_6560_SCENARIO"]).with_name("late-index_ack").write_text("injected")
        return result
    legacy_patch_tree.verify_first_patch_index = late_ack_after_index
if os.environ.get("SYNTHETIC_6560_EXPIRE_AFTER_INDEX"):
    from app.builderops import legacy_patch_tree
    original_index_check = legacy_patch_tree.verify_first_patch_index
    def expire_after_index(**kwargs):
        import sqlite3
        result = original_index_check(**kwargs)
        with sqlite3.connect(s["db"]) as conn:
            conn.execute("UPDATE dispatcher_leases SET expires_at=? WHERE lease_id=?", ("2000-01-01T00:00:00+00:00", s["successor_lease"]))
            conn.execute("UPDATE dispatcher_tasks SET lease_expires_at=? WHERE task_id=?", ("2000-01-01T00:00:00+00:00", s["task_id"]))
        return result
    legacy_patch_tree.verify_first_patch_index = expire_after_index
''')
    source = Path(__file__).resolve().parents[2]
    env = {k: v for k, v in os.environ.items() if not k.startswith('GIT_')}
    env.update({'PYTHONPATH': f'{site}{os.pathsep}{source}', 'SYNTHETIC_6560_SCENARIO': str(scenario_file),
                'CODEX_SESSION_ID': case['session']})
    script = source / 'scripts/agent_workspace_preflight.sh'
    common_args = ['--cwd', str(worktree), '--expected-branch', 'codex/example',
                   '--expected-worktree', str(worktree), '--allow-dirty']
    special = ['--legacy-6560-agent', case['agent'], '--legacy-6560-session', case['session'],
               '--legacy-6560-head', parent]

    def gate(*args, extra_env=None):
        return subprocess.run([str(script), *common_args, *args], env={**env, **(extra_env or {})},
                              capture_output=True, text=True)

    assert gate().returncode != 0  # The normal gate refuses the stale main.
    assert gate('--base-branch', '', '--legacy-6560-first-commit', 'stage', *special).returncode != 0
    refused = gate('--legacy-6560-first-commit', 'stage', '--legacy-6560-agent', 'wrong-agent', *special[2:])
    assert refused.returncode != 0
    drift = gate('--legacy-6560-first-commit', 'stage', *special,
                 extra_env={'SYNTHETIC_6560_CLOSE_DURING_PREFLIGHT': '1'})
    assert drift.returncode != 0 and _git(worktree, 'rev-parse', 'HEAD') == parent
    assert json.loads(scenario_file.read_text())['issue']['state'] == 'closed'
    scenario_file.write_text(json.dumps(scenario))
    stage = gate('--legacy-6560-first-commit', 'stage', *special)
    assert stage.returncode == 0, stage.stderr + stage.stdout
    if not unrelated_staged:
        for kind in ('pending', 'ack', 'duplicate'):
            late = gate('--legacy-6560-first-commit', 'stage', *special,
                        extra_env={'SYNTHETIC_6560_LATE_COMMENT': kind})
            assert scenario_file.with_name('late-' + kind).exists()
            assert late.returncode != 0, late.stderr + late.stdout

    index = tmp_path / 'first.index'
    isolated_env = {**env, 'GIT_INDEX_FILE': str(index)}
    for args in (('read-tree', 'HEAD'), ('add', '--', *names)):
        subprocess.run(['git', '-C', str(worktree), *args], env=isolated_env, check=True, capture_output=True)
    (worktree / 'file.txt').write_text('unrelated temporary change\n')
    subprocess.run(['git', '-C', str(worktree), 'add', '--', 'file.txt'],
                   env=isolated_env, check=True, capture_output=True)
    assert gate('--legacy-6560-first-commit', 'commit', *special,
                '--legacy-6560-index', str(index)).returncode != 0
    (worktree / 'file.txt').write_bytes(unrelated_bytes)
    for args in (('read-tree', 'HEAD'), ('add', '--', *names)):
        subprocess.run(['git', '-C', str(worktree), *args], env=isolated_env, check=True, capture_output=True)
    if not unrelated_staged:
        late_index = gate('--legacy-6560-first-commit', 'commit', *special, '--legacy-6560-index', str(index),
                          extra_env={'SYNTHETIC_6560_LATE_COMMENT': 'index_ack'})
        assert scenario_file.with_name('late-index_ack').exists()
        assert late_index.returncode != 0, late_index.stderr + late_index.stdout
    with case['store']._connect() as connection:
        lease_expiry = connection.execute('SELECT expires_at FROM dispatcher_leases WHERE lease_id = ?',
                                          (result['lease_id'],)).fetchone()[0]
        task_expiry = connection.execute('SELECT lease_expires_at FROM dispatcher_tasks WHERE task_id = ?',
                                         (result['task_id'],)).fetchone()[0]
    expired = gate('--legacy-6560-first-commit', 'commit', *special, '--legacy-6560-index', str(index),
                   extra_env={'SYNTHETIC_6560_EXPIRE_AFTER_INDEX': '1'})
    assert expired.returncode != 0 and _git(worktree, 'rev-parse', 'HEAD') == parent
    with case['store']._connect() as connection:
        assert connection.execute('SELECT expires_at FROM dispatcher_leases WHERE lease_id = ?',
                                  (result['lease_id'],)).fetchone()[0] == '2000-01-01T00:00:00+00:00', expired.stderr + expired.stdout
        connection.execute('UPDATE dispatcher_leases SET expires_at = ? WHERE lease_id = ?',
                           (lease_expiry, result['lease_id']))
        connection.execute('UPDATE dispatcher_tasks SET lease_expires_at = ? WHERE task_id = ?',
                           (task_expiry, result['task_id']))
        connection.commit()
    commit_gate = gate('--legacy-6560-first-commit', 'commit', *special,
                       '--legacy-6560-index', str(index))
    assert commit_gate.returncode == 0, commit_gate.stderr + commit_gate.stdout
    assert hashlib.sha256(ordinary_index_path.read_bytes()).hexdigest() == original_index_sha256
    subprocess.run(['git', '-C', str(worktree), 'commit', '-m', 'preserve selected patch'],
                   env=isolated_env, check=True, capture_output=True)
    first = _git(worktree, 'rev-parse', 'HEAD')
    verify_first_patch_commit(cwd=worktree, worktree=worktree, parent=parent, commit=first,
        selected=selected, baseline_oids=case['receipt']['dirty_candidate']['index_blobs'])
    assert ordinary_before == {name: _git(worktree, 'rev-parse', f':{name}') for name in names}
    _git(worktree, 'reset', '-q', 'HEAD', '--', *names)
    assert _git(worktree, 'rev-parse', ':file.txt') == unrelated_blob
    assert gate().returncode != 0  # A preserved first commit is not push authority.
    if unrelated_staged:
        assert _git(worktree, 'diff', '--cached', '--name-only') == 'file.txt'
        return  # Preserve unrelated staged work; integration needs its own reconciliation.

    _git(worktree, 'merge', '--no-commit', '--no-ff', 'origin/main')
    integration = ['--integration-merge-target', main_head, '--integration-step']
    for step in ('stage', 'commit'):
        checked = gate(*integration, step)
        assert checked.returncode == 0, checked.stderr + checked.stdout
    _git(worktree, 'commit', '-m', 'integrate main')
    assert gate().returncode == 0
    merged = (worktree / 'tests/properties/_machinery.py').read_text()
    assert 'dirty tests/properties/_machinery.py\n' in merged
    assert 'main change in the selected file\n' in merged
    integrated_head = _git(worktree, 'rev-parse', 'HEAD')
    publication = subprocess.run(
        [sys.executable, str(source / 'scripts/legacy_6560_publication_gate.py'),
         '--worktree', str(worktree), '--agent', case['agent'], '--session', case['session'],
         '--head', integrated_head, '--expected-remote-head', parent, '--effect', 'push'],
        cwd=worktree, env=env, capture_output=True, text=True,
    )
    assert publication.returncode == 0, publication.stderr + publication.stdout


@pytest.mark.parametrize("operator_case", [6560, (6560, 6565, "codex-issue-6560", 11)], indirect=True)
def test_dirty_preflight_refuses_production_fence_and_synthetic_transition(operator_case, tmp_path, monkeypatch, capsys):
    case = operator_case
    _make_dirty_6560(case, tmp_path, monkeypatch)
    history = case["store"].list_events(case["receipt"]["predecessor"]["task_id"])
    if case["pr"] == 6565:
        assert len([event for event in history if event.event_type == "task.claimed"]) == 1
        assert len([event for event in history if event.event_type == "task.heartbeat"]) == 11
        assert history[0].payload["ttl_minutes"] == 90 and "session" not in history[0].payload
        assert case["old_record"]["owner"] == "codex-issue-6560-20261102"
        assert case["receipt"]["predecessor"]["holder"] == "codex-issue-6560"
        assert case["old_record"]["owner"] != case["receipt"]["predecessor"]["holder"]
        update = next(index for index, event in enumerate(history) if event.event_type == "task.updated")
        assert update == 7 and history[update].payload == {"linked_pr": 6565}
        assert case["store"].get_task(history[0].task_id).linked_pr == "6565"
    preflight = recovery.preflight_operator_pickup(**{k: v for k, v in _args(case).items() if k != "run_state_root"})
    assert preflight["candidate"] == case["receipt"]["candidate"]
    # Exercise the real CLI argument/dispatch boundary; only host and GitHub ports
    # are substituted by the fixture, with real Git, SQLite and registry state.
    with monkeypatch.context() as patch:
        patch.chdir(case["cwd"])
        patch.setattr(sys, "argv", ["legacy_owner_recovery", "pickup", "--issue", "6560", "--pr", str(case["pr"]),
            "--worktree", str(case["worktree"]), "--agent", case["agent"], "--session", case["session"],
            "--comment-id", str(case["comment_id"]), "--workspace-root", str(case["workspace_root"]),
            "--legacy-run-state-root", str(case["run_state_root"])])
        assert recovery._main() == 0
    result = json.loads(capsys.readouterr().out.splitlines()[0])
    assert result["state"] == "pinned"
    ack = json.loads(case["comments"][2]["body"])["operator_reconciliation.v1"]
    assert "successor_acknowledgment" in ack and "predecessor_acknowledgment" not in ack
    assert ack["dirty_candidate"] == case["receipt"]["dirty_candidate"]
    # Exercise the actual publication-lineage consumer against a real first patch commit.
    from app.builderops import openhands_pr_cycle as cycle
    names = list(case["receipt"]["dirty_candidate"]["index_blobs"])
    (case["worktree"] / "file.txt").write_text("unrelated staging survives\n")
    _git(case["worktree"], "add", "file.txt")
    unrelated_blob = _git(case["worktree"], "rev-parse", ":file.txt")
    isolated_env = {**os.environ, "GIT_INDEX_FILE": str(tmp_path / "selected.index")}
    for args in (("read-tree", "HEAD"), ("add", "--", *names), ("commit", "-m", "preserve selected patch")):
        subprocess.check_call(["git", "-C", str(case["worktree"]), *args], env=isolated_env,
                              stdout=subprocess.DEVNULL)
    # Reconcile only the selected entries in the ordinary index after the
    # isolated-index commit; its unrelated staged blob remains byte-identical.
    _git(case["worktree"], "reset", "-q", "HEAD", "--", *names)
    head = _git(case["worktree"], "rev-parse", "HEAD")
    assert _git(case["worktree"], "rev-parse", ":file.txt") == unrelated_blob
    records = agent_worktree._locked_lifecycle_snapshot(agent_worktree._default_registry_path(case["cwd"]))
    row = records[str(case["worktree"])]
    task_id = result["task_id"]
    lineage_args = dict(events=[event.to_dict() for event in case["store"].list_events(task_id)],
        owner={"task_id": task_id, "lease_id": result["lease_id"], "lease_holder": case["agent"]},
        origin={"mode": "dispatcher-backed", "lease_id": result["lease_id"], "agent": case["agent"],
                "path": str(case["worktree"])}, registration=row, records=records,
        comments=list(case["comments"].values()), issue_comments=[], issue=6560, pr_number=case["pr"],
        branch=case["receipt"]["branch"], head=head, files=sorted(["file.txt", *names]),
        entry={"claimant": case["agent"], "session": case["session"], "lease_id": result["lease_id"],
               "base_sha": case["receipt"]["base"], "lifecycle_repo": str(case["cwd"])})
    cycle._operator_lineage(**lineage_args)
    assert _git(case["worktree"], "diff", "--cached", "--name-only") == "file.txt"
    from scripts import legacy_6560_publication_gate as publication_gate
    monkeypatch.setattr(cycle.closure, "_closing_issue_references", lambda *_args: [6560])
    gate_args = {"cwd": case["cwd"], "worktree": case["worktree"], "session": case["session"],
                 "agent": case["agent"], "head": head,
                 "expected_remote_head": case["receipt"]["publication"]["head"], "effect": "push"}
    effects = []
    def fake_effect_after_proof(**kwargs):
        publication_gate.check(**kwargs)
        effects.append("normal-control-reached")
    fake_effect_after_proof(**gate_args)
    assert effects == ["normal-control-reached"]
    effects.clear()
    with monkeypatch.context() as patch:
        patch.chdir(case["cwd"])
        patch.setattr(sys, "argv", ["legacy_6560_publication_gate", "--worktree", str(case["worktree"]),
            "--agent", case["agent"], "--session", case["session"], "--effect", "push", "--head", head,
            "--expected-remote-head", case["receipt"]["publication"]["head"]])
        assert publication_gate.main() == 0
    cli_proof = json.loads(capsys.readouterr().out)
    assert cli_proof["head"] == head and cli_proof["attempt_source"] == "operator must establish separately"
    with monkeypatch.context() as patch:
        patch.setenv("CODEX_SESSION_ID", "another-session")
        with pytest.raises(publication_gate.PublicationProofError):
            fake_effect_after_proof(**gate_args)
        assert effects == []
    with monkeypatch.context() as patch:
        original_claim = recovery._successor_claim_readback
        calls = []
        original_row = copy.deepcopy(row)
        def release_registry_after_final_claim(**kwargs):
            observed = original_claim(**kwargs)
            calls.append(True)
            if len(calls) == 2:
                agent_worktree.release_worktree(case["cwd"], worktree=case["worktree"], owner=case["session"])
            return observed
        patch.setattr(recovery, "_successor_claim_readback", release_registry_after_final_claim)
        try:
            with pytest.raises(publication_gate.PublicationProofError):
                fake_effect_after_proof(**gate_args)
            assert len(calls) == 2 and effects == []
        finally:
            # Restore only this disposable fixture so subsequent independent cases can run.
            registry = agent_worktree._default_registry_path(case["cwd"])
            with agent_worktree._locked_registry(registry) as payload:
                payload["worktrees"][str(case["worktree"])] = original_row
    with monkeypatch.context() as patch:
        original_live = recovery.read_live_publication
        def expire_during_pr_read(**kwargs):
            observed = original_live(**kwargs)
            patch.setattr(publication_gate.time, "time", lambda: row["expires_at"] + 1)
            return observed
        patch.setattr(recovery, "read_live_publication", expire_during_pr_read)
        with pytest.raises(publication_gate.PublicationProofError):
            fake_effect_after_proof(**gate_args)
        assert effects == []
    with monkeypatch.context() as patch:
        original_live = recovery.read_live_publication
        lease_id = result["lease_id"]
        with case["store"]._connect() as connection:
            lease_expiry = connection.execute("SELECT expires_at FROM dispatcher_leases WHERE lease_id = ?", (lease_id,)).fetchone()[0]
            task_expiry = connection.execute("SELECT lease_expires_at FROM dispatcher_tasks WHERE task_id = ?", (task_id,)).fetchone()[0]
        def expire_lease_during_pr_read(**kwargs):
            observed = original_live(**kwargs)
            with case["store"]._connect() as connection:
                expired = (datetime.now(timezone.utc) - timedelta(seconds=1)).isoformat()
                connection.execute("UPDATE dispatcher_leases SET expires_at = ? WHERE lease_id = ?", (expired, lease_id))
                connection.execute("UPDATE dispatcher_tasks SET lease_expires_at = ? WHERE task_id = ?", (expired, task_id))
                connection.commit()
            return observed
        patch.setattr(recovery, "read_live_publication", expire_lease_during_pr_read)
        try:
            with pytest.raises(publication_gate.PublicationProofError):
                fake_effect_after_proof(**gate_args)
            assert effects == []
        finally:
            with case["store"]._connect() as connection:
                connection.execute("UPDATE dispatcher_leases SET expires_at = ? WHERE lease_id = ?", (lease_expiry, lease_id))
                connection.execute("UPDATE dispatcher_tasks SET lease_expires_at = ? WHERE task_id = ?", (task_expiry, task_id))
                connection.commit()
    for location in (6560, case["pr"]):
        with monkeypatch.context() as patch:
            other = copy.deepcopy(case["comments"][2])
            other["id"] = 9999
            other["issue_url"] = f"https://api.github.com/repos/RasmusTho/agentic-pkm-mvp/issues/{location}"
            patch.setattr(recovery, "_operator_comments", lambda **_kwargs: [*case["comments"].values(), other])
            with pytest.raises(publication_gate.PublicationProofError):
                fake_effect_after_proof(**gate_args)
            assert effects == []
    with monkeypatch.context() as patch:
        def stale_claim(**_kwargs):
            raise recovery.RecoveryEvidenceError("stale claim")
        patch.setattr(recovery, "_successor_claim_readback", stale_claim)
        with pytest.raises(publication_gate.PublicationProofError):
            fake_effect_after_proof(**gate_args)
        assert effects == []
    with monkeypatch.context() as patch:
        patch.setattr(cycle.closure, "_closing_issue_references", lambda *_args: [9999])
        with pytest.raises(publication_gate.PublicationProofError):
            fake_effect_after_proof(**gate_args)
        assert effects == []
    with monkeypatch.context() as patch:
        references = []
        def changed_references(*_args):
            references.append(True)
            return [6560] if len(references) == 1 else [9999]
        patch.setattr(cycle.closure, "_closing_issue_references", changed_references)
        with pytest.raises(publication_gate.PublicationProofError):
            fake_effect_after_proof(**gate_args)
        assert effects == []
    with monkeypatch.context() as patch:
        def stale_pin(_record):
            raise agent_worktree.WorktreeLifecycleError("stale pin")
        patch.setattr(agent_worktree, "assert_operator_registration_pinned", stale_pin)
        with pytest.raises(publication_gate.PublicationProofError):
            fake_effect_after_proof(**gate_args)
        assert effects == []
    for drift in ("state", "draft", "head", "ref", "base"):
        with monkeypatch.context() as patch:
            original_patch = cycle._verify_dirty_first_patch
            original_pr = copy.deepcopy(case["pr_data"])
            def change_pr_during_patch(**kwargs):
                original_patch(**kwargs)
                if drift == "state":
                    case["pr_data"]["state"] = "closed"
                elif drift == "draft":
                    case["pr_data"]["draft"] = True
                elif drift == "head":
                    case["pr_data"]["head"]["sha"] = "a" * 40
                elif drift == "ref":
                    case["pr_data"]["head"]["ref"] = "foreign-branch"
                else:
                    case["pr_data"]["base"]["sha"] = "b" * 40
            patch.setattr(cycle, "_verify_dirty_first_patch", change_pr_during_patch)
            try:
                with pytest.raises(publication_gate.PublicationProofError):
                    fake_effect_after_proof(**gate_args)
                assert effects == []
            finally:
                case["pr_data"].clear()
                case["pr_data"].update(original_pr)
    # A verified H0->H1 push can update the body, and its successor body then
    # permits the already-published H1 to be the base for an H2 repair.
    with monkeypatch.context() as patch:
        original_comment_read = agent_worktree._read_github_transfer_comment
        intent_reads = []
        def comment_with_changing_avatar(comment_id, **kwargs):
            value = copy.deepcopy(original_comment_read(comment_id, **kwargs))
            if comment_id in {3, 4}:
                intent_reads.append(comment_id)
                value['user']['avatar_url'] = f'https://example.invalid/avatar?v={len(intent_reads)}'
            return value
        patch.setattr(agent_worktree, '_read_github_transfer_comment', comment_with_changing_avatar)
        original_live = recovery.read_live_publication
        old_live = original_live(cwd=case["cwd"], pr=case["pr"], branch=case["receipt"]["branch"])
        h1_live = {**old_live, "head": head}
        current_pr = {**case["pr_data"], "head": {**case["pr_data"]["head"], "sha": head}}
        original_github = recovery._github_read
        def github(args, *, cwd):
            if args == [f"repos/RasmusTho/agentic-pkm-mvp/pulls/{case['pr']}"]:
                return json.dumps(current_pr)
            return original_github(args, cwd=cwd)
        patch.setattr(recovery, "_github_read", github)
        patch.setattr(recovery, "read_live_publication", lambda **_kwargs: dict(h1_live))
        with pytest.raises(publication_gate.PublicationProofError):
            fake_effect_after_proof(**{**gate_args, "expected_remote_head": head})
        with pytest.raises(publication_gate.PublicationProofError):
            fake_effect_after_proof(**{**gate_args, "effect": "patch", "expected_remote_head": head,
                                      "just_pushed_from": old_live["head"]})
        assert effects == []
        successor_body = case["pr_data"]["body"].replace(
            f"lease_id={case['old_lease'].lease_id} holder={case['receipt']['predecessor']['holder']}",
            f"lease_id={result['lease_id']} holder={case['agent']}")
        successor_body += "\n<!-- operator-publication-attempt:" + "1" * 32 + " -->\n"
        intended_body_file = tmp_path / "reviewed-pr-body.txt"
        intended_body_file.write_text(successor_body)
        # The existing authenticated comment binds the exact reviewed body before PATCH.
        time.sleep(2.1)
        expected_body = hashlib.sha256(successor_body.encode()).hexdigest()
        intent = {"issue": 6560, "pr": case["pr"], "repository": "RasmusTho/agentic-pkm-mvp",
                  "branch": case["receipt"]["branch"], "session": case["session"], "agent": case["agent"],
                  "lease_id": result["lease_id"], "head": head, "before_body_sha256": old_live["body_sha256"],
                  "body_sha256": expected_body, "body": successor_body, "attempt_id": "1" * 32, "reviewed": True}
        comment = _comment(case["receipt"], 3, time.time())
        comment["body"] = json.dumps({"operator_publication_intent.v1": intent}, sort_keys=True)
        case["comments"][3] = comment
        first_patch_args = {**gate_args, "effect": "patch", "expected_remote_head": head,
                            "just_pushed_from": old_live["head"], "next_body_file": intended_body_file,
                            "next_intent_comment_id": 3}
        fake_effect_after_proof(**first_patch_args)
        assert effects == ["normal-control-reached"]
        effects.clear()
        # Both GitHub representations may agree at each read and still drift
        # between the first and the late authority checkpoint.
        original_intent_read = publication_gate._body_intent
        for changed_field in ('user_id', 'body'):
            previous_comment = copy.deepcopy(case['comments'][3])
            calls = []
            def change_before_late_intent(*args, **kwargs):
                calls.append(True)
                if len(calls) == 2:
                    if changed_field == 'user_id':
                        case['comments'][3]['user']['id'] += 1
                    else:
                        case['comments'][3]['body'] += ' '
                return original_intent_read(*args, **kwargs)
            patch.setattr(publication_gate, '_body_intent', change_before_late_intent)
            try:
                with pytest.raises(publication_gate.PublicationProofError):
                    fake_effect_after_proof(**first_patch_args)
                assert len(calls) == 2 and effects == []
            finally:
                case['comments'][3] = previous_comment
                patch.setattr(publication_gate, '_body_intent', original_intent_read)
        current_pr["body"] = successor_body
        current_pr["updated_at"] = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
        h1_live["body_sha256"] = expected_body
        _git(case["worktree"], "commit", "-m", "review repair")
        h2 = _git(case["worktree"], "rev-parse", "HEAD")
        h2_args = {**gate_args, "head": h2, "expected_remote_head": head,
                   "prior_body_file": intended_body_file, "prior_intent_comment_id": 3}
        # A lost body-update response without the earlier intended body identity remains unknown.
        with pytest.raises(publication_gate.PublicationProofError):
            fake_effect_after_proof(**{**gate_args, "head": h2, "expected_remote_head": head})
        assert effects == []
        with pytest.raises(publication_gate.PublicationProofError):
            fake_effect_after_proof(**{**gate_args, "head": h2, "expected_remote_head": head,
                                       "prior_body_file": intended_body_file})
        assert effects == []
        late_body_file = tmp_path / "body-derived-after-unknown-response.txt"
        late_body_file.write_text(successor_body)
        # A later unrelated PR update must not make an after-the-fact file valid.
        time.sleep(1.1)
        current_pr["updated_at"] = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
        with pytest.raises(publication_gate.PublicationProofError):
            fake_effect_after_proof(**{**h2_args, "prior_body_file": late_body_file})
        assert effects == []
        fake_effect_after_proof(**h2_args)
        assert effects == ["normal-control-reached"]
        effects.clear()
        # A later PATCH must bind a *new* intent as well as the existing one.
        with pytest.raises(publication_gate.PublicationProofError):
            fake_effect_after_proof(**{**h2_args, "effect": "patch", "head": head})
        assert effects == []
        # Simulate exact H2 push/readback, then bind the second PATCH to a new
        # comment and different body; the prior H1 intent is still required.
        h1_live["head"] = h2
        current_pr["head"]["sha"] = h2
        second_body = successor_body.replace('1' * 32, '2' * 32) + '\nValidation updated for H2.\n'
        second_file = tmp_path / 'reviewed-pr-body-h2.txt'
        second_file.write_text(second_body)
        time.sleep(2.1)
        second = {**intent, 'head': h2, 'before_body_sha256': expected_body,
                  'body_sha256': hashlib.sha256(second_body.encode()).hexdigest(),
                  'body': second_body, 'attempt_id': '2' * 32}
        second_comment = _comment(case['receipt'], 4, time.time())
        second_comment['body'] = json.dumps({'operator_publication_intent.v1': second}, sort_keys=True)
        case['comments'][4] = second_comment
        second_patch = {**h2_args, 'effect': 'patch', 'expected_remote_head': h2,
                        'next_body_file': second_file, 'next_intent_comment_id': 4}
        fake_effect_after_proof(**second_patch)
        assert effects == ['normal-control-reached']
        effects.clear()
        with pytest.raises(publication_gate.PublicationProofError):
            fake_effect_after_proof(**{**second_patch, 'prior_intent_comment_id': None})
        assert effects == []
        second_comment['body'] = json.dumps({'operator_publication_intent.v1': {**second, 'head': head}}, sort_keys=True)
        with pytest.raises(publication_gate.PublicationProofError):
            fake_effect_after_proof(**second_patch)
        assert effects == []
        second_comment['body'] = json.dumps({'operator_publication_intent.v1': second}, sort_keys=True)
        # Model an accepted PATCH with a lost response. Live bytes can match
        # the earlier intent; the real operator still needs the attempt source.
        current_pr['body'] = second_body
        h1_live['body_sha256'] = second['body_sha256']
        readback = publication_gate.check(**{**gate_args, 'effect': 'verify', 'head': h2, 'expected_remote_head': h2,
            'prior_body_file': second_file, 'prior_intent_comment_id': 4})
        assert readback['attempt_source'] == 'operator must establish separately'
        assert intent_reads.count(3) >= 2 and intent_reads.count(4) >= 2
        current_pr['body'] = successor_body
        current_pr['head']['sha'] = head
        h1_live['body_sha256'] = expected_body
        h1_live['head'] = head
        current_pr["body"] = successor_body + "\nChanged review scope without changing pickup or issue.\n"
        h1_live["body_sha256"] = hashlib.sha256(current_pr["body"].encode()).hexdigest()
        with pytest.raises(publication_gate.PublicationProofError):
            fake_effect_after_proof(**h2_args)
        assert effects == []
        current_pr["body"] = successor_body.replace(result["lease_id"], "foreign-lease")
        h1_live["body_sha256"] = hashlib.sha256(current_pr["body"].encode()).hexdigest()
        with pytest.raises(publication_gate.PublicationProofError):
            fake_effect_after_proof(**h2_args)
        assert effects == []
        current_pr["body"] = successor_body
        h1_live["body_sha256"] = expected_body
        h1_live["head"] = "a" * 40
        with pytest.raises(publication_gate.PublicationProofError):
            fake_effect_after_proof(**{**h2_args, "expected_remote_head": "a" * 40})
        assert effects == []
        _git(case["worktree"], "reset", "--soft", head)
    # Synthetically rewrite only this test checkout to exercise the gate on an
    # actual first commit that accidentally includes the unrelated staged path.
    _git(case["worktree"], "reset", "--soft", case["receipt"]["candidate"]["head"])
    _git(case["worktree"], "commit", "-m", "invalid mixed patch")
    bad_head = _git(case["worktree"], "rev-parse", "HEAD")
    _git(case["worktree"], "replace", bad_head, head)
    with pytest.raises(publication_gate.PublicationProofError):
        fake_effect_after_proof(**{**gate_args, "head": bad_head})
    assert effects == []
    _git(case["worktree"], "replace", "-d", bad_head)
    # Restore the synthetic checkout only so the following poisoning test keeps
    # its original candidate/HEAD relationship.
    _git(case["worktree"], "reset", "--soft", head)
    # A release in the same dispatcher database during a slow patch read must
    # be noticed by the final exact-claim readback.
    with monkeypatch.context() as patch:
        original_patch_read = cycle._verify_dirty_first_patch
        def release_during_patch(**kwargs):
            original_patch_read(**kwargs)
            leases.release(case["store"], result["task_id"], case["agent"], expected_lease_id=result["lease_id"])
        patch.setattr(cycle, "_verify_dirty_first_patch", release_during_patch)
        with pytest.raises(publication_gate.PublicationProofError):
            fake_effect_after_proof(**gate_args)
        assert effects == []
    # The unqualified source must never run Git to follow a local include.
    poison = tmp_path / "ignored-sensitive-config"
    poison.write_text("[core]\n  fsmonitor = /not-a-real-command\n")
    config = tmp_path / "agentic-pkm-mvp/.git/config"
    config.write_text(config.read_text() + f"\n[include]\n  path = {poison}\n")
    def source_git_forbidden(*_args, **_kwargs):
        pytest.fail("dirty lineage used source Git before rejecting the include")
    monkeypatch.setattr(agent_worktree, "_worktree_identity", source_git_forbidden)
    monkeypatch.setattr(cycle.legacy_owner_recovery, "_git_read", source_git_forbidden)
    with pytest.raises(cycle.CycleError, match="candidate readback is unavailable") as refused:
        cycle._operator_lineage(**lineage_args)
    assert "Git configuration is unsupported" in str(refused.value.__cause__)


@pytest.mark.parametrize("operator_case", [6560], indirect=True)
@pytest.mark.parametrize("drift", ["backup", "publication", "unknown"])
def test_dirty_preflight_refuses_drift_or_unknown_before_claim(operator_case, tmp_path, monkeypatch, drift):
    case = operator_case
    backup = _make_dirty_6560(case, tmp_path, monkeypatch)
    if drift == "backup":
        backup.write_bytes(b"changed")
    elif drift == "publication":
        case["pr_data"]["head"]["sha"] = "a" * 40
    else:
        case["receipt"]["writer"]["restart"] = "unknown"
        case["comments"][1] = _comment(case["receipt"], 1, time.time() - 5)
    with pytest.raises(recovery.RecoveryEvidenceError):
        recovery.preflight_operator_pickup(**{k: v for k, v in _args(case).items() if k != "run_state_root"})
    assert case["store"].get_task(case["receipt"]["predecessor"]["task_id"]).lease_id == case["old_lease"].lease_id
    assert 2 not in case["comments"]


@pytest.mark.parametrize('operator_case', [6560], indirect=True)
@pytest.mark.parametrize('drift', ['process', 'cwd', 'launchctl', 'crontab', 'boot', 'delegate', 'postboot',
                                  'manual', 'historical_push', 'historical_body', 'command_prefix'])
def test_codex_guard_refuses_specific_drift_before_claim(operator_case, tmp_path, monkeypatch, drift):
    from app.builderops import legacy_codex_6560_guard as guard
    case = operator_case
    _make_dirty_6560(case, tmp_path, monkeypatch)
    boot = int(datetime.fromisoformat(case['receipt']['writer']['boot']).timestamp())
    processes, launchctl, crontab = '', '', ''
    if drift == 'process':
        processes = f'12345 1 codex {guard.CHILD}'
    elif drift == 'cwd':
        processes = '12345 1 codex worker'
        monkeypatch.setattr(guard, '_run', lambda *args, **kwargs: 'p12345\nn' + guard.WORKTREE + '\n')
    elif drift == 'launchctl':
        launchctl = f'program = {guard.WORKTREE}'
    elif drift == 'crontab':
        crontab = f'* * * * * {guard.WORKTREE}'
    elif drift == 'boot':
        boot += 1
    elif drift == 'delegate':
        case['receipt']['codex_custody']['delegates'][next(iter(guard.DELEGATES))] = 'unknown'
    elif drift == 'postboot':
        case['receipt']['codex_custody']['postboot_identified_activity_reconciled'] = False
    elif drift == 'historical_push':
        case['receipt']['codex_custody']['historical_push_outputs'] = 'matched'
    elif drift == 'historical_body':
        case['receipt']['codex_custody']['historical_edited_bodies'] = 'matched'
    elif drift == 'command_prefix':
        case['receipt']['codex_custody']['publication_commands'][0] = guard.PUBLICATION_COMMANDS[0][:13]
    else:
        case['receipt']['codex_custody']['no_new_manual_starts'] = False
    case['comments'][1] = _comment(case['receipt'], 1, time.time() - 5)
    monkeypatch.setattr(guard, '_host_readback', lambda: (boot, processes, launchctl, crontab))
    with pytest.raises(recovery.RecoveryEvidenceError):
        recovery.execute_operator_pickup(**_args(case))
    assert case['store'].get_task(case['receipt']['predecessor']['task_id']).lease_id == case['old_lease'].lease_id
    assert 2 not in case['comments']


@pytest.mark.parametrize('operator_case', [6560], indirect=True)
def test_codex_guard_rechecks_before_pin_and_retains_claim(operator_case, tmp_path, monkeypatch):
    from app.builderops import legacy_codex_6560_guard as guard
    case = operator_case
    _make_dirty_6560(case, tmp_path, monkeypatch)
    boot = int(datetime.fromisoformat(case['receipt']['writer']['boot']).timestamp())
    original_run = recovery.subprocess.run
    def run(args, **kwargs):
        result = original_run(args, **kwargs)
        if args[0] == 'gh' and 'POST' in args:
            monkeypatch.setattr(guard, '_host_readback', lambda: (boot, f'12345 1 codex {guard.CHILD}', '', ''))
        return result
    monkeypatch.setattr(recovery.subprocess, 'run', run)
    with pytest.raises(recovery.RecoveryEvidenceError, match='retain claim'):
        recovery.execute_operator_pickup(**_args(case))
    row = agent_worktree._locked_lifecycle_snapshot(agent_worktree._default_registry_path(case['cwd']))[str(case['worktree'])]
    assert row['operator_registration']['state'] == 'prepared'
    assert case['store'].get_task(case['receipt']['predecessor']['task_id']).lease_id != case['old_lease'].lease_id


@pytest.mark.parametrize('operator_case', [6560], indirect=True)
def test_codex_guard_detects_postclaim_drift_before_ack(operator_case, tmp_path, monkeypatch):
    from app.builderops import legacy_codex_6560_guard as guard
    case = operator_case
    _make_dirty_6560(case, tmp_path, monkeypatch)
    boot = int(datetime.fromisoformat(case['receipt']['writer']['boot']).timestamp())
    original_post = recovery._post_and_pin_operator_ack
    def post(**kwargs):
        monkeypatch.setattr(guard, '_host_readback', lambda: (boot, f'12345 1 codex {guard.CHILD}', '', ''))
        return original_post(**kwargs)
    monkeypatch.setattr(recovery, '_post_and_pin_operator_ack', post)
    with pytest.raises(recovery.RecoveryEvidenceError, match='retain claim'):
        recovery.execute_operator_pickup(**_args(case))
    row = agent_worktree._locked_lifecycle_snapshot(agent_worktree._default_registry_path(case['cwd']))[str(case['worktree'])]
    assert row['operator_registration']['state'] == 'prepared'
    assert 'ack_intent' not in row['operator_registration']
    assert case['store'].get_task(case['receipt']['predecessor']['task_id']).lease_id != case['old_lease'].lease_id
    assert 2 not in case['comments']


@pytest.mark.parametrize('operator_case', [6560], indirect=True)
def test_codex_guard_detects_drift_after_intent_before_post(operator_case, tmp_path, monkeypatch):
    from app.builderops import legacy_codex_6560_guard as guard
    case = operator_case
    _make_dirty_6560(case, tmp_path, monkeypatch)
    boot = int(datetime.fromisoformat(case['receipt']['writer']['boot']).timestamp())
    original_intent = agent_worktree.begin_operator_ack
    def intent(*args, **kwargs):
        result = original_intent(*args, **kwargs)
        monkeypatch.setattr(guard, '_host_readback', lambda: (boot, f'12345 1 codex {guard.CHILD}', '', ''))
        return result
    monkeypatch.setattr(agent_worktree, 'begin_operator_ack', intent)
    with pytest.raises(recovery.RecoveryEvidenceError, match='retain claim'):
        recovery.execute_operator_pickup(**_args(case))
    row = agent_worktree._locked_lifecycle_snapshot(agent_worktree._default_registry_path(case['cwd']))[str(case['worktree'])]
    assert row['operator_registration']['state'] == 'prepared'
    assert row['operator_registration']['ack_intent']
    assert 2 not in case['comments']


@pytest.mark.parametrize('operator_case', [6560], indirect=True)
@pytest.mark.parametrize('boundary', ['prepare', 'ack_post', 'pin'])
@pytest.mark.parametrize('drift', ['release', 'issue'])
def test_6560_effect_rechecks_claim_after_slow_read(operator_case, tmp_path, monkeypatch, boundary, drift):
    from app.builderops import legacy_codex_6560_guard as guard
    case = operator_case
    _make_dirty_6560(case, tmp_path, monkeypatch)
    task_id = case['receipt']['predecessor']['task_id']
    boot = int(datetime.fromisoformat(case['receipt']['writer']['boot']).timestamp())
    released = []
    def release_once():
        if not released:
            lease_id = case['store'].get_task(task_id).lease_id
            if lease_id != case['old_lease'].lease_id:
                if drift == 'release':
                    leases.release(case['store'], task_id, case['agent'], expected_lease_id=lease_id)
                else:
                    case['issue_data']['state'] = 'closed'
                released.append(True)
    if boundary == 'prepare':
        def host():
            release_once()
            return boot, '', '', ''
        monkeypatch.setattr(guard, '_host_readback', host)
    elif boundary == 'ack_post':
        original_intent = agent_worktree.begin_operator_ack
        original_comments = recovery._operator_comments
        intent_set = []
        def intent(*args, **kwargs):
            result = original_intent(*args, **kwargs)
            intent_set.append(True)
            return result
        def comments(**kwargs):
            result = original_comments(**kwargs)
            if intent_set:
                release_once()
            return result
        monkeypatch.setattr(agent_worktree, 'begin_operator_ack', intent)
        monkeypatch.setattr(recovery, '_operator_comments', comments)
    else:
        original_ack = recovery._read_unique_operator_ack
        reads = []
        def ack(**kwargs):
            result = original_ack(**kwargs)
            reads.append(True)
            if len(reads) == 2:
                release_once()
            return result
        monkeypatch.setattr(recovery, '_read_unique_operator_ack', ack)
    with pytest.raises(recovery.RecoveryEvidenceError):
        recovery.execute_operator_pickup(**_args(case))
    assert released
    row = agent_worktree._locked_lifecycle_snapshot(agent_worktree._default_registry_path(case['cwd']))[str(case['worktree'])]
    if boundary == 'prepare':
        assert 'operator_registration' not in row
    else:
        assert row['operator_registration']['state'] == 'prepared'
        assert bool(row['operator_registration'].get('ack_intent'))
    assert (2 in case['comments']) is (boundary == 'pin')


@pytest.mark.parametrize('operator_case', [6560], indirect=True)
def test_6560_registry_expiry_after_intent_refuses_ack_post(operator_case, tmp_path, monkeypatch):
    case = operator_case
    _make_dirty_6560(case, tmp_path, monkeypatch)
    original_intent = agent_worktree.begin_operator_ack
    def intent(*args, **kwargs):
        result = original_intent(*args, **kwargs)
        registry = agent_worktree._default_registry_path(case['cwd'])
        with agent_worktree._locked_registry(registry) as payload:
            payload['worktrees'][str(case['worktree'])]['expires_at'] = time.time() - 0.001
        return result
    monkeypatch.setattr(agent_worktree, 'begin_operator_ack', intent)
    with pytest.raises(recovery.RecoveryEvidenceError):
        recovery.execute_operator_pickup(**_args(case))
    row = agent_worktree._locked_lifecycle_snapshot(agent_worktree._default_registry_path(case['cwd']))[str(case['worktree'])]
    assert row['operator_registration']['state'] == 'prepared'
    assert row['operator_registration']['ack_intent']
    assert case['store'].get_task(case['receipt']['predecessor']['task_id']).lease_id != case['old_lease'].lease_id
    assert 2 not in case['comments']


@pytest.mark.parametrize('operator_case', [6560], indirect=True)
@pytest.mark.parametrize('boundary', ['post', 'pin'])
def test_6560_late_competing_ack_refused_at_effect_boundary(operator_case, tmp_path, monkeypatch, boundary):
    case = operator_case
    _make_dirty_6560(case, tmp_path, monkeypatch)
    original_intent = agent_worktree.begin_operator_ack
    original_claim = recovery._successor_claim_readback
    intent_set, injected = [], []
    def intent(*args, **kwargs):
        value = original_intent(*args, **kwargs)
        intent_set.append(True)
        return value
    def claim(**kwargs):
        value = original_claim(**kwargs)
        if not injected and ((boundary == 'post' and intent_set) or (boundary == 'pin' and 2 in case['comments'])):
            if boundary == 'post':
                extra = {**copy.deepcopy(case['receipt']), 'successor_acknowledgment': {'ambiguous': True}}
                case['comments'][3] = _comment(extra, 3, time.time())
            else:
                case['comments'][3] = copy.deepcopy(case['comments'][2])
                case['comments'][3]['id'] = 3
            injected.append(True)
        return value
    monkeypatch.setattr(agent_worktree, 'begin_operator_ack', intent)
    monkeypatch.setattr(recovery, '_successor_claim_readback', claim)
    with pytest.raises(recovery.RecoveryEvidenceError):
        recovery.execute_operator_pickup(**_args(case))
    assert injected
    row = agent_worktree._locked_lifecycle_snapshot(agent_worktree._default_registry_path(case['cwd']))[str(case['worktree'])]
    assert row['operator_registration']['state'] == 'prepared'
    assert row['operator_registration']['ack_intent']
    assert (2 in case['comments']) is (boundary == 'pin')


@pytest.mark.parametrize('operator_case', [6560], indirect=True)
def test_6560_late_ack_during_intent_read_prevents_intent(operator_case, tmp_path, monkeypatch):
    case = operator_case
    _make_dirty_6560(case, tmp_path, monkeypatch)
    original_intent = agent_worktree.begin_operator_ack
    original_claim = recovery._successor_claim_readback
    injected = []
    def intent(*args, **kwargs):
        original_before_write = kwargs['before_write']
        def before_write(payload):
            def claim(**claim_kwargs):
                value = original_claim(**claim_kwargs)
                if not injected:
                    extra = {**copy.deepcopy(case['receipt']), 'successor_acknowledgment': {'ambiguous': True}}
                    case['comments'][3] = _comment(extra, 3, time.time())
                    injected.append(True)
                return value
            with monkeypatch.context() as patch:
                patch.setattr(recovery, '_successor_claim_readback', claim)
                original_before_write(payload)
        kwargs['before_write'] = before_write
        return original_intent(*args, **kwargs)
    monkeypatch.setattr(agent_worktree, 'begin_operator_ack', intent)
    with pytest.raises(recovery.RecoveryEvidenceError):
        recovery.execute_operator_pickup(**_args(case))
    assert injected
    row = agent_worktree._locked_lifecycle_snapshot(agent_worktree._default_registry_path(case['cwd']))[str(case['worktree'])]
    assert row['operator_registration']['state'] == 'prepared'
    assert 'ack_intent' not in row['operator_registration'] and 2 not in case['comments']


def _bind_6561_sources(case, source_bound, monkeypatch):
    from app.builderops import legacy_codex_6561_guard as guard
    monkeypatch.setattr(guard, "WORKTREE", str(case["worktree"]))
    monkeypatch.setattr(guard, "BRANCH", "codex/example")
    monkeypatch.setattr(guard, "GENERATION", case["receipt"]["candidate"]["generation"])
    monkeypatch.setattr(guard, "OWNER", case["old_record"]["owner"])
    monkeypatch.setattr(guard, "HOLDER", case["receipt"]["predecessor"]["holder"])
    monkeypatch.setattr(guard, "LEASE", case["old_lease"].lease_id)
    monkeypatch.setattr(guard, "HEAD", case["pr_data"]["head"]["sha"])
    monkeypatch.setattr(guard, "BODY", case["receipt"]["publication"]["body_sha256"])
    for row in source_bound["child"]:
        item = row["payload"].get("item", {})
        if item.get("id") in guard.PUBLICATION_COMMANDS:
            item["aggregated_output"] = json.dumps({"pr": 6562, "head": guard.HEAD,
                "body_sha256": guard.BODY, "state": "open"}) + "\ncomment link"
    source_bound["child_path"].write_bytes(sources_6561._jsonl(source_bound["child"]))
    evidence = copy.deepcopy(source_bound["receipt"]["writer"]["codex_custody"])
    evidence["child_sha256"] = hashlib.sha256(source_bound["child_path"].read_bytes()).hexdigest()
    case["receipt"]["writer"].update({"boot": "2026-11-14T21:48:30Z",
        "last_activity": "2026-11-15T08:03:36.536Z", "codex_custody": evidence})
    case["comments"][1] = _comment(case["receipt"], 1, time.time() - 5)
    monkeypatch.setattr(agent_worktree, "_read_github_transfer_comment", lambda ident, *, cwd: case["comments"][ident])
    def github(args, *, cwd):
        if args and "/issues/comments/" in args[0]:
            return json.dumps({"id": int(args[0].rsplit("/", 1)[1]), "user": {"login": "RasmusTho"},
                "issue_url": "https://api.github.com/repos/RasmusTho/agentic-pkm-mvp/issues/6561"})
        return case["github_read"](args, cwd=cwd)
    monkeypatch.setattr(recovery, "_github_read", github)
    return guard


@pytest.mark.parametrize("operator_case", [(6561, 6562, "codex-issue6561-normal-transport", 9)], indirect=True)
@pytest.mark.parametrize("projection", [None, "6562"])
def test_6561_real_pickup_and_lost_ack_resume_with_synthetic_sources(operator_case, codex_6561_source, monkeypatch, projection):
    case = operator_case
    if projection is None:
        task_id = case["receipt"]["predecessor"]["task_id"]
        with case["store"]._connect() as conn:
            conn.execute("UPDATE dispatcher_tasks SET linked_pr=NULL WHERE task_id=?", (task_id,))
            conn.execute("DELETE FROM dispatcher_events WHERE event_id=?", ("fixture-linked-pr",))
        case["receipt"]["predecessor"] = recovery.read_live_predecessor(cwd=case["cwd"], issue=case["issue"])
    source_bound = codex_6561_source
    guard = _bind_6561_sources(case, source_bound, monkeypatch)
    from scripts import legacy_operator_evidence
    draft = legacy_operator_evidence.build_draft(cwd=case["cwd"], issue=6561, pr=6562,
        worktree=case["worktree"], base=case["receipt"]["base"], agent=case["agent"],
        session=case["session"])["operator_reconciliation.v1"]
    assert draft["writer"]["codex_custody"]["observed_at"] is None
    assert draft["writer"]["codex_custody"]["unrecorded_effects"] == "unknown"
    original = guard.check
    checks = []
    def check(**kwargs):
        result = original(**kwargs)
        checks.append(result)
        return result
    monkeypatch.setattr(guard, "check", check)
    run = recovery.subprocess.run
    posts = []
    def lost_ack(args, **kwargs):
        if args[0] == "gh" and "POST" in args:
            posts.append(1)
            run(args, **kwargs)
            return subprocess.CompletedProcess(args, 1, stdout="", stderr="lost response")
        return run(args, **kwargs)
    monkeypatch.setattr(recovery.subprocess, "run", lost_ack)
    with pytest.raises(recovery.RecoveryEvidenceError, match="ACK publication outcome unknown"):
        recovery.execute_operator_pickup(**_args(case))
    monkeypatch.setattr(recovery.subprocess, "run", run)
    before_resume = len(checks)
    result = recovery.resume_operator_pickup(**_args(case))
    assert result["state"] == "pinned" and len(posts) == 1
    assert before_resume >= 3 and len(checks) > before_resume
    assert all(item["unrecorded_effects"] == "UNKNOWN" for item in checks)

    from app.builderops import openhands_pr_cycle as cycle
    from scripts import verify_operator_successor
    (case["worktree"] / "file.txt").write_text("synthetic repair\n")
    _git(case["worktree"], "commit", "-am", "repair")
    head = _git(case["worktree"], "rev-parse", "HEAD")
    live = case["pr_data"]
    live["head"]["sha"] = head
    live["body"] = (f"Governing-Issue: #6561\nFixes #6561\n"
                    f"Pickup-Receipt: {result['pickup_receipt']}\n")
    class Executor:
        def __init__(self, **kwargs): pass
        def run(self, args, *, cwd):
            return subprocess.CompletedProcess(args, 0, "RasmusTho\n", "")
    monkeypatch.setattr(cycle, "SubprocessExecutor", Executor)
    monkeypatch.setattr(cycle.closure, "_api", lambda *args: {
        "full_name": "RasmusTho/agentic-pkm-mvp", "default_branch": "main"})
    monkeypatch.setattr(cycle.closure, "_pr", lambda *args: live)
    monkeypatch.setattr(cycle.closure, "_closing_issue_references", lambda *args: [6561])
    def pages(executor, cwd, endpoint):
        if endpoint == "/issues/6561/comments": return list(case["comments"].values())
        if endpoint == "/issues/6562/comments": return []
        if endpoint == "/pulls/6562/files": return [{"filename": "file.txt"}]
        raise AssertionError(endpoint)
    monkeypatch.setattr(cycle, "_api_pages", pages)
    args = {key: case[key] for key in ("issue", "pr", "worktree", "workspace_root", "agent", "session", "cwd")}
    proof = verify_operator_successor.verify(**args)
    assert proof["head"] == head and proof["task_pr_projection"] == projection

    # A legitimate renewal during the final native source check must not be
    # confused with a new claimant or lifecycle registration.
    runtime_check = guard.check_runtime
    checks = []
    def heartbeat_during_guard(**kwargs):
        result = runtime_check(**kwargs)
        checks.append(1)
        if len(checks) == 2:
            leases.heartbeat(case["store"], case["receipt"]["predecessor"]["task_id"], case["agent"])
            agent_worktree.heartbeat_worktree(case["cwd"], worktree=case["worktree"], owner=case["session"])
        return result
    with monkeypatch.context() as patch:
        patch.setattr(guard, "check_runtime", heartbeat_during_guard)
        assert verify_operator_successor.verify(**args)["head"] == head
    assert len(checks) == 2

    import sqlite3
    with sqlite3.connect(source_bound["database"]) as db:
        db.execute("INSERT INTO thread_spawn_edges VALUES (?, ?, ?)",
                   (guard.CHILD, "01a10000-0000-7000-8000-000000000003", "open"))
    with pytest.raises(cycle.CycleError, match="UNKNOWN"):
        verify_operator_successor.verify(**args)
    with sqlite3.connect(source_bound["database"]) as db:
        db.execute("DELETE FROM thread_spawn_edges WHERE child_thread_id=?",
                   ("01a10000-0000-7000-8000-000000000003",))

    # Release after the last #6561 source callback must be caught by the
    # common final dispatcher readback, before proof is returned.
    checks.clear()
    def release_during_guard(**kwargs):
        result = runtime_check(**kwargs)
        checks.append(1)
        if len(checks) == 2:
            leases.release(case["store"], case["receipt"]["predecessor"]["task_id"], case["agent"])
        return result
    with monkeypatch.context() as patch:
        patch.setattr(guard, "check_runtime", release_during_guard)
        with pytest.raises((cycle.CycleError, cycle.closure.ClosureError)):
            verify_operator_successor.verify(**args)
    assert len(checks) == 2


@pytest.mark.parametrize("operator_case", [(6561, 6562, "codex-issue6561-normal-transport", 9)], indirect=True)
@pytest.mark.parametrize("target", [True, False])
def test_6561_wal_changes_between_pickup_checkpoints(operator_case, codex_6561_source, monkeypatch, target):
    import sqlite3
    case = operator_case
    source_bound = codex_6561_source
    guard = _bind_6561_sources(case, source_bound, monkeypatch)
    db = sqlite3.connect(source_bound["database"])
    db.execute("PRAGMA journal_mode=WAL")
    db.execute("INSERT INTO thread_spawn_edges VALUES (?, ?, ?)",
               ("unrelated-seed", "01a10000-0000-7000-8000-000000000002", "open"))
    db.commit()
    original = recovery._post_and_pin_operator_ack
    def post(**kwargs):
        db.execute("INSERT INTO thread_spawn_edges VALUES (?, ?, ?)",
                   (guard.CHILD if target else "unrelated", "01a10000-0000-7000-8000-000000000001", "open"))
        db.commit()
        return original(**kwargs)
    monkeypatch.setattr(recovery, "_post_and_pin_operator_ack", post)
    try:
        if target:
            with pytest.raises(recovery.RecoveryEvidenceError, match="UNKNOWN"):
                recovery.execute_operator_pickup(**_args(case))
            assert 2 not in case["comments"]
            assert case["store"].get_task(case["receipt"]["predecessor"]["task_id"]).lease_id != case["old_lease"].lease_id
        else:
            assert recovery.execute_operator_pickup(**_args(case))["state"] == "pinned"
    finally:
        db.close()


@pytest.mark.parametrize("operator_case", [(6561, 6562, "codex-issue6561-normal-transport", 9)], indirect=True)
def test_6561_unknown_target_child_refuses_before_claim(operator_case, codex_6561_source, monkeypatch):
    import sqlite3
    case = operator_case
    source_bound = codex_6561_source
    guard = _bind_6561_sources(case, source_bound, monkeypatch)
    with sqlite3.connect(source_bound["database"]) as db:
        db.execute("INSERT INTO thread_spawn_edges VALUES (?, ?, ?)",
                   (guard.CHILD, "01a10000-0000-7000-8000-000000000004", "open"))
    with pytest.raises(recovery.RecoveryEvidenceError, match="UNKNOWN"):
        recovery.execute_operator_pickup(**_args(case))
    assert case["store"].get_task(case["receipt"]["predecessor"]["task_id"]).lease_id == case["old_lease"].lease_id
    assert 2 not in case["comments"]


@pytest.mark.parametrize("operator_case", [(6561, 6562, "codex-issue6561-normal-transport", 9)], indirect=True)
@pytest.mark.parametrize("drift", ["closed", "label_removed"])
def test_6561_issue_drift_in_last_guard_refuses_before_claim(operator_case, codex_6561_source, monkeypatch, drift):
    case = operator_case
    guard = _bind_6561_sources(case, codex_6561_source, monkeypatch)
    task_id = case["receipt"]["predecessor"]["task_id"]
    events = case["store"].list_events(task_id)
    registry = agent_worktree._default_registry_path(case["cwd"])
    row = agent_worktree._locked_lifecycle_snapshot(registry)[str(case["worktree"])]
    original = guard.check
    calls = []
    def drift_during_guard(**kwargs):
        result = original(**kwargs)
        calls.append(1)
        if len(calls) == 2:
            if drift == "closed":
                case["issue_data"]["state"] = "closed"
            else:
                case["issue_data"]["labels"] = []
        return result
    monkeypatch.setattr(guard, "check", drift_during_guard)
    with pytest.raises(recovery.RecoveryEvidenceError, match="current issue validation failed"):
        recovery.execute_operator_pickup(**_args(case))
    assert len(calls) == 2
    assert case["store"].get_task(task_id).lease_id == case["old_lease"].lease_id
    assert case["store"].list_events(task_id) == events
    assert agent_worktree._locked_lifecycle_snapshot(registry)[str(case["worktree"])] == row
    assert 2 not in case["comments"]


@pytest.mark.parametrize("operator_case", [(6561, 6562, "codex-issue6561-normal-transport", 9)], indirect=True)
def test_6561_contradictory_linked_pr_refuses_draft_and_claim(operator_case, codex_6561_source, monkeypatch):
    case = operator_case
    _bind_6561_sources(case, codex_6561_source, monkeypatch)
    task_id = case["receipt"]["predecessor"]["task_id"]
    with case["store"]._connect() as conn:
        conn.execute("UPDATE dispatcher_tasks SET linked_pr=? WHERE task_id=?", ("999999", task_id))
        conn.execute("UPDATE dispatcher_events SET payload=? WHERE event_id=?",
                     (json.dumps({"linked_pr": 999999}), "fixture-linked-pr"))
    events = case["store"].list_events(task_id)
    registry = agent_worktree._default_registry_path(case["cwd"])
    row = agent_worktree._locked_lifecycle_snapshot(registry)[str(case["worktree"])]
    from scripts import legacy_operator_evidence
    with pytest.raises(recovery.RecoveryEvidenceError, match="linked to a different PR"):
        legacy_operator_evidence.build_draft(cwd=case["cwd"], issue=6561, pr=6562,
            worktree=case["worktree"], base=case["receipt"]["base"], agent=case["agent"], session=case["session"])
    with pytest.raises(recovery.RecoveryEvidenceError, match="linked to a different PR"):
        recovery.execute_operator_pickup(**_args(case))
    assert case["store"].get_task(task_id).lease_id == case["old_lease"].lease_id
    assert case["store"].list_events(task_id) == events
    assert agent_worktree._locked_lifecycle_snapshot(registry)[str(case["worktree"])] == row
    assert 2 not in case["comments"]


@pytest.mark.parametrize("operator_case", [(6561, 6562, "codex-issue6561-normal-transport", 9)], indirect=True)
def test_6561_linked_pr_drift_in_last_guard_refuses_before_claim(operator_case, codex_6561_source, monkeypatch):
    case = operator_case
    guard = _bind_6561_sources(case, codex_6561_source, monkeypatch)
    task_id = case["receipt"]["predecessor"]["task_id"]
    events = case["store"].list_events(task_id)
    original = guard.check
    calls = []
    def drift_during_guard(**kwargs):
        result = original(**kwargs)
        calls.append(1)
        if len(calls) == 2:
            with case["store"]._connect() as conn:
                conn.execute("UPDATE dispatcher_tasks SET linked_pr=? WHERE task_id=?", ("999999", task_id))
        return result
    monkeypatch.setattr(guard, "check", drift_during_guard)
    with pytest.raises(recovery.RecoveryEvidenceError, match="linked to a different PR"):
        recovery.execute_operator_pickup(**_args(case))
    assert len(calls) == 2
    assert case["store"].get_task(task_id).lease_id == case["old_lease"].lease_id
    assert case["store"].list_events(task_id) == events
    assert 2 not in case["comments"]


@pytest.mark.parametrize("operator_case", [(6561, 6562, "codex-issue6561-normal-transport", 9)], indirect=True)
def test_6561_postclaim_linked_pr_drift_retains_claim_and_resume_refuses(operator_case, codex_6561_source, monkeypatch):
    case = operator_case
    _bind_6561_sources(case, codex_6561_source, monkeypatch)
    task_id = case["receipt"]["predecessor"]["task_id"]
    original = recovery._successor_claim_readback
    calls = []
    def drift_after_claim(**kwargs):
        result = original(**kwargs)
        calls.append(1)
        if len(calls) == 1:
            with case["store"]._connect() as conn:
                conn.execute("UPDATE dispatcher_tasks SET linked_pr=? WHERE task_id=?", ("999999", task_id))
        return result
    monkeypatch.setattr(recovery, "_successor_claim_readback", drift_after_claim)
    with pytest.raises(recovery.RecoveryEvidenceError, match="linked to a different PR"):
        recovery.execute_operator_pickup(**_args(case))
    current = case["store"].get_task(task_id)
    assert current.lease_id != case["old_lease"].lease_id and 2 not in case["comments"]
    registry = agent_worktree._default_registry_path(case["cwd"])
    row = agent_worktree._locked_lifecycle_snapshot(registry)[str(case["worktree"])]
    assert "operator_registration" not in row
    events = case["store"].list_events(task_id)
    with pytest.raises(recovery.RecoveryEvidenceError, match="linked to a different PR"):
        recovery.resume_operator_pickup(**_args(case))
    assert case["store"].list_events(task_id) == events and 2 not in case["comments"]


@pytest.mark.parametrize("operator_case", [(6561, 6562, "codex-issue6561-normal-transport", 9)], indirect=True)
def test_6561_missing_linked_pr_field_refuses_before_claim(operator_case, codex_6561_source, monkeypatch):
    case = operator_case
    _bind_6561_sources(case, codex_6561_source, monkeypatch)
    task_id = case["receipt"]["predecessor"]["task_id"]
    original = recovery._readonly_dispatcher
    def missing_projection(**kwargs):
        task, events, lease = original(**kwargs)
        task.pop("linked_pr")
        return task, events, lease
    monkeypatch.setattr(recovery, "_readonly_dispatcher", missing_projection)
    with pytest.raises(recovery.RecoveryEvidenceError, match="PR projection is unavailable"):
        recovery.execute_operator_pickup(**_args(case))
    assert case["store"].get_task(task_id).lease_id == case["old_lease"].lease_id
    assert 2 not in case["comments"]
