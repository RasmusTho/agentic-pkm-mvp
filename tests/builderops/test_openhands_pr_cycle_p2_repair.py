"""Regression coverage for retained PR-cycle and worktree authority."""
import json
import time

import pytest

from app.builderops import epic_workspace as ew
from app.builderops import openhands_pr_cycle as cycle
from scripts import agent_worktree
from tests.builderops.test_openhands_pr_cycle import (
    HEAD, _event_time, _handoff, _native_authority_fixture, _prepare_and_pin, fetch, setup,
)
from tests.builderops.test_openhands_transfer_registration import _pickup
from tests.ops.test_agent_worktree import GENERATION


def _dispatcher_fixture(tmp_path, monkeypatch):
    f = _native_authority_fixture(tmp_path, monkeypatch)
    now = int(time.time())
    agent_worktree.register_worktree(f["source"], worktree=f["worktree"], owner="session-original", now=now - 800)
    f["events"][0]["timestamp"] = _event_time(now - 700 + .5)
    return f, now


def _both_consumers(f):
    pr = {**f["pr"], "review_context": {}, "review_material": {}}
    cycle._add_transfer_review_context(f["layout"], f["entry"], pr)
    return cycle.native_authority(f["layout"], f["pr"], f["entry"])


@pytest.mark.parametrize("when,accepted", [(-701, True), (-700, False), (-699, False)])
def test_dispatcher_origin_uses_whole_comment_seconds_for_both_consumers(tmp_path, monkeypatch, when, accepted):
    f, now = _dispatcher_fixture(tmp_path, monkeypatch)
    f["comments"].append(_pickup(7, now + when, "rival", "rival-session", "/old/path", branch="codex/old"))
    if accepted:
        assert _both_consumers(f)["owner"]["lease_id"] == "old-lease"
    else:
        with pytest.raises(cycle.CycleError):
            cycle._add_transfer_review_context(f["layout"], f["entry"], {**f["pr"], "review_context": {}, "review_material": {}})
        with pytest.raises(cycle.CycleError):
            cycle.native_authority(f["layout"], f["pr"], f["entry"])


def test_merge_old_intent_allows_only_fresh_different_head(tmp_path, monkeypatch):
    layout, config, server = setup(tmp_path, monkeypatch)
    old = "c" * 40
    saved = {"kind": "pr_cycle", "number": 10, "identity": "old", "merge_exit_code": 1,
             "merge_intent": {"number": 10, "head_sha": old, "governing_issue": 6618, "closing_issues": []}}
    cycle._save(layout, saved)
    readback = {"state": "open", "merged_at": None, "head": {"sha": HEAD}}
    monkeypatch.setattr(cycle.closure, "_pr", lambda *args: readback)
    called = []
    monkeypatch.setattr(cycle, "_advance_one", lambda layout, pr, entry, **kw: called.append(pr["head_sha"]) or {"number": 10, "action": "review"})
    result = cycle.advance(layout, config, fetch=fetch, http=server)
    assert called == [HEAD]
    assert any(row.get("intent_head_sha") == old for row in result["results"])
    assert cycle._find(layout, 10, "old") == saved
    called.clear()
    readback["head"]["sha"] = old
    cycle.advance(layout, config, fetch=fetch, http=server)
    assert called == []  # old-head unknown cannot be replayed from a stale scan
    readback["head"]["sha"] = "d" * 40
    cycle.advance(layout, config, fetch=fetch, http=server)
    assert called == []  # scan and reconciliation disagreed


def _row(path, owner, at, status="released"):
    row = {"path": str(path.resolve()), "branch": "codex/example", "generation": GENERATION, "owner": owner,
           "status": status, "registered_at": 10, "heartbeat_at": 10, "authority_since": 10,
           "authority_until": at, "released_at": at, "expires_at": at}
    if status == "removed":
        row["removed_at"] = at + 10
    if status == "removal_pending":
        row.update(removal_pending_at=at + 10, removal_pending_from_status="released")
    return row


def _registry(tmp_path, monkeypatch, rows, target, branch="codex/example"):
    repo, reg = tmp_path / "repo", tmp_path / "registry.json"
    repo.mkdir(exist_ok=True)
    reg.write_text(json.dumps({"schema": agent_worktree.REGISTRY_SCHEMA, "worktrees": {r["path"]: r for r in rows}}))
    monkeypatch.setattr(agent_worktree, "_worktree_identity", lambda *args: (target.resolve(), branch))
    monkeypatch.setattr(agent_worktree, "_worktree_generation", lambda *args, **kw: GENERATION)
    return repo, reg


@pytest.mark.parametrize("status", ["removed", "removal_pending"])
def test_tombstone_is_the_latest_predecessor(tmp_path, monkeypatch, status):
    a, b, c = (tmp_path / name for name in ("a", "b", "c"))
    repo, reg = _registry(tmp_path, monkeypatch, [_row(a, "older", 100), _row(b, "last", 200, status)], c)
    result = agent_worktree.register_worktree(repo, worktree=c, owner="next", registry_path=reg, now=300)
    assert result["prior_owner"]["owner"] == "last"
    assert result["prior_owner"]["released_at"] == 200


