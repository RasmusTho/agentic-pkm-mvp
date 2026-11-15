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


def _git(cwd, *args):
    return subprocess.check_output(["git", "-C", str(cwd), *args], text=True).strip()


def _comment(body, ident, timestamp):
    at = datetime.fromtimestamp(timestamp, timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    return {"id": ident, "user": {"login": "RasmusTho"}, "author_association": "OWNER",
            "created_at": at, "updated_at": at,
            "issue_url": "https://api.github.com/repos/RasmusTho/agentic-pkm-mvp/issues/6601",
            "body": json.dumps({"operator_reconciliation.v1": body}, sort_keys=True)}


@pytest.fixture
def operator_case(tmp_path, monkeypatch):
    repo = tmp_path / "repo"
    repo.mkdir()
    _git(repo, "init", "-b", "main")
    _git(repo, "config", "user.name", "Fixture")
    _git(repo, "config", "user.email", "fixture@example.invalid")
    (repo / "file.txt").write_text("base\n")
    _git(repo, "add", "file.txt")
    _git(repo, "commit", "-m", "base")
    base = _git(repo, "rev-parse", "HEAD")
    checkout = tmp_path / "checkout"
    _git(repo, "worktree", "add", "-b", "codex/example", str(checkout))
    (checkout / "file.txt").write_text("candidate\n")
    _git(checkout, "add", "file.txt")
    _git(checkout, "commit", "-m", "candidate")
    head = _git(checkout, "rev-parse", "HEAD")

    now = time.time()
    agent_worktree.register_worktree(checkout, worktree=checkout, owner="old-session", now=now - 7200, ttl_seconds=60)
    state_dir = tmp_path / "dispatcher"
    state_dir.mkdir()
    db_path = state_dir / "dispatcher.sqlite3"
    store = SqliteStore(db_path, JsonlEventWriter(state_dir / "events.jsonl"))
    store.initialize()
    task_id = "github-RasmusTho--agentic-pkm-mvp-issue-6601"
    old_time = (datetime.now(timezone.utc) - timedelta(hours=2)).isoformat(timespec="microseconds")
    store.upsert_task(TaskRecord(task_id=task_id, issue_number=6601, title="fixture", status="ready", priority="high",
                                source_anchor_refs=[], created_at=old_time, updated_at=old_time,
                                repo="RasmusTho/agentic-pkm-mvp"))
    with monkeypatch.context() as patch:
        patch.setattr(leases, "_utc_now", lambda: old_time)
        _, old_lease = leases.claim(store, task_id, "old-agent")
        for minutes in (110, 100):
            heartbeat_at = (datetime.now(timezone.utc) - timedelta(minutes=minutes)).isoformat(timespec="microseconds")
            patch.setattr(leases, "_utc_now", lambda: heartbeat_at)
            leases.heartbeat(store, task_id, "old-agent")

    monkeypatch.setattr(recovery, "load_dispatcher_paths", lambda *_args, **_kwargs: SimpleNamespace(
        state_dir=state_dir, db_path=db_path))
    monkeypatch.setenv("CODEX_SESSION_ID", "new-session")
    source_root = str(Path(recovery.__file__).resolve().parents[2])
    monkeypatch.setenv("PYTHONPATH", source_root)
    predecessor = recovery.read_live_predecessor(cwd=checkout, issue=6601)
    candidate = recovery.read_clean_candidate(cwd=checkout, worktree=checkout)
    registration = recovery.read_expired_registration(cwd=checkout, candidate=candidate)
    old_record = agent_worktree._locked_lifecycle_snapshot(agent_worktree._default_registry_path(checkout))[str(checkout)]
    sources = {"attempts": ["fixture:attempts"], "github": ["fixture:github"]}
    writer = {"state": "stopped", "delegations": "stopped", "restart": "reconciled",
              "last_activity": (datetime.now(timezone.utc) - timedelta(hours=2)).isoformat(),
              "boot": (datetime.now(timezone.utc) - timedelta(hours=1)).isoformat(),
              "sources": {"execution": ["fixture:execution"], "delegations": ["fixture:delegations"],
                          "restart": ["fixture:restart"]}}
    origin_receipt = (f"pickup-claim-complete issue=6601 branch=codex/example worktree={checkout} "
                      f"coordination_mode=dispatcher-backed fallback_reason=none task_id={task_id} "
                      f"lease_id={old_lease.lease_id} holder=old-agent evidence=verified-dispatcher-lease")
    pr_body = f"Governing-Issue: #6601\n\nPickup-Receipt: {origin_receipt}\n\nCloses #6601\n"
    publication = {"state": "reconciled", "pr": 6602, "head": head, "repo": "RasmusTho/agentic-pkm-mvp",
                   "branch": "codex/example", "pr_state": "OPEN", "sources": sources}
    publication["body_sha256"] = hashlib.sha256(pr_body.encode()).hexdigest()
    receipt = {"issue": 6601, "mode": "operator", "account": "RasmusTho",
               "mandate": {"reference": "fixture:explicit-user-direction", "repo": "RasmusTho/agentic-pkm-mvp",
                           "issue": 6601, "effects": ["reconcile", "claim", "register", "acknowledge"]},
               "successor": {"agent": "new-agent", "session": "new-session"}, "predecessor": predecessor,
               "registration": registration, "candidate": candidate, "writer": writer, "publication": publication,
               "branch": "codex/example", "writable_worktree": str(checkout), "predecessor_registration": old_record,
               "branch_history_digest": registration["branch_history_digest"], "base": base,
               "unpublished_candidate_head": head, "changed_files": ["file.txt"]}
    comments = {1: _comment(receipt, 1, now - 5)}
    pr = {"number": 6602, "state": "open", "body": pr_body, "head": {"ref": "codex/example", "sha": head,
          "repo": {"full_name": "RasmusTho/agentic-pkm-mvp"}},
          "base": {"ref": "main", "repo": {"full_name": "RasmusTho/agentic-pkm-mvp"}}}

    def github_read(args, *, cwd):
        if "user" in args:
            return "RasmusTho\n"
        if "--slurp" in args and any("/issues/6601/comments" in arg for arg in args):
            return json.dumps([list(comments.values())])
        if "--slurp" in args:
            return json.dumps([[pr]])
        if any("/pulls/6602" in arg for arg in args):
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
    return {"cwd": checkout, "issue": 6601, "pr": 6602, "worktree": checkout, "agent": "new-agent",
            "session": "new-session", "comment_id": 1, "workspace_root": tmp_path / "model", "store": store,
            "old_lease": old_lease, "comments": comments, "old_record": old_record, "receipt": receipt, "pr_data": pr}


def _args(case):
    return {key: case[key] for key in ("cwd", "issue", "pr", "worktree", "agent", "session", "comment_id", "workspace_root")}


def test_operator_cli_emits_the_existing_pickup_receipt_line(monkeypatch, capsys, tmp_path):
    receipt = "pickup-claim-complete issue=6601 branch=codex/example worktree=/fixture coordination_mode=dispatcher-backed"
    monkeypatch.setattr(recovery, "execute_operator_pickup", lambda **_kwargs: {"state": "pinned", "pickup_receipt": receipt})
    monkeypatch.setattr(sys, "argv", ["legacy_owner_recovery", "pickup", "--issue", "6601", "--pr", "6602",
                                   "--worktree", str(tmp_path), "--agent", "new", "--session", "s",
                                   "--comment-id", "1", "--workspace-root", str(tmp_path / "model")])
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


@pytest.mark.parametrize("kind", ["root", "relative", "overlap"])
def test_operator_rejects_workspace_before_read_or_claim(operator_case, monkeypatch, kind):
    case = operator_case
    args = _args(case)
    args["workspace_root"] = Path("/") if kind == "root" else (
        Path("relative") if kind == "relative" else case["worktree"])

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
    observed = recovery.preflight_operator_pickup(**_args(case))
    assert observed["candidate"]["head"] != observed["publication"]["head"]


def test_competing_operator_invocations_only_one_can_claim(operator_case, monkeypatch):
    case = operator_case
    rival = copy.deepcopy(case["receipt"])
    rival["successor"]["agent"] = "rival-agent"
    case["comments"][4] = _comment(rival, 4, time.time() - 5)
    original = recovery.preflight_operator_pickup
    barrier = threading.Barrier(2)

    def concurrent_preflight(**kwargs):
        observed = original(**kwargs)
        barrier.wait(timeout=15)
        return observed

    monkeypatch.setattr(recovery, "preflight_operator_pickup", concurrent_preflight)
    def attempt(index):
        args = _args(case)
        if index:
            args.update(agent="rival-agent", comment_id=4)
        try:
            return recovery.execute_operator_pickup(**args)
        except recovery.RecoveryEvidenceError:
            return None

    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(attempt, range(2)))
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
        origin={"mode": "dispatcher-backed", "lease_id": case["old_lease"].lease_id, "agent": "old-agent"},
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
        origin={"mode": "dispatcher-backed", "lease_id": case["old_lease"].lease_id, "agent": "old-agent"},
        registration=row, records={str(case["worktree"]): row}, comments=list(case["comments"].values()),
        issue_comments=[], issue=6601, pr_number=6602, branch="codex/example", head=head, files=["file.txt"], entry=entry,
    )
    assert case["store"].get_lease(result["lease_id"]).heartbeat_at is not None
    with pytest.raises(openhands_pr_cycle.CycleError, match="verification is incomplete"):
        openhands_pr_cycle._premerge(None, {"head_sha": head}, {"engine": "codex"}, {})