def test_tombstone_without_release_is_not_laundered(tmp_path, monkeypatch):
    a, b = tmp_path / "a", tmp_path / "b"
    row = _row(a, "expired", 100, "removed")
    del row["released_at"]
    repo, reg = _registry(tmp_path, monkeypatch, [row], b)
    result = agent_worktree.register_worktree(repo, worktree=b, owner="next", registry_path=reg, now=300)
    assert result["prior_owner"]["released_at"] is None


def test_cross_branch_reuse_refuses_without_destroying_history(tmp_path, monkeypatch):
    a, b = tmp_path / "a", tmp_path / "b"
    row = _row(a, "last", 100)
    repo, reg = _registry(tmp_path, monkeypatch, [row], a, branch="codex/other")
    before = reg.read_bytes()
    with pytest.raises(agent_worktree.WorktreeLifecycleError, match="replacement path"):
        agent_worktree.register_worktree(repo, worktree=a, owner="other", registry_path=reg, now=200)
    assert reg.read_bytes() == before
    monkeypatch.setattr(agent_worktree, "_worktree_identity", lambda *args: (b.resolve(), "codex/example"))
    result = agent_worktree.register_worktree(repo, worktree=b, owner="next", registry_path=reg, now=300)
    assert result["prior_owner"]["owner"] == "last"


def test_removed_predecessor_supports_real_transfer_at_both_consumers(tmp_path, monkeypatch):
    f, now = _dispatcher_fixture(tmp_path, monkeypatch)
    old, new, source = f["worktree"], tmp_path / "successor", f["source"]
    original = agent_worktree.release_worktree(source, worktree=old, owner="session-original", now=now - 400)
    cycle.subprocess.run(["git", "-C", str(source), "worktree", "move", str(old), str(new)],
                         check=True, capture_output=True)
    registry = agent_worktree._default_registry_path(source)
    payload = json.loads(registry.read_text())
    payload["worktrees"][str(old)]["status"] = "removed"
    payload["worktrees"][str(old)]["removed_at"] = now - 390
    registry.write_text(json.dumps(payload))
    successor = agent_worktree.register_worktree(source, worktree=new, owner="session-successor", now=now - 300)
    assert successor["prior_owner"]["path"] == str(old)
    f["events"][:] = [
        {"task_id": f["task_id"], "event_type": "task.claimed", "actor": "original", "lease_id": "old-lease",
         "timestamp": _event_time(now - 700), "payload": {"session": "session-original", "ttl_minutes": 90}},
        {"task_id": f["task_id"], "event_type": "task.released", "actor": "original", "lease_id": "old-lease",
         "timestamp": _event_time(now - 600), "payload": {"reason": "manual"}},
        {"task_id": f["task_id"], "event_type": "task.claimed", "actor": "successor", "lease_id": "new-lease",
         "timestamp": _event_time(now - 500), "payload": {"session": "session-successor", "ttl_minutes": 90}},
    ]
    f["task"].update(claimed_by="successor", lease_id="new-lease")
    f["lease"].update(holder="successor", lease_id="new-lease")
    f["entry"].update(owner_worktree=str(new), claimant="successor", session="session-successor", lease_id="new-lease")
    f["worktree"] = new
    record = _handoff(f, predecessor=("original", "session-original"), successor=("successor", "session-successor"),
                      registration=successor, prior_lease="old-lease", pickup_lease="new-lease")
    record["successor_acknowledgment"]["prior_worktree_release"].update(path=str(old), generation=original["generation"])
    f["comments"][:] = _prepare_and_pin(f, record, receipt_at=now - 650, ack_at=now - 100)
    assert _both_consumers(f)["owner"]["lease_id"] == "new-lease"


def _verify_setup(tmp_path, monkeypatch):
    layout, _, _ = setup(tmp_path, monkeypatch)
    ew._record_worker(layout, 6618, state="stopped_verified", image="agent-server@sha256:" + "c" * 64)
    saved = {"kind": "pr_cycle", "number": 10, "identity": "verify"}
    return layout, saved


def test_verify_recovers_exact_running_container_before_retry(tmp_path, monkeypatch):
    layout, saved = _verify_setup(tmp_path, monkeypatch)
    cid = "d" * 64
    name = "epicws-git-123456789abc"
    saved["verification_intent"] = {"protocol": ew.LAUNCH_PROTOCOL, "worker": "reviewer", "head_sha": HEAD,
                                    "targets": ["tests/example.py"], "test_venv": "/approved/venv",
                                    "container": name, "container_id": cid}
    ew._mutate_mapping(layout, "reviewer", lambda row: row.update(checkpoint_inspection_unknown={
        "at": ew._now(), "protocol": ew.LAUNCH_PROTOCOL, "name": name, "container_id": cid}))
    with pytest.raises(ew.TakeoverRefused):
        ew._assert_no_pending_takeover(cycle._mapping(layout, "reviewer"))
    actions = []
    def remove(n, labels, runner, *, cid=None):
        actions.append(("remove", n, cid))
    monkeypatch.setattr(ew, "_remove_owned", remove)
    def command(args, *, timeout):
        actions.append((args[1], args[-1]))
        if args[1] == "create":
            return cycle.subprocess.CompletedProcess(args, 0, "e" * 64, "")
        return cycle.subprocess.CompletedProcess(args, 0, "1 passed in 1s", "")
    monkeypatch.setattr(cycle, "_command", command)
    result = cycle.sandbox_verify(layout, "reviewer", HEAD, ["tests/example.py"], "/approved/venv", saved)
    assert result["passed"]
    assert actions[0] == ("remove", name, cid)
    assert actions[1][0] == "create" and actions[2] == ("start", "e" * 64)
    assert saved["verification_previous_intent"]["container_id"] == cid
    assert "checkpoint_inspection_unknown" not in cycle._mapping(layout, "reviewer")


def test_verify_unknown_or_competing_lifecycle_never_retries(tmp_path, monkeypatch):
    layout, saved = _verify_setup(tmp_path, monkeypatch)
    saved["verification_intent"] = {"container": "old-docker-run"}
    monkeypatch.setattr(cycle, "_command", lambda *args, **kw: pytest.fail("must not launch"))
    with pytest.raises(cycle.CycleError, match="legacy"):
        cycle.sandbox_verify(layout, "reviewer", HEAD, ["tests/example.py"], "/approved/venv", saved)
    with ew._worker_lifecycle_lock(layout, "reviewer"):
        with pytest.raises(ew.LaunchRefused):
            cycle.sandbox_verify(layout, "reviewer", HEAD, ["tests/example.py"], "/approved/venv", saved)


def test_verify_does_not_create_when_another_checkpoint_writer_is_unresolved(tmp_path, monkeypatch):
    layout, saved = _verify_setup(tmp_path, monkeypatch)
    marker = {"at": ew._now(), "protocol": ew.LAUNCH_PROTOCOL,
              "name": "epicws-git-123456789abc", "container_id": "d" * 64}
    ew._mutate_mapping(layout, "reviewer", lambda row: row.update(checkpoint_inspection_unknown=marker))
    monkeypatch.setattr(cycle, "_command", lambda *args, **kwargs: pytest.fail("must not create a verifier"))
    with pytest.raises(cycle.CycleError, match="another lifecycle inspection"):
        cycle.sandbox_verify(layout, "reviewer", HEAD, ["tests/example.py"], "/approved/venv", saved)
    assert cycle._mapping(layout, "reviewer")["checkpoint_inspection_unknown"] == marker
    assert "verification_intent" not in saved


def test_verify_reconciliation_keeps_a_newer_checkpoint_hold(tmp_path, monkeypatch):
    layout, saved = _verify_setup(tmp_path, monkeypatch)
    old = {"at": ew._now(), "protocol": ew.LAUNCH_PROTOCOL,
           "name": "epicws-git-123456789abc", "container_id": "d" * 64}
    newer = {"at": ew._now(), "protocol": ew.LAUNCH_PROTOCOL,
             "name": "epicws-git-fedcba987654", "container_id": "e" * 64}
    saved["verification_intent"] = {"protocol": ew.LAUNCH_PROTOCOL, "worker": "reviewer", "head_sha": HEAD,
                                    "targets": ["tests/example.py"], "test_venv": "/approved/venv",
                                    "container": old["name"], "container_id": old["container_id"]}
    ew._mutate_mapping(layout, "reviewer", lambda row: row.update(checkpoint_inspection_unknown=old))
    def remove(*args, **kwargs):
        ew._mutate_mapping(layout, "reviewer", lambda row: row.update(checkpoint_inspection_unknown=newer))
    monkeypatch.setattr(ew, "_remove_owned", remove)
    with pytest.raises(cycle.CycleError, match="marker changed"):
        cycle.sandbox_verify(layout, "reviewer", HEAD, ["tests/example.py"], "/approved/venv", saved)
    assert cycle._mapping(layout, "reviewer")["checkpoint_inspection_unknown"] == newer


def test_verify_completion_keeps_a_newer_checkpoint_hold(tmp_path, monkeypatch):
    layout, saved = _verify_setup(tmp_path, monkeypatch)
    newer = {"at": ew._now(), "protocol": ew.LAUNCH_PROTOCOL,
             "name": "epicws-git-fedcba987654", "container_id": "e" * 64}
    def command(argv, *, timeout):
        if argv[1] == "create":
            return cycle.subprocess.CompletedProcess(argv, 0, "d" * 64, "")
        ew._mutate_mapping(layout, "reviewer", lambda row: row.update(checkpoint_inspection_unknown=newer))
        return cycle.subprocess.CompletedProcess(argv, 0, "1 passed in 1s", "")
    monkeypatch.setattr(cycle, "_command", command)
    monkeypatch.setattr(ew, "_remove_owned", lambda *args, **kwargs: None)
    with pytest.raises(cycle.CycleError, match="marker changed"):
        cycle.sandbox_verify(layout, "reviewer", HEAD, ["tests/example.py"], "/approved/venv", saved)
    assert cycle._mapping(layout, "reviewer")["checkpoint_inspection_unknown"] == newer


def _review_release_setup(tmp_path, monkeypatch):
    layout, _, _ = setup(tmp_path, monkeypatch)
    conversation = {"id": "old-conversation", "operation_id": "old-operation", "status": "created"}
    ew._record_worker(layout, 6618, conversation=conversation)
    observed = cycle._mapping(layout, "reviewer")
    saved = {"kind": "pr_cycle", "number": 10, "identity": "release",
             "execution_proof": {"operation_id": "old-operation", "conversation_id": "old-conversation",
                                 "container_id": observed["container_id"]}}
    return layout, observed, saved


def test_review_release_never_stops_a_successor_conversation(tmp_path, monkeypatch):
    layout, observed, saved = _review_release_setup(tmp_path, monkeypatch)
    successor = {"id": "new-conversation", "operation_id": "new-operation", "status": "created"}
    ew._record_worker(layout, 6618, conversation=successor, next_action="continue successor")
    monkeypatch.setattr(ew, "stop_worker", lambda *args, **kwargs: pytest.fail("must not stop successor"))
    with pytest.raises(cycle.CycleError, match="assignment changed"):
        cycle._release_reviewer(layout, "reviewer", saved, observed)
    assert cycle._mapping(layout, "reviewer")["conversation"] == successor
    assert cycle._mapping(layout, "reviewer")["next_action"] == "continue successor"
    assert "stop_intent" not in saved


def test_review_release_refuses_a_missing_legacy_container_id(tmp_path, monkeypatch):
    layout, _, saved = _review_release_setup(tmp_path, monkeypatch)
    ew._record_worker(layout, 6618, container_id=None)
    observed = cycle._mapping(layout, "reviewer")
    saved["execution_proof"]["container_id"] = None
    saved["stop_intent"] = {"container_id": None}
    monkeypatch.setattr(ew, "stop_worker", lambda *args, **kwargs: pytest.fail("must not stop without an ID"))
    with pytest.raises(cycle.CycleError, match="container lineage"):
        cycle._release_reviewer(layout, "reviewer", saved, observed)


def test_review_stop_readback_cannot_record_success_for_a_new_assignment(tmp_path, monkeypatch):
    layout, prior, saved = _review_release_setup(tmp_path, monkeypatch)
    saved["stop_intent"] = {"container_id": prior["container_id"], "assignment": ew.assignment_of(prior)}
    saved["stop_verified"] = True
    ew._record_worker(layout, 6618, state="stopped_verified", conversation={**prior["conversation"], "status": ew.CONVERSATION_ENDED})
    observed = cycle._mapping(layout, "reviewer")
    successor = {"id": "new-conversation", "operation_id": "new-operation", "status": "created"}
    def replace_after_readback(*args):
        ew._record_worker(layout, 6618, state="running", container_id="e" * 64,
                          conversation=successor, next_action="continue successor")
    monkeypatch.setattr(cycle, "_assert_stopped", replace_after_readback)
    with pytest.raises(cycle.CycleError, match="assignment changed"):
        cycle._release_reviewer(layout, "reviewer", saved, observed)
    current = cycle._mapping(layout, "reviewer")
    assert current["conversation"] == successor and current["next_action"] == "continue successor"
    assert not cycle._find(layout, 10, "release").get("stop_verified")


def test_review_stop_keeps_a_newer_assignment_during_checkpoint_inspection(tmp_path, monkeypatch):
    layout, observed, _ = _review_release_setup(tmp_path, monkeypatch)
    successor = {"id": "new-conversation", "operation_id": "new-operation", "status": "created"}
    def inspect(*args, **kwargs):
        ew._record_worker(layout, 6618, state="running", container_id="e" * 64,
                          conversation=successor, next_action="continue successor")
        return {"readable": False, "unique_work": True}, []
    monkeypatch.setattr(ew, "_inspect", inspect)
    with pytest.raises(ew.EpicWorkspaceError, match="assignment changed during stop"):
        ew.stop_worker(layout, "reviewer", reason="review completed; release model capacity",
                       expected_container_id=observed["container_id"], expected_assignment=observed,
                       runner=cycle._worker_runner)
    current = cycle._mapping(layout, "reviewer")
    assert current["state"] == "running" and current["container_id"] == "e" * 64
    assert current["conversation"] == successor and current["next_action"] == "continue successor"


@pytest.mark.parametrize("failure", ["none", "wrong-label", "engine-unavailable"])
def test_verify_reconciliation_uses_real_scoped_id_removal(tmp_path, monkeypatch, failure):
    layout, saved = _verify_setup(tmp_path, monkeypatch)
    old_id = "d" * 64
    old_name = "epicws-git-123456789abc"
    old = {"name": old_name, "id": old_id, "labels": {"epic-workspace.inspect": "1",
           ew.LABEL_EPIC: "6615", ew.LABEL_WORKER: "verify-reviewer"}}
    saved["verification_intent"] = {"protocol": ew.LAUNCH_PROTOCOL, "worker": "reviewer", "head_sha": HEAD,
                                    "targets": ["tests/example.py"], "test_venv": "/approved/venv",
                                    "container": old_name, "container_id": old_id}
    ew._mutate_mapping(layout, "reviewer", lambda row: row.update(checkpoint_inspection_unknown={
        "at": ew._now(), "protocol": ew.LAUNCH_PROTOCOL, "name": old_name, "container_id": old_id}))
    if failure == "wrong-label":
        old["labels"][ew.LABEL_WORKER] = "other"
    containers = {old_id: old}
    calls = []
    def runner(argv, **kwargs):
        calls.append(argv)
        if failure == "engine-unavailable":
            raise OSError("engine unavailable")
        if argv[1] == "ps":
            match = argv[argv.index("--filter") + 1]
            rows = [item["id"] for item in containers.values()
                    if match == f"name=^/{item['name']}$" or match == f"id={item['id']}"]
            return cycle.subprocess.CompletedProcess(argv, 0, "\n".join(rows), "")
        if argv[1] == "inspect":
            return cycle.subprocess.CompletedProcess(argv, 0, json.dumps(containers[argv[-1]]["labels"]), "")
        if argv[1] == "rm":
            containers.pop(argv[-1], None)
            return cycle.subprocess.CompletedProcess(argv, 0, "", "")
        raise AssertionError(argv)
    real_remove = ew._remove_owned
    monkeypatch.setattr(ew, "_remove_owned", lambda name, labels, ignored, *, cid=None:
                        real_remove(name, labels, runner, cid=cid))
    def command(argv, *, timeout):
        calls.append(argv)
        if argv[1] == "create":
            assert old_id not in containers
            new_id = "e" * 64
            name = argv[argv.index("--name") + 1]
            containers[new_id] = {"id": new_id, "name": name, "labels": {
                "epic-workspace.inspect": "1", ew.LABEL_EPIC: "6615", ew.LABEL_WORKER: "verify-reviewer"}}
            return cycle.subprocess.CompletedProcess(argv, 0, new_id, "")
        assert argv == ["docker", "start", "--attach", "e" * 64]
        return cycle.subprocess.CompletedProcess(argv, 0, "1 passed in 1s", "")
    monkeypatch.setattr(cycle, "_command", command)
    if failure != "none":
        with pytest.raises((ew.LaunchRefused, ew.EngineUnavailable)):
            cycle.sandbox_verify(layout, "reviewer", HEAD, ["tests/example.py"], "/approved/venv", saved)
        assert not any(call[1] == "create" for call in calls)
        assert cycle._mapping(layout, "reviewer")["checkpoint_inspection_unknown"]["container_id"] == old_id
    else:
        assert cycle.sandbox_verify(layout, "reviewer", HEAD, ["tests/example.py"], "/approved/venv", saved)["passed"]
        assert not containers
        assert any(call[:3] == ["docker", "rm", "--force"] and call[-1] == old_id for call in calls)


def test_verify_lost_create_can_only_leave_an_inert_distinct_name(tmp_path, monkeypatch):
    layout, saved = _verify_setup(tmp_path, monkeypatch)
    names, removed = [], []
    monkeypatch.setattr(ew, "_remove_owned", lambda name, labels, runner, *, cid=None: removed.append((name, cid)))
    def command(argv, *, timeout):
        if argv[1] == "create":
            names.append(argv[argv.index("--name") + 1])
            if len(names) == 1:
                raise cycle.CycleError("lost create response")
            return cycle.subprocess.CompletedProcess(argv, 0, "f" * 64, "")
        assert argv == ["docker", "start", "--attach", "f" * 64]
        return cycle.subprocess.CompletedProcess(argv, 0, "1 passed in 1s", "")
    monkeypatch.setattr(cycle, "_command", command)
    with pytest.raises(cycle.CycleError, match="lost create"):
        cycle.sandbox_verify(layout, "reviewer", HEAD, ["tests/example.py"], "/approved/venv", saved)
    assert "container_id" not in saved["verification_intent"]
    assert cycle.sandbox_verify(layout, "reviewer", HEAD, ["tests/example.py"], "/approved/venv", saved)["passed"]
    assert names[0] != names[1] and removed[0] == (names[0], None)


def test_advance_retries_interrupted_verification_after_reconciliation(tmp_path, monkeypatch):
    layout, config, server = setup(tmp_path, monkeypatch)
    cycle.advance(layout, config, fetch=fetch, http=server)
    state = ew._load_state(layout)
    conversation = state["issue_mappings"]["6618"]["conversation"]["id"]
    identity = next(row["identity"] for row in state["compact_receipts"] if row.get("kind") == "pr_cycle")
    server.conversations[conversation]["execution_status"] = "finished"
    response = json.dumps({"identity": identity, "head_sha": HEAD, "verdict": "pass", "findings": [],
                           "verify_targets": config[0]["verify_targets"], "owner_doc": {"paths": []}})
    server.events = [{"kind": "MessageEvent", "source": "agent", "detail": response}]
    server.final_responses[conversation] = response
    monkeypatch.setattr(ew, "stop_worker", lambda layout, worker, **kw:
                        ew._record_worker(layout, 6618, state="stopped_verified"))
    calls = []
    def verify(layout, worker, head, targets, test_venv, saved):
        calls.append(saved.get("verification_intent"))
        if len(calls) == 1:
            saved["verification_intent"] = {"protocol": "interrupted-test"}
            cycle._save(layout, saved)
            raise cycle.CycleError("interrupted verification")
        return {"head_sha": head, "targets": targets, "passed": True, "exit_code": 0}
    monkeypatch.setattr(cycle, "sandbox_verify", verify)
    monkeypatch.setattr(cycle, "ci_once", lambda *args: {"exit_code": 0})
    first = cycle.advance(layout, config, fetch=fetch, http=server)
    assert any(row.get("reason") == "interrupted verification" for row in first["results"])
    cycle.advance(layout, config, fetch=fetch, http=server)
    assert calls == [None, {"protocol": "interrupted-test"}]
    assert cycle._find(layout, 10, identity)["verification"]["passed"]


def test_unresolved_merge_does_not_block_other_pr(tmp_path, monkeypatch):
    layout, config, server = setup(tmp_path, monkeypatch)
    first = cycle.advance(layout, config, fetch=fetch, http=server)["results"][1]
    saved = cycle._find(layout, 10, first["identity"])
    saved["merge_intent"] = {
        "number": 10, "head_sha": HEAD, "governing_issue": 6618, "closing_issues": []}
    cycle._save(layout, saved)
    monkeypatch.setattr(cycle.closure, "_pr", lambda *args: {"state": "open", "merged_at": None, "head": {"sha": HEAD}})
    seen = []
    advance_one = cycle._advance_one
    def one(layout, pr, entry, **kwargs):
        if pr["number"] == 9:
            seen.append(9)
            return {"number": 9, "action": "review"}
        return advance_one(layout, pr, entry, **kwargs)
    monkeypatch.setattr(cycle, "_advance_one", one)
    result = cycle.advance(layout, [{**config[0], "number": 9}, config[0]], fetch=fetch, http=server)
    assert seen == [9]
    assert any(row["number"] == 10 and "unknown" in row.get("reason", "") for row in result["results"])
    assert cycle._find(layout, 10, first["identity"]) == saved


def test_displaced_branch_moves_to_replacement_then_original_owner_can_handoff(tmp_path, monkeypatch):
    f, now = _dispatcher_fixture(tmp_path, monkeypatch)
    source, old = f["source"], f["worktree"]
    original = agent_worktree.release_worktree(source, worktree=old, owner="session-original", now=now - 400)
    cycle.subprocess.run(["git", "-C", str(old), "switch", "-c", "codex/other"], check=True, capture_output=True)
    with pytest.raises(agent_worktree.WorktreeLifecycleError, match="replacement path"):
        agent_worktree.register_worktree(source, worktree=old, owner="other", now=now - 390)
    replacement, successor_path = tmp_path / "other-replacement", tmp_path / "successor"
    cycle.subprocess.run(["git", "-C", str(source), "worktree", "move", str(old), str(replacement)],
                         check=True, capture_output=True)
    agent_worktree.register_worktree(source, worktree=replacement, owner="other", now=now - 380)
    cycle.subprocess.run(["git", "-C", str(source), "worktree", "add", str(successor_path), "codex/example"],
                         check=True, capture_output=True)
    successor = agent_worktree.register_worktree(source, worktree=successor_path, owner="session-successor", now=now - 300)
    assert successor["prior_owner"]["path"] == str(old)
    f["events"][:] = [
        {"task_id": f["task_id"], "event_type": "task.claimed", "actor": "original", "lease_id": "old-lease",
         "timestamp": _event_time(now - 700), "payload": {"session": "session-original", "ttl_minutes": 90}},
        {"task_id": f["task_id"], "event_type": "task.released", "actor": "original", "lease_id": "old-lease",
         "timestamp": _event_time(now - 600), "payload": {"reason": "manual"}},
        {"task_id": f["task_id"], "event_type": "task.claimed", "actor": "successor", "lease_id": "new-lease",
         "timestamp": _event_time(now - 500), "payload": {"session": "session-successor", "ttl_minutes": 90}},
    ]
    f["task"].update(claimed_by="successor", lease_id="new-lease")
    f["lease"].update(holder="successor", lease_id="new-lease")
    f["entry"].update(owner_worktree=str(successor_path), claimant="successor", session="session-successor", lease_id="new-lease")
    f["worktree"] = successor_path
    record = _handoff(f, predecessor=("original", "session-original"), successor=("successor", "session-successor"),
                      registration=successor, prior_lease="old-lease", pickup_lease="new-lease")
    record["successor_acknowledgment"]["prior_worktree_release"].update(path=str(old), generation=original["generation"])
    f["comments"][:] = _prepare_and_pin(f, record, receipt_at=now - 650, ack_at=now - 100)
    assert _both_consumers(f)["owner"]["lease_id"] == "new-lease"


def test_continuous_reregistration_keeps_prior_pickup_window_for_both_consumers(tmp_path, monkeypatch):
    f, now = _dispatcher_fixture(tmp_path, monkeypatch)
    f["comments"].append(_pickup(7, now - 600, "original", "session-original", f["worktree"]))
    before = agent_worktree.load_lifecycle_records(f["source"])[str(f["worktree"])]
    renewed = agent_worktree.register_worktree(f["source"], worktree=f["worktree"],
                                               owner="session-original", now=now - 500)
    assert renewed["registered_at"] == now - 500
    assert renewed["authority_since"] == before["authority_since"]
    assert renewed["registration_epoch"] == before["registration_epoch"]
    assert _both_consumers(f)["owner"]["lease_id"] == "old-lease"


@pytest.mark.parametrize("interruption", ["expired", "released", "generation", "epoch-second"])
def test_reregistration_does_not_fill_continuity_gaps_at_either_consumer(tmp_path, monkeypatch, interruption):
    f = _native_authority_fixture(tmp_path, monkeypatch)
    now = int(time.time())
    path, source = f["worktree"], f["source"]
    ttl = 200 if interruption in ("expired", "epoch-second") else 3600
    first = agent_worktree.register_worktree(source, worktree=path, owner="session-original", now=now - 1000, ttl_seconds=ttl)
    f["events"][0]["timestamp"] = _event_time(now - 900)
    if interruption == "released":
        agent_worktree.release_worktree(source, worktree=path, owner="session-original", now=now - 800)
    if interruption == "generation":
        raw = cycle.subprocess.run(["git", "-C", str(path), "rev-parse", "--git-path", agent_worktree.GENERATION_MARKER],
                                   check=True, capture_output=True, text=True).stdout.strip()
        marker = cycle.Path(raw)
        if not marker.is_absolute():
            marker = path / marker
        marker.write_text("b" * 32 + "\n")
    pickup_at = now - (700 if interruption == "epoch-second" else 750)
    f["comments"].append(_pickup(7, pickup_at, "original", "session-original", path))
    renewed = agent_worktree.register_worktree(source, worktree=path, owner="session-original",
                                               now=now - 700 + (.5 if interruption == "epoch-second" else 0))
    assert renewed["registration_epoch"] != first["registration_epoch"]
    assert renewed["authority_since"] > pickup_at
    with pytest.raises(cycle.CycleError):
        cycle._add_transfer_review_context(f["layout"], f["entry"], {**f["pr"], "review_context": {}, "review_material": {}})
    with pytest.raises(cycle.CycleError):
        cycle.native_authority(f["layout"], f["pr"], f["entry"])


def test_changed_branch_cannot_reuse_pickup_epoch_at_either_consumer(tmp_path, monkeypatch):
    f, now = _dispatcher_fixture(tmp_path, monkeypatch)
    f["comments"].append(_pickup(7, now - 600, "original", "session-original", f["worktree"]))
    cycle.subprocess.run(["git", "-C", str(f["worktree"]), "switch", "-c", "codex/other"], check=True, capture_output=True)
    with pytest.raises(agent_worktree.WorktreeLifecycleError, match="replacement path"):
        agent_worktree.register_worktree(f["source"], worktree=f["worktree"], owner="session-original", now=now - 500)
    with pytest.raises(cycle.CycleError):
        cycle._add_transfer_review_context(f["layout"], f["entry"], {**f["pr"], "review_context": {}, "review_material": {}})
    with pytest.raises(cycle.CycleError):
        cycle.native_authority(f["layout"], f["pr"], f["entry"])


def test_ended_move_does_not_extend_authority_past_expiry(tmp_path, monkeypatch):
    f = _native_authority_fixture(tmp_path, monkeypatch)
    now, old, source = int(time.time()), f["worktree"], f["source"]
    agent_worktree.register_worktree(source, worktree=old, owner="session-original", now=now - 1000, ttl_seconds=200)
    f["events"][0]["timestamp"] = _event_time(now - 900)
    f["comments"].append(_pickup(7, now - 700, "original", "session-original", old))
    ended = agent_worktree.release_worktree(source, worktree=old, owner="session-original", now=now - 600)
    assert ended["authority_until"] == now - 800 and ended["released_at"] == now - 600
    moved = tmp_path / "moved"
    cycle.subprocess.run(["git", "-C", str(source), "worktree", "move", str(old), str(moved)],
                         check=True, capture_output=True)
    agent_worktree.register_worktree(source, worktree=moved, owner="session-original", now=now - 500)
    f["entry"]["owner_worktree"] = str(moved)
    with pytest.raises(cycle.CycleError):
        cycle._add_transfer_review_context(f["layout"], f["entry"], {**f["pr"], "review_context": {}, "review_material": {}})
    with pytest.raises(cycle.CycleError):
        cycle.native_authority(f["layout"], f["pr"], f["entry"])


def test_continuous_reregistration_does_not_erase_rival_at_either_consumer(tmp_path, monkeypatch):
    f, now = _dispatcher_fixture(tmp_path, monkeypatch)
    f["comments"].append(_pickup(7, now - 600, "rival", "session-rival", f["worktree"]))
    agent_worktree.register_worktree(f["source"], worktree=f["worktree"], owner="session-original", now=now - 500)
    with pytest.raises(cycle.CycleError):
        cycle._add_transfer_review_context(f["layout"], f["entry"], {**f["pr"], "review_context": {}, "review_material": {}})
    with pytest.raises(cycle.CycleError):
        cycle.native_authority(f["layout"], f["pr"], f["entry"])


def test_same_head_changed_contract_can_review_while_old_merge_is_fenced(tmp_path, monkeypatch):
    layout, config, server = setup(tmp_path, monkeypatch)
    first = cycle.advance(layout, config, fetch=fetch, http=server)["results"][1]
    old = cycle._find(layout, 10, first["identity"])
    old["merge_intent"] = {"number": 10, "head_sha": HEAD, "governing_issue": 6618, "closing_issues": []}
    cycle._save(layout, old)
    def complete(state):
        for row in state["dispatch_decisions"]:
            if row.get("operation_id") == first["operation_id"]:
                row["outcome"] = "completed"
        return state
    cycle.epic_run_state.update_epic_run_state(layout.run_id, root=layout.run_state_dir,
                                               expected_epic_issue_number=6615, updater=complete)
    monkeypatch.setattr(cycle.closure, "_pr", lambda *args: {"state": "open", "merged_at": None, "head": {"sha": HEAD}})
    started = []
    monkeypatch.setattr(cycle, "start_or_reconcile_review", lambda layout, worker, operation_id, pr, identity, entry, **kw:
                        started.append(identity) or {"id": "new", "status": "created"})
    monkeypatch.setattr(cycle, "merge_once", lambda *args, **kwargs: pytest.fail("unknown same-head merge must not repeat"))
    changed = [{**config[0], "verify_targets": ["tests/example.py::test_other"]}]
    result = cycle.advance(layout, changed, fetch=fetch, http=server)
    review = next(row for row in result["results"] if row.get("action") == "independent-review")
    assert review["identity"] != first["identity"] and started == [review["identity"]]
    assert cycle._find(layout, 10, first["identity"])["merge_intent"] == old["merge_intent"]


def test_same_head_new_identity_still_cannot_repeat_unknown_merge(tmp_path, monkeypatch):
    layout, config, server = setup(tmp_path, monkeypatch)
    saved = {"kind": "pr_cycle", "number": 10, "identity": "new-identity", "review_operation": "op",
             "review": {"verdict": "pass", "findings": []}, "public_report_conversation": "conversation",
             "execution_proof": {"operation_id": "op", "conversation_id": "conversation"},
             "verification": {"passed": True}}
    monkeypatch.setattr(cycle, "_find", lambda *args: saved)
    monkeypatch.setattr(cycle, "_mapping", lambda *args: {"conversation": {"id": "conversation"}})
    monkeypatch.setattr(cycle, "_add_transfer_review_context", lambda *args: None)
    monkeypatch.setattr(cycle, "_release_reviewer", lambda *args: None)
    monkeypatch.setattr(cycle.completion, "work_identity", lambda pr: "new-identity")
    monkeypatch.setattr(cycle.completion, "intake", lambda *args, **kwargs:
                        [{"action": "wait", "reason": "active or unknown writable owner"}])
    monkeypatch.setattr(cycle, "ci_once", lambda *args: {"exit_code": 0})
    monkeypatch.setattr(cycle, "merge_once", lambda *args: pytest.fail("must not repeat unknown merge"))
    pr = {"number": 10, "head_sha": HEAD, "body": "", "restrictions": [], "effect_outcomes": {}}
    result = cycle._advance_one(layout, pr, config[0], http=server, merge_obligations=[("old-identity", HEAD)])
    assert result["action"] == "wait" and "remains unknown" in result["reason"]


@pytest.mark.parametrize("intent", [
    {"container": "epicws-6615-verify-reviewer"},
    {"protocol": ew.LAUNCH_PROTOCOL, "worker": "reviewer", "container": "epicws-git-123456789abc"},
])
def test_other_identity_cannot_overlap_unresolved_worker_verification(tmp_path, monkeypatch, intent):
    layout, saved = _verify_setup(tmp_path, monkeypatch)
    cycle._save(layout, {"kind": "pr_cycle", "number": 10, "identity": "older", "verification_intent": intent})
    monkeypatch.setattr(cycle, "_command", lambda *args, **kwargs: pytest.fail("must not start another verification"))
    monkeypatch.setattr(ew, "_remove_owned", lambda *args, **kwargs:
                        (_ for _ in ()).throw(ew.EngineUnavailable("cannot prove old verification stopped")))
    with pytest.raises((cycle.CycleError, ew.EngineUnavailable)):
        cycle.sandbox_verify(layout, "reviewer", HEAD, ["tests/example.py"], "/approved/venv", saved)


def test_other_identity_settles_known_previous_worker_verification(tmp_path, monkeypatch):
    layout, saved = _verify_setup(tmp_path, monkeypatch)
    old_name, old_id = "epicws-git-123456789abc", "d" * 64
    old = {"kind": "pr_cycle", "number": 10, "identity": "older", "verification_intent": {
        "protocol": ew.LAUNCH_PROTOCOL, "worker": "reviewer", "container": old_name, "container_id": old_id}}
    cycle._save(layout, old)
    removed = []
    monkeypatch.setattr(ew, "_remove_owned", lambda name, labels, runner, *, cid=None: removed.append((name, cid)))
    def command(argv, *, timeout):
        if argv[1] == "create":
            assert removed == [(old_name, old_id)]
            return cycle.subprocess.CompletedProcess(argv, 0, "e" * 64, "")
        return cycle.subprocess.CompletedProcess(argv, 0, "1 passed in 1s", "")
    monkeypatch.setattr(cycle, "_command", command)
    assert cycle.sandbox_verify(layout, "reviewer", HEAD, ["tests/example.py"], "/approved/venv", saved)["passed"]
    assert cycle._find(layout, 10, "older")["verification_settled"] is True


def test_unresolved_verification_on_other_worker_does_not_block(tmp_path, monkeypatch):
    layout, saved = _verify_setup(tmp_path, monkeypatch)
    cycle._save(layout, {"kind": "pr_cycle", "number": 11, "identity": "other", "verification_intent": {
        "protocol": ew.LAUNCH_PROTOCOL, "worker": "other", "container": "epicws-git-123456789abc"}})
    monkeypatch.setattr(ew, "_remove_owned", lambda *args, **kwargs: None)
    def command(argv, *, timeout):
        if argv[1] == "create":
            return cycle.subprocess.CompletedProcess(argv, 0, "e" * 64, "")
        return cycle.subprocess.CompletedProcess(argv, 0, "1 passed in 1s", "")
    monkeypatch.setattr(cycle, "_command", command)
    assert cycle.sandbox_verify(layout, "reviewer", HEAD, ["tests/example.py"], "/approved/venv", saved)["passed"]
