"""Transfer-time registry proof through real Git and lifecycle writers."""
import copy
import json
import subprocess
import time
from unittest.mock import patch

import pytest

from tests.builderops.test_openhands_pr_cycle import (
    _authority_transfer_fixture, _event_time, _github_time, _handoff, _native_authority_fixture,
    _prepare_and_pin, _two_phase, cycle,
)


def _pickup(comment_id, at, agent, session, path, *, branch="codex/example", issue=6618):
    """An authenticated label-only fallback pickup comment as the wrapper posts it."""
    return {"id": comment_id, "user": {"login": "RasmusTho"}, "author_association": "OWNER",
            "created_at": _github_time(at), "updated_at": _github_time(at),
            "issue_url": f"https://api.github.com/repos/{cycle.completion.REPOSITORY}/issues/{issue}",
            "body": f"Pickup intent receipt: agent={agent} session={session} branch={branch} worktree={path} "
                    f"coordination_mode=github-label-only-fallback fallback_reason=dispatcher_db_missing issue={issue}"}


def _fallback_origin_body(path, agent="original", session="session-original", comment_id=6):
    return ("Governing-Issue: #6618\nFixes #6618\n"
            f"Pickup-Receipt: pickup-claim-complete issue=6618 branch=codex/example worktree={path} "
            "coordination_mode=github-label-only-fallback fallback_reason=dispatcher_db_missing "
            f"agent={agent} session={session} evidence=github-comment:{comment_id}")


def _fallback_transfer(f, *, extra=()):
    """Turn the canonical fixture into a pinned fallback-to-fallback transfer on this host."""
    now = f["now"]
    f["pr"]["body"] = f["live"]["body"] = _fallback_origin_body(f["worktree"])
    record = _handoff(f, predecessor=("original", "session-original"), successor=("successor", "session-successor"),
                      registration=f["new"], prior_lease=None, pickup_lease="unused")
    record["successor_acknowledgment"]["successor_pickup"] = {
        "mode": "github-label-only-fallback", "agent": "successor", "session": "session-successor",
        "evidence": "github-comment:7"}
    f["comments"][:] = [_pickup(6, now - 950, "original", "session-original", f["worktree"]),
                        _pickup(7, now - 500, "successor", "session-successor", f["worktree"]), *extra,
                        *_prepare_and_pin(f, record, receipt_at=now - 700, ack_at=now - 100)]
    f["entry"].update(coordination_mode="github-label-only-fallback", fallback_reason="dispatcher_db_missing",
                      coordination_evidence="github-comment:7")
    return record


def _prepare(f, *, at):
    pending = _two_phase(f["record"], receipt_at=f["now"] - 700, ack_at=f["now"] - 200)[0]
    readbacks = cycle.agent_worktree.prepare_transfer_registration(
        f["source"], worktree=f["worktree"], owner="session-successor", issue=6618, pr=10,
        pending_comment=pending, base_sha=f["live"]["base"]["sha"], workspace_root=f["layout"].root, now=at)
    f["record"]["successor_acknowledgment"].update(readbacks)
    return pending, readbacks


def _ack(f, *, at):
    return _two_phase(f["record"], receipt_at=f["now"] - 700, ack_at=at)[1]


def _pin(f, pending, ack, *, at):
    return cycle.agent_worktree.pin_transfer_registration(
        f["source"], worktree=f["worktree"], owner="session-successor", issue=6618, pr=10,
        pending_comment=pending, ack_comment=ack, workspace_root=f["layout"].root, now=at)


@pytest.mark.parametrize("gap", ["expiry", "release"])
def test_prepared_ack_cannot_be_pinned_across_registration_gap(tmp_path, monkeypatch, gap):
    f = _authority_transfer_fixture(tmp_path, monkeypatch, pin=False)
    now = f["now"]
    pending, _ = _prepare(f, at=now - 290)
    if gap == "expiry":
        cycle.agent_worktree.heartbeat_worktree(f["source"], worktree=f["worktree"],
                                               owner="session-successor", now=now - 280, ttl_seconds=20)
        cycle.agent_worktree.heartbeat_worktree(f["source"], worktree=f["worktree"],
                                               owner="session-successor", now=now - 100, ttl_seconds=3600)
    else:
        cycle.agent_worktree.release_worktree(f["source"], worktree=f["worktree"],
                                             owner="session-successor", now=now - 250)
        cycle.agent_worktree.register_worktree(f["source"], worktree=f["worktree"],
                                              owner="session-successor", now=now - 100, ttl_seconds=3600)
    ack = _ack(f, at=now - 200)
    with pytest.raises(cycle.agent_worktree.WorktreeLifecycleError, match="epoch"):
        _pin(f, pending, ack, at=now - 90)
    f["comments"][:] = [pending, ack]
    with pytest.raises(cycle.CycleError, match="unproved"):
        cycle.native_authority(f["layout"], f["pr"], f["entry"])


@pytest.mark.parametrize("defect", ["same_second", "before_readback", "partial_second", "changed_readback",
                                    "wrong_epoch", "edited_ack", "changed_pending"])
def test_pin_rejects_ambiguous_or_changed_evidence(tmp_path, monkeypatch, defect):
    f = _authority_transfer_fixture(tmp_path, monkeypatch, pin=False)
    now = f["now"]
    pending, _ = _prepare(f, at=now - 220)
    ack_at = now - (220 if defect == "same_second" else 230 if defect == "before_readback" else 200)
    ack = _ack(f, at=ack_at)
    if defect in {"changed_readback", "wrong_epoch"}:
        body = json.loads(ack["body"])
        acknowledgment = body["lifecycle_handoff_receipt.v1"]["successor_acknowledgment"]
        if defect == "changed_readback":
            acknowledgment["candidate_readback"]["head"] = "d" * 40
        else:
            acknowledgment["successor_registration"]["epoch"] = "f" * 32
        ack["body"] = json.dumps(body)
    if defect == "edited_ack":
        ack["updated_at"] = _ack(f, at=now - 199)["created_at"]
    if defect == "changed_pending":
        pending["body"] += " "
    with pytest.raises(cycle.agent_worktree.WorktreeLifecycleError):
        _pin(f, pending, ack, at=ack_at + (0.5 if defect == "partial_second" else 2))


def test_pin_is_immutable_and_same_session_reclaim_preserves_it(tmp_path, monkeypatch):
    f = _authority_transfer_fixture(tmp_path, monkeypatch, pin=False)
    now = f["now"]
    pending, readbacks = _prepare(f, at=now - 220)
    repeated = cycle.agent_worktree.prepare_transfer_registration(
        f["source"], worktree=f["worktree"], owner="session-successor", issue=6618, pr=10,
        pending_comment=pending, base_sha=f["live"]["base"]["sha"], workspace_root=f["layout"].root, now=now - 210)
    assert repeated == readbacks
    ack = _ack(f, at=now - 200)
    proof = _pin(f, pending, ack, at=now - 198)
    assert _pin(f, pending, ack, at=now - 197) == proof
    edited = copy.deepcopy(ack)
    edited["body"] += " "
    with pytest.raises(cycle.agent_worktree.WorktreeLifecycleError, match="cannot be replaced"):
        _pin(f, pending, edited, at=now - 196)
    continuous = cycle.agent_worktree.heartbeat_worktree(
        f["source"], worktree=f["worktree"], owner="session-successor", now=now - 190)
    assert continuous["registration_epoch"] == proof["epoch"]
    cycle.agent_worktree.release_worktree(f["source"], worktree=f["worktree"],
                                         owner="session-successor", now=now - 180)
    reclaimed = cycle.agent_worktree.register_worktree(f["source"], worktree=f["worktree"],
                                                      owner="session-successor", now=now - 170)
    assert reclaimed["registration_epoch"] != proof["epoch"]
    assert reclaimed["transfer_registration"] == proof
    f["comments"][:] = [pending, ack]
    assert cycle.native_authority(f["layout"], f["pr"], f["entry"])["owner"]["lease_id"] == "new-lease"


def test_prepare_refuses_dirty_or_changed_checkout(tmp_path, monkeypatch):
    f = _authority_transfer_fixture(tmp_path, monkeypatch, pin=False)
    (f["worktree"] / "app" / "example.py").write_text("uncommitted\n")
    with pytest.raises(cycle.agent_worktree.WorktreeLifecycleError, match="dirty"):
        _prepare(f, at=f["now"] - 220)


def test_prepare_refuses_model_workspace_before_git(tmp_path, monkeypatch):
    f = _authority_transfer_fixture(tmp_path, monkeypatch, pin=False)
    pending = _two_phase(f["record"], receipt_at=f["now"] - 700, ack_at=f["now"] - 200)[0]
    monkeypatch.setattr(cycle.agent_worktree, "_worktree_identity", lambda *args: pytest.fail("model checkout was inspected"))
    with pytest.raises(cycle.agent_worktree.WorktreeLifecycleError, match="outside model workspaces"):
        cycle.agent_worktree.prepare_transfer_registration(
            f["source"], worktree=f["worktree"], owner="session-successor", issue=6618, pr=10,
            pending_comment=pending, base_sha=f["live"]["base"]["sha"],
            workspace_root=f["worktree"], now=f["now"] - 220)


def test_prepared_transfer_rechecks_registry_after_git_readback(tmp_path, monkeypatch):
    f = _authority_transfer_fixture(tmp_path, monkeypatch, pin=False)
    real = cycle.agent_worktree._transfer_candidate
    def racing(*args, **kwargs):
        candidate = real(*args, **kwargs)
        cycle.agent_worktree.heartbeat_worktree(f["source"], worktree=f["worktree"],
                                               owner="session-successor", now=f["now"] - 240)
        return candidate
    monkeypatch.setattr(cycle.agent_worktree, "_transfer_candidate", racing)
    with pytest.raises(cycle.agent_worktree.WorktreeLifecycleError, match="changed"):
        _prepare(f, at=f["now"] - 220)


def test_current_review_receives_transfer_delta_and_dirty_candidate_refuses(tmp_path, monkeypatch):
    f = _authority_transfer_fixture(tmp_path, monkeypatch)
    pr = {**f["pr"], "review_context": {}, "review_material": {}}
    cycle._add_transfer_review_context(f["layout"], f["entry"], pr)
    original = pr["review_context"]["transfer_delta_digest"]
    (f["worktree"] / "app" / "example.py").write_text("refactored implementation\n")
    subprocess.run(["git", "-C", str(f["worktree"]), "add", "app/example.py"], check=True)
    subprocess.run(["git", "-C", str(f["worktree"]), "-c", "user.name=Test", "-c",
                    "user.email=test@example.invalid", "commit", "-m", "continue work"], check=True, capture_output=True)
    head = subprocess.run(["git", "-C", str(f["worktree"]), "rev-parse", "HEAD"],
                          check=True, capture_output=True, text=True).stdout.strip()
    f["pr"]["head_sha"] = f["live"]["head"]["sha"] = head
    pr.update(head_sha=head, review_context={}, review_material={})
    cycle._add_transfer_review_context(f["layout"], f["entry"], pr)
    assert pr["review_context"]["transfer_delta_digest"] != original
    assert "-candidate" in pr["review_material"]["transfer_to_current"]["diff"]
    assert "assess that delta for dropped" in cycle._review_prompt(pr, "identity", [])
    assert cycle.native_authority(f["layout"], f["pr"], f["entry"])["head_sha"] == head
    (f["worktree"] / "untracked.txt").write_text("dirty")
    with pytest.raises(cycle.CycleError, match="dirty"):
        cycle._add_transfer_review_context(f["layout"], f["entry"], pr)


def test_real_coordinator_cli_prepares_and_pins_authenticated_readbacks(tmp_path, monkeypatch, capsys):
    f = _authority_transfer_fixture(tmp_path, monkeypatch, pin=False)
    now = f["now"]
    pending = _two_phase(f["record"], receipt_at=now - 700, ack_at=now - 200)[0]
    observations = {41: pending}
    monkeypatch.setattr(cycle.agent_worktree, "_read_github_transfer_comment",
                        lambda comment_id, *, cwd: observations[comment_id])
    monkeypatch.setattr(cycle.agent_worktree.time, "time", lambda: now - 220)
    common = ["--cwd", str(f["source"]), "prepare-transfer", "--worktree", str(f["worktree"]),
              "--owner", "session-successor", "--workspace-root", str(f["layout"].root),
              "--issue", "6618", "--pr", "10", "--pending-comment-id", "41"]
    assert cycle.agent_worktree.main([*common, "--base-sha", f["live"]["base"]["sha"]]) == 0
    readbacks = json.loads(capsys.readouterr().out)
    f["record"]["successor_acknowledgment"].update(readbacks)
    observations[42] = _ack(f, at=now - 200)
    monkeypatch.setattr(cycle.agent_worktree.time, "time", lambda: now - 198)
    pin_args = ["--cwd", str(f["source"]), "pin-transfer", "--worktree", str(f["worktree"]),
                "--owner", "session-successor", "--workspace-root", str(f["layout"].root), "--issue", "6618", "--pr", "10",
                "--pending-comment-id", "41", "--ack-comment-id", "42"]
    assert cycle.agent_worktree.main(pin_args) == 0
    assert json.loads(capsys.readouterr().out)["state"] == "pinned"
    assert cycle.agent_worktree.main(pin_args) == 0
    assert json.loads(capsys.readouterr().out)["ack_comment_id"] == 42


def test_rewritten_history_cannot_use_historical_transfer(tmp_path, monkeypatch):
    f = _authority_transfer_fixture(tmp_path, monkeypatch)
    worktree = str(f["worktree"])
    subprocess.run(["git", "-C", worktree, "switch", "--orphan", "rewritten"], check=True, capture_output=True)
    (f["worktree"] / "unrelated.txt").write_text("replacement\n")
    subprocess.run(["git", "-C", worktree, "add", "unrelated.txt"], check=True)
    subprocess.run(["git", "-C", worktree, "-c", "user.name=Test", "-c",
                    "user.email=test@example.invalid", "commit", "-m", "rewrite"], check=True, capture_output=True)
    subprocess.run(["git", "-C", worktree, "branch", "-D", "codex/example"], check=True, capture_output=True)
    subprocess.run(["git", "-C", worktree, "branch", "-m", "codex/example"], check=True)
    head = subprocess.run(["git", "-C", worktree, "rev-parse", "HEAD"],
                          check=True, capture_output=True, text=True).stdout.strip()
    f["pr"]["head_sha"] = f["live"]["head"]["sha"] = head
    with pytest.raises(cycle.CycleError, match="candidate readback is unavailable"):
        cycle.native_authority(f["layout"], f["pr"], f["entry"])


def test_unknown_predecessor_history_cannot_be_pinned_by_fresh_pickup(tmp_path, monkeypatch):
    f = _authority_transfer_fixture(tmp_path, monkeypatch, pin=False)
    now = f["now"]
    cycle.agent_worktree.release_worktree(f["source"], worktree=f["worktree"],
                                         owner="session-successor", now=now - 250)
    third = cycle.agent_worktree.register_worktree(f["source"], worktree=f["worktree"],
                                                   owner="session-third", now=now - 240)
    assert "transfer_registration" in third["prior_owner"]
    assert third["prior_owner"]["transfer_registration"] is None
    record = copy.deepcopy(f["record"])
    record["current_lifecycle_owner"] = {"agent": "successor", "session": "session-successor"}
    record["successor"] = {"agent": "third", "session": "session-third"}
    pending = _two_phase(record, receipt_at=now - 260, ack_at=now - 100)[0]
    with pytest.raises(cycle.agent_worktree.WorktreeLifecycleError, match="history is unproved"):
        cycle.agent_worktree.prepare_transfer_registration(
            f["source"], worktree=f["worktree"], owner="session-third", issue=6618, pr=10,
            pending_comment=pending, base_sha=f["live"]["base"]["sha"], workspace_root=f["layout"].root, now=now - 110)


def test_moved_successor_can_transfer_again_with_real_prior_mapping(tmp_path, monkeypatch):
    from tests.builderops.test_openhands_pr_cycle import _event_time, _handoff, _prepare_and_pin

    f = _authority_transfer_fixture(tmp_path, monkeypatch)
    now = f["now"]
    old = f["worktree"]
    cycle.agent_worktree.release_worktree(f["source"], worktree=old, owner="session-successor", now=now - 80)
    moved = old.parent / "moved-successor"
    subprocess.run(["git", "-C", str(f["source"]), "worktree", "move", str(old), str(moved)], check=True)
    cycle.agent_worktree.register_worktree(f["source"], worktree=moved, owner="session-successor", now=now - 70)
    f["events"].extend([
        {"task_id": f["task_id"], "event_type": "task.released", "actor": "successor", "lease_id": "new-lease",
         "timestamp": _event_time(now - 58), "payload": {"reason": "manual"}},
        {"task_id": f["task_id"], "event_type": "task.claimed", "actor": "third", "lease_id": "third-lease",
         "timestamp": _event_time(now - 57), "payload": {"session": "session-third", "ttl_minutes": 90}},
    ])
    cycle.agent_worktree.release_worktree(f["source"], worktree=moved, owner="session-successor", now=now - 55)
    third = cycle.agent_worktree.register_worktree(f["source"], worktree=moved, owner="session-third", now=now - 50)
    f["worktree"] = moved
    f["entry"].update(owner_worktree=str(moved), claimant="third", session="session-third", lease_id="third-lease")
    f["task"].update(claimed_by="third", lease_id="third-lease")
    f["lease"].update(holder="third", lease_id="third-lease")
    latest = _handoff(f, predecessor=("successor", "session-successor"), successor=("third", "session-third"),
                      registration=third, prior_lease="new-lease", pickup_lease="third-lease")
    f["comments"].extend(_prepare_and_pin(f, latest, receipt_at=now - 65, ack_at=now - 20, first_id=51))
    assert cycle.native_authority(f["layout"], f["pr"], f["entry"])["owner"]["lease_id"] == "third-lease"
    registry = cycle.agent_worktree._default_registry_path(f["source"])
    data = json.loads(registry.read_text())
    data["worktrees"][str(old)]["generation"] = "f" * 32
    registry.write_text(json.dumps(data))
    with pytest.raises(cycle.CycleError):
        cycle.native_authority(f["layout"], f["pr"], f["entry"])


def test_same_session_fallback_to_dispatcher_keeps_existing_transfer(tmp_path, monkeypatch):
    from tests.builderops.test_openhands_pr_cycle import _event_time, _github_time, _handoff, _prepare_and_pin

    f = _authority_transfer_fixture(tmp_path, monkeypatch, pin=False)
    now = f["now"]
    def pickup(comment_id, at, agent, session):
        return {"id": comment_id, "user": {"login": "RasmusTho"}, "author_association": "OWNER",
                "created_at": _github_time(at), "updated_at": _github_time(at),
                "issue_url": f"https://api.github.com/repos/{cycle.completion.REPOSITORY}/issues/6618",
                "body": f"Pickup intent receipt: agent={agent} session={session} branch=codex/example worktree={f['worktree']} "
                        "coordination_mode=github-label-only-fallback fallback_reason=dispatcher_db_missing issue=6618"}
    original, current = pickup(6, now - 950, "original", "session-original"), pickup(7, now - 500, "successor", "session-successor")
    f["pr"]["body"] = f["live"]["body"] = ("Governing-Issue: #6618\nFixes #6618\n"
        f"Pickup-Receipt: pickup-claim-complete issue=6618 branch=codex/example worktree={f['worktree']} "
        "coordination_mode=github-label-only-fallback fallback_reason=dispatcher_db_missing "
        "agent=original session=session-original evidence=github-comment:6")
    record = _handoff(f, predecessor=("original", "session-original"), successor=("successor", "session-successor"),
                      registration=f["new"], prior_lease=None, pickup_lease="unused")
    record["successor_acknowledgment"]["successor_pickup"] = {
        "mode": "github-label-only-fallback", "agent": "successor", "session": "session-successor", "evidence": "github-comment:7"}
    f["comments"][:] = [original, current, *_prepare_and_pin(f, record, receipt_at=now - 700, ack_at=now - 100)]
    f["entry"].update(coordination_mode="github-label-only-fallback", fallback_reason="dispatcher_db_missing",
                      coordination_evidence="github-comment:7")
    assert cycle.native_authority(f["layout"], f["pr"], f["entry"])["owner"]["mode"] == "github-label-only-fallback"
    f["events"][:] = [{"task_id": f["task_id"], "event_type": "task.claimed", "actor": "successor",
                       "lease_id": "resumed-dispatcher", "timestamp": _event_time(now - 50),
                       "payload": {"session": "session-successor", "ttl_minutes": 90}}]
    f["task"].update(claimed_by="successor", lease_id="resumed-dispatcher")
    f["lease"].update(holder="successor", lease_id="resumed-dispatcher")
    f["entry"].update(coordination_mode="dispatcher-backed", lease_id="resumed-dispatcher")
    assert cycle.native_authority(f["layout"], f["pr"], f["entry"])["owner"]["lease_id"] == "resumed-dispatcher"
    rival = pickup(8, now - 75, "rival", "session-rival")
    f["comments"].insert(0, rival)
    with pytest.raises(cycle.CycleError, match="conflicting fallback pickup"):
        cycle.native_authority(f["layout"], f["pr"], f["entry"])


@pytest.mark.parametrize("defect", ["remote_session", "remote_expiry", "remote_release", "remote_path", "unknown_history", "missing_pickup", "later_rival", "early_successor"])
def test_remote_dispatcher_to_fallback_requires_exact_reconciled_readbacks(tmp_path, monkeypatch, defect):
    from tests.builderops.test_openhands_pr_cycle import _event_time, _github_time, _handoff, _native_authority_fixture, _prepare_and_pin

    f = _native_authority_fixture(tmp_path, monkeypatch)
    now = int(cycle.time.time())
    new = cycle.agent_worktree.register_worktree(f["source"], worktree=f["worktree"],
                                                 owner="session-successor", now=now - 300)
    remote = "/remote/mac/previous-worktree"
    f["entry"].update(claimant="successor", session="session-successor", coordination_mode="github-label-only-fallback",
                      fallback_reason="dispatcher_db_missing", coordination_evidence="github-comment:7")
    fallback = {"id": 7, "user": {"login": "RasmusTho"}, "author_association": "OWNER",
                "created_at": _github_time(now - 500), "updated_at": _github_time(now - 500),
                "issue_url": f"https://api.github.com/repos/{cycle.completion.REPOSITORY}/issues/6618",
                "body": f"Pickup intent receipt: agent=successor session=session-successor branch=codex/example worktree={f['worktree']} "
                        "coordination_mode=github-label-only-fallback fallback_reason=dispatcher_db_missing issue=6618"}
    record = _handoff(f, predecessor=("original", "session-original"), successor=("successor", "session-successor"),
                      registration=new, prior_lease="old-lease", pickup_lease="unused")
    record["predecessor_registration"] = {"path": remote, "owner": "session-original", "branch": "codex/example",
        "generation": "f" * 32, "status": "active", "observed_at": now - 800, "expires_at": now + 1200}
    record["predecessor_dispatcher"] = {"task_id": f["task_id"], "lease_id": "old-lease", "holder": "original",
        "session": "session-original", "claimed_at": _event_time(now - 900), "observed_at": _event_time(now - 800),
        "expires_at": _event_time(now + 1200), "history_reconciled": True}
    ack = record["successor_acknowledgment"]
    ack["successor_pickup"] = {"mode": "github-label-only-fallback", "agent": "successor", "session": "session-successor",
                                "evidence": "github-comment:7"}
    ack["prior_worktree_release"].update(path=remote, generation="f" * 32, released_at=now - 400)
    ack["prior_coordination_release"]["released_at"] = _event_time(now - 600)
    if defect == "remote_session":
        record["predecessor_dispatcher"]["session"] = "wrong"
    elif defect == "remote_expiry":
        record["predecessor_dispatcher"]["expires_at"] = _event_time(now - 700)
    elif defect == "remote_release":
        ack["prior_coordination_release"]["lease_id"] = "rival"
    elif defect == "remote_path":
        ack["prior_worktree_release"]["path"] = "/remote/different"
    elif defect == "unknown_history":
        record["predecessor_dispatcher"]["history_reconciled"] = False
    if defect == "unknown_history":
        with pytest.raises(cycle.agent_worktree.WorktreeLifecycleError, match="unreconciled"):
            _prepare_and_pin(f, record, receipt_at=now - 700, ack_at=now - 100)
        return
    comments = _prepare_and_pin(f, record, receipt_at=now - 700, ack_at=now - 100)
    f["comments"][:] = comments if defect == "missing_pickup" else [fallback, *comments]
    if defect == "later_rival":
        rival = {**fallback, "id": 8, "created_at": _github_time(now - 650), "updated_at": _github_time(now - 650),
                 "body": fallback["body"].replace("agent=successor", "agent=rival").replace("session=session-successor", "session=session-rival")}
        f["comments"].insert(0, rival)
    if defect == "early_successor":
        f["comments"].insert(0, {**fallback, "id": 8, "created_at": _github_time(now - 650), "updated_at": _github_time(now - 650)})
    with pytest.raises(cycle.CycleError):
        cycle.native_authority(f["layout"], f["pr"], f["entry"])


@pytest.mark.parametrize("reference,accepted", [(None, False), (6, False), (8, True)])
def test_multiple_predecessor_pickups_require_latest_explicit_reference(tmp_path, monkeypatch, reference, accepted):
    from tests.builderops.test_openhands_pr_cycle import _event_time, _github_time, _handoff, _prepare_and_pin

    f = _authority_transfer_fixture(tmp_path, monkeypatch, pin=False)
    now = f["now"]
    def pickup(comment_id, at):
        return {"id": comment_id, "user": {"login": "RasmusTho"}, "author_association": "OWNER",
                "created_at": _github_time(at), "updated_at": _github_time(at),
                "issue_url": f"https://api.github.com/repos/{cycle.completion.REPOSITORY}/issues/6618",
                "body": f"Pickup intent receipt: agent=original session=session-original branch=codex/example worktree={f['worktree']} "
                        "coordination_mode=github-label-only-fallback fallback_reason=dispatcher_db_missing issue=6618"}
    f["pr"]["body"] = f["live"]["body"] = ("Governing-Issue: #6618\nFixes #6618\n"
        f"Pickup-Receipt: pickup-claim-complete issue=6618 branch=codex/example worktree={f['worktree']} "
        "coordination_mode=github-label-only-fallback fallback_reason=dispatcher_db_missing "
        "agent=original session=session-original evidence=github-comment:6")
    f["events"][:] = [{"task_id": f["task_id"], "event_type": "task.claimed", "actor": "successor",
                       "lease_id": "new-lease", "timestamp": _event_time(now - 500),
                       "payload": {"session": "session-successor", "ttl_minutes": 90}}]
    record = _handoff(f, predecessor=("original", "session-original"), successor=("successor", "session-successor"),
                      registration=f["new"], prior_lease=None, pickup_lease="new-lease")
    if reference is not None:
        record["predecessor_pickup_comment_id"] = reference
    f["comments"][:] = [pickup(6, now - 1100), pickup(8, now - 950),
                         *_prepare_and_pin(f, record, receipt_at=now - 700, ack_at=now - 100)]
    if accepted:
        assert cycle.native_authority(f["layout"], f["pr"], f["entry"])["owner"]["lease_id"] == "new-lease"
    else:
        with pytest.raises(cycle.CycleError, match="fallback predecessor"):
            cycle.native_authority(f["layout"], f["pr"], f["entry"])


@pytest.mark.parametrize("field", ["epoch", "ack_digest", "pending_digest", "generation"])
def test_tampered_pinned_registry_anchor_is_not_authority(tmp_path, monkeypatch, field):
    f = _authority_transfer_fixture(tmp_path, monkeypatch)
    registry = cycle.agent_worktree._default_registry_path(f["source"])
    data = json.loads(registry.read_text())
    proof = data["worktrees"][str(f["worktree"])]["transfer_registration"]
    proof[field] = ("f" * 64 if field.endswith("digest") else "f" * 32)
    registry.write_text(json.dumps(data))
    with pytest.raises(cycle.CycleError):
        cycle.native_authority(f["layout"], f["pr"], f["entry"])


def test_transfer_keeps_immutable_base_when_main_advances_after_readback(tmp_path, monkeypatch):
    f = _authority_transfer_fixture(tmp_path, monkeypatch, pin=False)
    now = f["now"]
    pending, readbacks = _prepare(f, at=now - 220)
    old_base = readbacks["candidate_readback"]["base_sha"]
    (f["source"] / "main-only.txt").write_text("another main commit\n")
    subprocess.run(["git", "-C", str(f["source"]), "add", "main-only.txt"], check=True)
    subprocess.run(["git", "-C", str(f["source"]), "-c", "user.name=Test", "-c",
                    "user.email=test@example.invalid", "commit", "-m", "advance main"], check=True, capture_output=True)
    current_base = subprocess.run(["git", "-C", str(f["source"]), "rev-parse", "HEAD"],
                                  check=True, capture_output=True, text=True).stdout.strip()
    assert current_base != old_base
    ack = _ack(f, at=now - 200)
    proof = _pin(f, pending, ack, at=now - 198)
    assert proof["candidate_readback"]["base_sha"] == old_base
    f["comments"][:] = [pending, ack]
    f["live"]["base"]["sha"] = current_base
    assert cycle.native_authority(f["layout"], f["pr"], f["entry"])["head_sha"] == f["head"]


def _commit(path, text, message):
    (path / "app" / "example.py").write_text(text)
    subprocess.run(["git", "-C", str(path), "add", "app/example.py"], check=True, capture_output=True)
    subprocess.run(["git", "-C", str(path), "-c", "user.name=Test", "-c", "user.email=test@example.invalid",
                    "commit", "-m", message], check=True, capture_output=True)
    return subprocess.run(["git", "-C", str(path), "rev-parse", "HEAD"],
                          check=True, capture_output=True, text=True).stdout.strip()


def _first_fallback_hop(tmp_path, monkeypatch, *, second_ttl):
    """Pinned S1 -> S2 fallback transfer on one checkout, S2 still registered."""
    f = _native_authority_fixture(tmp_path, monkeypatch)
    now = int(time.time())
    repo, path = f["source"], f["worktree"]
    f["pr"]["body"] = f["live"]["body"] = _fallback_origin_body(path)
    cycle.agent_worktree.register_worktree(repo, worktree=path, owner="session-original", now=now - 2000, ttl_seconds=3600)
    cycle.agent_worktree.release_worktree(repo, worktree=path, owner="session-original", now=now - 1600)
    second = cycle.agent_worktree.register_worktree(repo, worktree=path, owner="session-second",
                                                    now=now - 1500, ttl_seconds=second_ttl)
    record = _handoff(f, predecessor=("original", "session-original"), successor=("second", "session-second"),
                      registration=second, prior_lease=None, pickup_lease="unused")
    record["successor_acknowledgment"]["successor_pickup"] = {
        "mode": "github-label-only-fallback", "agent": "second", "session": "session-second",
        "evidence": "github-comment:7"}
    f["comments"][:] = [_pickup(6, now - 2100, "original", "session-original", path),
                        _pickup(7, now - 1700, "second", "session-second", path),
                        *_prepare_and_pin(f, record, receipt_at=now - 1900, ack_at=now - 1400)]
    f["entry"].update(claimant="second", session="session-second", coordination_mode="github-label-only-fallback",
                      fallback_reason="dispatcher_db_missing", coordination_evidence="github-comment:7")
    with patch.object(cycle.time, "time", return_value=now - 1300):
        assert cycle.native_authority(f["layout"], f["pr"], f["entry"])["owner"]["caller_session"] == "session-second"
    proof = cycle.agent_worktree.load_lifecycle_records(repo)[str(path)]["transfer_registration"]
    assert proof["state"] == "pinned"
    f.update(now=now, second=second, second_proof=proof)
    return f


@pytest.mark.parametrize("returning,ended", [("original", "expired"), ("third", "expired"), ("original", "complete")])
def test_expired_successor_is_retained_when_an_earlier_owner_returns(tmp_path, monkeypatch, returning, ended):
    f = _first_fallback_hop(tmp_path, monkeypatch, second_ttl=500 if ended == "expired" else 3600)
    now, repo, path = f["now"], f["source"], f["worktree"]
    if ended == "complete":
        cycle.agent_worktree.complete_worktree(repo, worktree=path, owner="session-second", now=now - 960)
    session = f"session-{returning}"
    row = cycle.agent_worktree.register_worktree(repo, worktree=path, owner=session, now=now - 900, ttl_seconds=3600)
    # Neither expiry nor completion is a release, and the later owner's anchor
    # survives the generic registration of any other session.
    assert row["prior_owner"]["owner"] == "session-second" and row["prior_owner"]["released_at"] is None
    assert row["prior_owner"]["transfer_registration"] == f["second_proof"]
    assert "transfer_registration" not in row
    f["comments"].append(_pickup(8, now - 950, returning, session, path))
    f["entry"].update(claimant=returning, session=session, coordination_evidence="github-comment:8")
    with pytest.raises(cycle.CycleError, match="transfer registration is unproved"):
        cycle.native_authority(f["layout"], f["pr"], f["entry"])
    head = _commit(path, "candidate\ncontinued without a return transfer\n", "continue after unproved takeover")
    f["pr"]["head_sha"] = f["live"]["head"]["sha"] = head
    with pytest.raises(cycle.CycleError, match="transfer registration is unproved"):
        cycle.native_authority(f["layout"], f["pr"], f["entry"])
    with pytest.raises(cycle.CycleError, match="transfer registration is unproved"):
        cycle._add_transfer_review_context(f["layout"], f["entry"], {**f["pr"], "review_context": {}, "review_material": {}})
    # A return handoff cannot be prepared from an owner that never released.
    back = _handoff(f, predecessor=("second", "session-second"), successor=(returning, session),
                    registration=row, prior_lease=None, pickup_lease="unused")
    back["unpublished_candidate_head"] = head
    pending = _two_phase(back, receipt_at=now - 920, ack_at=now - 100, first_id=51)[0]
    with pytest.raises(cycle.agent_worktree.WorktreeLifecycleError, match="ended without release"):
        cycle.agent_worktree.prepare_transfer_registration(
            repo, worktree=path, owner=session, issue=6618, pr=10, pending_comment=pending,
            base_sha=f["live"]["base"]["sha"], workspace_root=f["layout"].root, now=now - 110)


def test_released_successor_can_return_authority_to_an_earlier_owner(tmp_path, monkeypatch):
    f = _first_fallback_hop(tmp_path, monkeypatch, second_ttl=3600)
    now, repo, path = f["now"], f["source"], f["worktree"]
    back = _handoff(f, predecessor=("second", "session-second"), successor=("original", "session-original"),
                    registration=f["second"], prior_lease=None, pickup_lease="unused")
    back["successor_acknowledgment"]["successor_pickup"] = {
        "mode": "github-label-only-fallback", "agent": "original", "session": "session-original",
        "evidence": "github-comment:8"}
    f["comments"].append(_pickup(8, now - 980, "original", "session-original", path))
    cycle.agent_worktree.release_worktree(repo, worktree=path, owner="session-second", now=now - 950)
    returned = cycle.agent_worktree.register_worktree(repo, worktree=path, owner="session-original",
                                                      now=now - 900, ttl_seconds=3600)
    assert returned["prior_owner"]["owner"] == "session-second" and returned["prior_owner"]["released_at"] == now - 950
    f["comments"].extend(_prepare_and_pin(f, back, receipt_at=now - 1000, ack_at=now - 100, first_id=51))
    f["entry"].update(claimant="original", session="session-original", coordination_evidence="github-comment:8")
    # The returning session's own older pickup is history the later owner resolved.
    assert cycle.native_authority(f["layout"], f["pr"], f["entry"])["owner"]["caller_session"] == "session-original"
    head = _commit(path, "candidate\nlegitimate fix after return\n", "continue after return transfer")
    f["pr"]["head_sha"] = f["live"]["head"]["sha"] = head
    material = {**f["pr"], "review_context": {}, "review_material": {}}
    cycle._add_transfer_review_context(f["layout"], f["entry"], material)
    assert "legitimate fix after return" in material["review_material"]["transfer_to_current"]["diff"]
    assert cycle.native_authority(f["layout"], f["pr"], f["entry"])["head_sha"] == head


def _remote_after_local_history(tmp_path, monkeypatch, *, released_before=5000, moved=True):
    """Older TARS owner, reconciled Mac dispatcher predecessor, then a TARS fallback pickup.

    ``released_before`` is how long before now the older TARS owner released its
    row; ``None`` lets that registration expire without a release.
    """
    f = _native_authority_fixture(tmp_path, monkeypatch)
    now = int(time.time())
    repo, old = f["source"], f["worktree"]
    oldreg = cycle.agent_worktree.register_worktree(repo, worktree=old, owner="session-historical",
                                                    now=now - 5600, ttl_seconds=600 if released_before is None else 3600)
    if released_before is not None:
        cycle.agent_worktree.release_worktree(repo, worktree=old, owner="session-historical", now=now - released_before)
    current_path = old
    if moved:
        current_path = old.parent / "new-approved-checkout"
        subprocess.run(["git", "-C", str(repo), "worktree", "move", str(old), str(current_path)], check=True)
    current = cycle.agent_worktree.register_worktree(repo, worktree=current_path, owner="session-successor",
                                                     now=now - 3300, ttl_seconds=7200)
    assert current["prior_owner"]["owner"] == "session-historical"
    f["worktree"] = current_path
    f["entry"].update(owner_worktree=str(current_path), claimant="successor", session="session-successor",
                      coordination_mode="github-label-only-fallback", fallback_reason="dispatcher_db_missing",
                      coordination_evidence="github-comment:7")
    f["pr"]["body"] = f["live"]["body"] = _fallback_origin_body(old, agent="historical", session="session-historical")
    remote = "/remote/mac/previous-worktree"
    record = _handoff(f, predecessor=("remote", "session-remote"), successor=("successor", "session-successor"),
                      registration=current, prior_lease="remote-lease", pickup_lease="unused")
    record["predecessor_registration"] = {"path": remote, "owner": "session-remote", "branch": "codex/example",
                                          "generation": "f" * 32, "status": "active",
                                          "observed_at": now - 3800, "expires_at": now + 1200}
    record["predecessor_dispatcher"] = {"task_id": f["task_id"], "lease_id": "remote-lease", "holder": "remote",
                                        "session": "session-remote", "claimed_at": _event_time(now - 3900),
                                        "observed_at": _event_time(now - 3800), "expires_at": _event_time(now + 1200),
                                        "history_reconciled": True}
    ack = record["successor_acknowledgment"]
    ack["successor_pickup"] = {"mode": "github-label-only-fallback", "agent": "successor",
                               "session": "session-successor", "evidence": "github-comment:7"}
    ack["prior_worktree_release"].update(path=remote, generation="f" * 32, released_at=now - 3400)
    ack["prior_coordination_release"]["released_at"] = _event_time(now - 3600)
    # The earlier authenticated TARS -> Mac hop; the coordinator reconciled it remotely.
    earlier = _handoff(f, predecessor=("historical", "session-historical"), successor=("remote", "session-remote"),
                       registration={"generation": "f" * 32}, prior_lease=None, pickup_lease="remote-previous-lease")
    earlier["writable_worktree"] = remote
    earlier["successor_acknowledgment"]["prior_worktree_release"].update(path=str(old), generation=oldreg["generation"])
    earlier["successor_acknowledgment"]["successor_registration"].update(path=remote)
    f["comments"][:] = [_pickup(6, now - 5700, "historical", "session-historical", old),
                        *_two_phase(earlier, receipt_at=now - 4300, ack_at=now - 4000, first_id=31),
                        _pickup(7, now - 3500, "successor", "session-successor", current_path)]
    f.update(now=now, record=record, current=current)
    return f


def test_older_local_owner_is_history_for_a_reconciled_remote_predecessor(tmp_path, monkeypatch):
    f = _remote_after_local_history(tmp_path, monkeypatch)
    now, repo, path = f["now"], f["source"], f["worktree"]
    f["comments"].extend(_prepare_and_pin(f, f["record"], receipt_at=now - 3700, ack_at=now - 3100))
    proof = cycle.agent_worktree.load_lifecycle_records(repo)[str(path)]["transfer_registration"]
    # The released local row is history, not the recorded transfer predecessor.
    assert proof["state"] == "pinned" and "predecessor_registration" not in proof
    authority = lambda: cycle.native_authority(f["layout"], f["pr"], f["entry"])
    assert authority()["owner"]["caller_session"] == "session-successor"
    # Local history that overlaps the remote claim or never released is
    # unresolved, even under an otherwise valid pinned remote transfer.
    registry = cycle.agent_worktree._default_registry_path(repo)
    original = registry.read_text()
    for tampered in ({"released_at": now - 3850, "authority_until": now - 3850},
                     {"released_at": None, "authority_until": None}):
        data = json.loads(original)
        data["worktrees"][str(path)]["prior_owner"].update(tampered)
        registry.write_text(json.dumps(data))
        with pytest.raises(cycle.CycleError, match="unreleased or overlaps the remote predecessor"):
            authority()
    registry.write_text(original)
    # A later transfer on this host verifies the remote hop from its pinned comments.
    nxt = _handoff(f, predecessor=("successor", "session-successor"), successor=("next", "session-next"),
                   registration=f["current"], prior_lease=None, pickup_lease="unused")
    nxt["successor_acknowledgment"]["successor_pickup"] = {
        "mode": "github-label-only-fallback", "agent": "next", "session": "session-next",
        "evidence": "github-comment:9"}
    f["comments"].append(_pickup(9, now - 1900, "next", "session-next", path))
    cycle.agent_worktree.release_worktree(repo, worktree=path, owner="session-successor", now=now - 1800)
    later = cycle.agent_worktree.register_worktree(repo, worktree=path, owner="session-next",
                                                   now=now - 1700, ttl_seconds=7200)
    assert later["prior_owner"]["transfer_registration"] == proof
    f["comments"].extend(_prepare_and_pin(f, nxt, receipt_at=now - 2000, ack_at=now - 1000, first_id=51))
    f["entry"].update(claimant="next", session="session-next", coordination_evidence="github-comment:9")
    assert authority()["owner"]["caller_session"] == "session-next"


@pytest.mark.parametrize("local_end", ["overlap", "expired"])
def test_local_history_overlapping_or_unreleased_refuses_remote_preparation(tmp_path, monkeypatch, local_end):
    f = _remote_after_local_history(tmp_path, monkeypatch, released_before=3850 if local_end == "overlap" else None,
                                    moved=local_end == "overlap")
    if local_end == "expired":
        assert f["current"]["prior_owner"]["released_at"] is None
    with pytest.raises(cycle.agent_worktree.WorktreeLifecycleError, match="unreleased or overlaps"):
        _prepare_and_pin(f, f["record"], receipt_at=f["now"] - 3700, ack_at=f["now"] - 3100)


@pytest.mark.parametrize("agent,branch,elsewhere", [("rival", "codex/example", True),
                                                    ("original", "codex/other", False),
                                                    ("original", "codex/example", True)])
def test_later_pickup_by_another_claimant_with_the_same_session_refuses(tmp_path, monkeypatch, agent, branch, elsewhere):
    f = _authority_transfer_fixture(tmp_path, monkeypatch, pin=False)
    now = f["now"]
    f["pr"]["body"] = f["live"]["body"] = _fallback_origin_body(f["worktree"])
    f["events"][:] = [{"task_id": f["task_id"], "event_type": "task.claimed", "actor": "successor",
                       "lease_id": "new-lease", "timestamp": _event_time(now - 500),
                       "payload": {"session": "session-successor", "ttl_minutes": 90}}]
    record = _handoff(f, predecessor=("original", "session-original"), successor=("successor", "session-successor"),
                      registration=f["new"], prior_lease=None, pickup_lease="new-lease")
    path = "/other-host/different-checkout" if elsewhere else f["worktree"]
    f["comments"][:] = [_pickup(6, now - 1100, "original", "session-original", f["worktree"]),
                        _pickup(8, now - 900, agent, "session-original", path, branch=branch),
                        *_prepare_and_pin(f, record, receipt_at=now - 700, ack_at=now - 100)]
    authority = lambda: cycle.native_authority(f["layout"], f["pr"], f["entry"])
    # Session equality is not the predecessor's identity.
    with pytest.raises(cycle.CycleError, match="conflicting fallback pickup"):
        authority()
    # The same claim for an unrelated Issue does not compete with this transfer.
    f["comments"][1] = _pickup(8, now - 900, agent, "session-original", path, branch=branch, issue=6619)
    assert authority()["owner"]["lease_id"] == "new-lease"


@pytest.mark.parametrize("rival", [("rival", "session-rival", "/elsewhere/rival"),
                                   ("rival", "session-original", "/elsewhere/rival"),
                                   ("successor", "session-successor", "/elsewhere/rival")])
def test_competing_pickup_before_acknowledgment_survives_a_mode_change(tmp_path, monkeypatch, rival):
    f = _authority_transfer_fixture(tmp_path, monkeypatch, pin=False)
    now = f["now"]
    _fallback_transfer(f, extra=[_pickup(9, now - 800, *rival)])
    authority = lambda: cycle.native_authority(f["layout"], f["pr"], f["entry"])
    with pytest.raises(cycle.CycleError, match="conflicting fallback pickup"):
        authority()
    # The historical transfer is rechecked after the same session moves to the dispatcher.
    f["events"][:] = [{"task_id": f["task_id"], "event_type": "task.claimed", "actor": "successor",
                       "lease_id": "resumed-dispatcher", "timestamp": _event_time(now - 50),
                       "payload": {"session": "session-successor", "ttl_minutes": 90}}]
    f["task"].update(claimed_by="successor", lease_id="resumed-dispatcher")
    f["lease"].update(holder="successor", lease_id="resumed-dispatcher")
    f["entry"].update(coordination_mode="dispatcher-backed", lease_id="resumed-dispatcher")
    with pytest.raises(cycle.CycleError, match="conflicting fallback pickup"):
        authority()


@pytest.mark.parametrize("later", [None, "unregistered-path", "other-agent", "other-branch"])
def test_current_owner_pickups_after_transfer_need_exact_registered_identity(tmp_path, monkeypatch, later):
    f = _authority_transfer_fixture(tmp_path, monkeypatch, pin=False)
    now, old = f["now"], f["worktree"]
    _fallback_transfer(f)
    authority = lambda: cycle.native_authority(f["layout"], f["pr"], f["entry"])
    assert authority()["owner"]["mode"] == "github-label-only-fallback"
    cycle.agent_worktree.release_worktree(f["source"], worktree=old, owner="session-successor", now=now - 80)
    moved = old.parent / "moved-successor"
    subprocess.run(["git", "-C", str(f["source"]), "worktree", "move", str(old), str(moved)], check=True)
    cycle.agent_worktree.register_worktree(f["source"], worktree=moved, owner="session-successor", now=now - 70)
    if later is not None:
        agent, branch, path = {"unregistered-path": ("successor", "codex/example", "/elsewhere/unregistered"),
                               "other-agent": ("rival", "codex/example", moved),
                               "other-branch": ("successor", "codex/other", moved)}[later]
        f["comments"].append(_pickup(10, now - 60, agent, "session-successor", path, branch=branch))
    f["comments"].append(_pickup(11, now - 50, "successor", "session-successor", moved))
    f["entry"].update(owner_worktree=str(moved), coordination_evidence="github-comment:11")
    if later is None:
        # An exact same-owner pickup at a registry-proven moved path continues the owner.
        assert authority()["worktree_owner"]["path"] == str(moved)
    else:
        with pytest.raises(cycle.CycleError, match="conflicting fallback pickup"):
            authority()


@pytest.mark.parametrize("mode", ["fallback", "dispatcher"])
@pytest.mark.parametrize("agent,branch,other_path", [
    ("rival", "codex/example", False),
    ("original", "codex/example", True),
    ("original", "codex/other", False),
])
def test_original_claimant_cannot_erase_a_rival_by_renewing(tmp_path, monkeypatch, mode, agent, branch, other_path):
    f = _native_authority_fixture(tmp_path, monkeypatch)
    now, path = int(time.time()), f["worktree"]
    cycle.agent_worktree.register_worktree(f["source"], worktree=path, owner="session-original", now=now - 1000)
    f["pr"]["body"] = f["live"]["body"] = _fallback_origin_body(path)
    f["comments"][:] = [_pickup(6, now - 900, "original", "session-original", path)]
    f["entry"].update(coordination_mode="github-label-only-fallback", fallback_reason="dispatcher_db_missing",
                      coordination_evidence="github-comment:6")
    assert cycle.native_authority(f["layout"], f["pr"], f["entry"])["owner"]["caller_agent"] == "original"
    rival_path = "/elsewhere/rival" if other_path else path
    f["comments"].append(_pickup(7, now - 700, agent, "session-original", rival_path, branch=branch))
    if mode == "fallback":
        f["comments"].append(_pickup(8, now - 500, "original", "session-original", path))
        f["entry"]["coordination_evidence"] = "github-comment:8"
    else:
        f["events"][:] = [{"task_id": f["task_id"], "event_type": "task.claimed", "actor": "original",
                           "lease_id": "old-lease", "timestamp": _event_time(now - 500),
                           "payload": {"session": "session-original", "ttl_minutes": 90}}]
        f["entry"]["coordination_mode"] = "dispatcher-backed"
    with pytest.raises(cycle.CycleError, match="conflicting fallback pickup"):
        cycle._add_transfer_review_context(f["layout"], f["entry"], {**f["pr"], "review_context": {}, "review_material": {}})
    with pytest.raises(cycle.CycleError, match="conflicting fallback pickup"):
        cycle.native_authority(f["layout"], f["pr"], f["entry"])


def test_original_fallback_identity_includes_agent(tmp_path, monkeypatch):
    f = _native_authority_fixture(tmp_path, monkeypatch)
    now, path = int(time.time()), f["worktree"]
    cycle.agent_worktree.register_worktree(f["source"], worktree=path, owner="session-original", now=now - 1000)
    f["pr"]["body"] = f["live"]["body"] = _fallback_origin_body(path)
    f["comments"][:] = [_pickup(6, now - 900, "original", "session-original", path),
                        _pickup(7, now - 700, "rival", "session-original", path)]
    f["entry"].update(claimant="rival", coordination_mode="github-label-only-fallback",
                      fallback_reason="dispatcher_db_missing", coordination_evidence="github-comment:7")
    with pytest.raises(cycle.CycleError, match="claimant"):
        cycle.native_authority(f["layout"], f["pr"], f["entry"])
    with pytest.raises(cycle.CycleError, match="claimant"):
        cycle._add_transfer_review_context(f["layout"], f["entry"], {**f["pr"], "review_context": {}, "review_material": {}})


def test_unlinked_registration_does_not_make_a_rival_path_authoritative(tmp_path, monkeypatch):
    f = _native_authority_fixture(tmp_path, monkeypatch)
    now, path = int(time.time()), f["worktree"]
    cycle.agent_worktree.register_worktree(f["source"], worktree=path, owner="session-original", now=now - 1000)
    row = cycle.agent_worktree.load_lifecycle_records(f["source"])[str(path)]
    comments = [_pickup(6, now - 900, "original", "session-original", path),
                _pickup(7, now - 700, "original", "session-original", "/elsewhere/unlinked")]
    origin, at = cycle._pickup_origin(_fallback_origin_body(path), issue=6618, closing=[6618],
                                      branch="codex/example", comments=comments)
    unrelated = {**row, "path": "/elsewhere/unlinked", "status": "released", "released_at": now - 600}
    with pytest.raises(cycle.CycleError, match="conflicting fallback pickup"):
        cycle._claimant_history(registration=row, records={str(path): row, unrelated["path"]: unrelated},
            comments=comments, issue_comments=comments, events=None, origin=origin, origin_at=at,
            issue=6618, pr_number=10, branch="codex/example", entry=f["entry"])


def test_original_owner_renewal_and_mode_change_preserve_authority(tmp_path, monkeypatch):
    f = _native_authority_fixture(tmp_path, monkeypatch)
    now, path = int(time.time()), f["worktree"]
    cycle.agent_worktree.register_worktree(f["source"], worktree=path, owner="session-original", now=now - 1000)
    f["pr"]["body"] = f["live"]["body"] = _fallback_origin_body(path)
    f["comments"][:] = [_pickup(6, now - 900, "original", "session-original", path),
                        _pickup(8, now - 700, "original", "session-original", path)]
    f["entry"].update(coordination_mode="github-label-only-fallback", fallback_reason="dispatcher_db_missing",
                      coordination_evidence="github-comment:8")
    assert cycle.native_authority(f["layout"], f["pr"], f["entry"])["owner"]["caller_session"] == "session-original"
    f["events"][:] = [{"task_id": f["task_id"], "event_type": "task.claimed", "actor": "original",
                       "lease_id": "old-lease", "timestamp": _event_time(now - 500),
                       "payload": {"session": "session-original", "ttl_minutes": 90}}]
    f["entry"]["coordination_mode"] = "dispatcher-backed"
    cycle._add_transfer_review_context(f["layout"], f["entry"], {**f["pr"], "review_context": {}, "review_material": {}})
    assert cycle.native_authority(f["layout"], f["pr"], f["entry"])["owner"]["lease_id"] == "old-lease"


def test_legacy_recovery_then_transfer_preserves_original_claim_history(tmp_path, monkeypatch):
    f = _authority_transfer_fixture(tmp_path, monkeypatch, pin=False)
    now = f["now"]
    f["events"][0]["payload"] = {"ttl_minutes": 90}
    f["events"][1]["lease_id"] = "fresh-lease"
    f["events"][1:1] = [
        {"task_id": f["task_id"], "event_type": "task.released", "actor": "original", "lease_id": "old-lease",
         "timestamp": _event_time(now - 850), "payload": {"reason": "manual"}},
        {"task_id": f["task_id"], "event_type": "task.claimed", "actor": "original", "lease_id": "fresh-lease",
         "timestamp": _event_time(now - 800), "payload": {"session": "session-original", "ttl_minutes": 90}},
    ]
    record = _handoff(f, predecessor=("original", "session-original"), successor=("successor", "session-successor"),
                      registration=f["new"], prior_lease="fresh-lease", pickup_lease="new-lease")
    f["comments"][:] = _prepare_and_pin(f, record, receipt_at=now - 700, ack_at=now - 100)
    cycle._add_transfer_review_context(f["layout"], f["entry"], {**f["pr"], "review_context": {}, "review_material": {}})
    assert cycle.native_authority(f["layout"], f["pr"], f["entry"])["owner"]["lease_id"] == "new-lease"
    f["events"][1]["actor"] = "other"
    with pytest.raises(cycle.CycleError, match="session history is unbound"):
        cycle.native_authority(f["layout"], f["pr"], f["entry"])


def test_original_owner_can_continue_across_multiple_proven_moves(tmp_path, monkeypatch):
    f = _native_authority_fixture(tmp_path, monkeypatch)
    now, first, source = int(time.time()), f["worktree"], f["source"]
    cycle.agent_worktree.register_worktree(source, worktree=first, owner="session-original", now=now - 1000)
    f["pr"]["body"] = f["live"]["body"] = _fallback_origin_body(first)
    f["comments"][:] = [_pickup(6, now - 900, "original", "session-original", first)]
    cycle.agent_worktree.release_worktree(source, worktree=first, owner="session-original", now=now - 800)
    second = first.parent / "second-path"
    subprocess.run(["git", "-C", str(source), "worktree", "move", str(first), str(second)], check=True)
    cycle.agent_worktree.register_worktree(source, worktree=second, owner="session-original", now=now - 700)
    f["comments"].append(_pickup(7, now - 650, "original", "session-original", second))
    cycle.agent_worktree.release_worktree(source, worktree=second, owner="session-original", now=now - 600)
    third = first.parent / "third-path"
    subprocess.run(["git", "-C", str(source), "worktree", "move", str(second), str(third)], check=True)
    cycle.agent_worktree.register_worktree(source, worktree=third, owner="session-original", now=now - 500)
    f["comments"].append(_pickup(8, now - 450, "original", "session-original", third))
    f["entry"].update(owner_worktree=str(third), coordination_mode="github-label-only-fallback",
                      fallback_reason="dispatcher_db_missing", coordination_evidence="github-comment:8")
    cycle._add_transfer_review_context(f["layout"], f["entry"], {**f["pr"], "review_context": {}, "review_material": {}})
    assert cycle.native_authority(f["layout"], f["pr"], f["entry"])["worktree_owner"]["path"] == str(third)


def test_pickup_in_acknowledgment_second_has_ambiguous_order(tmp_path, monkeypatch):
    f = _first_fallback_hop(tmp_path, monkeypatch, second_ttl=3600)
    f["comments"].append(_pickup(9, f["now"] - 1400, "second", "session-second", f["worktree"]))
    f["entry"]["coordination_evidence"] = "github-comment:9"
    with pytest.raises(cycle.CycleError, match="ordering at acknowledgment is ambiguous"):
        cycle.native_authority(f["layout"], f["pr"], f["entry"])
    with pytest.raises(cycle.CycleError, match="ordering at acknowledgment is ambiguous"):
        cycle._add_transfer_review_context(f["layout"], f["entry"], {**f["pr"], "review_context": {}, "review_material": {}})


def test_pickup_in_release_second_is_not_a_live_registration_proof(tmp_path, monkeypatch):
    f = _first_fallback_hop(tmp_path, monkeypatch, second_ttl=3600)
    f["comments"].append(_pickup(9, f["now"] - 1600, "original", "session-original", f["worktree"]))
    with pytest.raises(cycle.CycleError, match="conflicting fallback pickup"):
        cycle._add_transfer_review_context(f["layout"], f["entry"], {**f["pr"], "review_context": {}, "review_material": {}})
    with pytest.raises(cycle.CycleError):
        cycle.native_authority(f["layout"], f["pr"], f["entry"])


@pytest.mark.parametrize("rival", [None, ("rival", "session-second", False, "codex/example"),
                                  ("second", "session-second", True, "codex/example"),
                                  ("second", "session-second", False, "codex/other"),
                                  ("original", "session-original", False, "codex/example")])
def test_claimant_conflict_survives_return_and_another_real_transfer(tmp_path, monkeypatch, rival):
    f = _first_fallback_hop(tmp_path, monkeypatch, second_ttl=3600)
    now, path = f["now"], f["worktree"]
    if rival:
        agent, session, other_path, branch = rival
        f["comments"].append(_pickup(9, now - 1250, agent, session,
                                      "/elsewhere/rival" if other_path else path, branch=branch))
    f["comments"].append(_pickup(10, now - 1150, "second", "session-second", path))
    back = _handoff(f, predecessor=("second", "session-second"), successor=("original", "session-original"),
                    registration=f["second"], prior_lease=None, pickup_lease="unused")
    back["predecessor_pickup_comment_id"] = 10
    back["successor_acknowledgment"]["successor_pickup"] = {
        "mode": "github-label-only-fallback", "agent": "original", "session": "session-original",
        "evidence": "github-comment:8"}
    f["comments"].append(_pickup(8, now - 980, "original", "session-original", path))
    cycle.agent_worktree.release_worktree(f["source"], worktree=path, owner="session-second", now=now - 950)
    returned = cycle.agent_worktree.register_worktree(f["source"], worktree=path, owner="session-original",
                                                      now=now - 900, ttl_seconds=3600)
    f["comments"].extend(_prepare_and_pin(f, back, receipt_at=now - 1000, ack_at=now - 800, first_id=51))
    f["entry"].update(claimant="original", session="session-original", coordination_evidence="github-comment:8")
    if rival:
        with pytest.raises(cycle.CycleError, match="conflicting fallback pickup"):
            cycle.native_authority(f["layout"], f["pr"], f["entry"])
    else:
        assert cycle.native_authority(f["layout"], f["pr"], f["entry"])["owner"]["caller_session"] == "session-original"
    third = _handoff(f, predecessor=("original", "session-original"), successor=("third", "session-third"),
                     registration=returned, prior_lease=None, pickup_lease="unused")
    third["predecessor_pickup_comment_id"] = 8
    third["successor_acknowledgment"]["successor_pickup"] = {
        "mode": "github-label-only-fallback", "agent": "third", "session": "session-third",
        "evidence": "github-comment:11"}
    f["comments"].append(_pickup(11, now - 680, "third", "session-third", path))
    cycle.agent_worktree.release_worktree(f["source"], worktree=path, owner="session-original", now=now - 650)
    cycle.agent_worktree.register_worktree(f["source"], worktree=path, owner="session-third", now=now - 600)
    f["comments"].extend(_prepare_and_pin(f, third, receipt_at=now - 700, ack_at=now - 500, first_id=61))
    f["entry"].update(claimant="third", session="session-third", coordination_evidence="github-comment:11")
    material = {**f["pr"], "review_context": {}, "review_material": {}}
    if rival:
        with pytest.raises(cycle.CycleError, match="conflicting fallback pickup"):
            cycle._add_transfer_review_context(f["layout"], f["entry"], material)
        with pytest.raises(cycle.CycleError, match="conflicting fallback pickup"):
            cycle.native_authority(f["layout"], f["pr"], f["entry"])
    else:
        cycle._add_transfer_review_context(f["layout"], f["entry"], material)
        assert cycle.native_authority(f["layout"], f["pr"], f["entry"])["owner"]["caller_session"] == "session-third"
        # A later pin without the retained earlier proof cannot certify that
        # the earlier successor was ever authorized, even when no rival exists.
        registry = cycle.agent_worktree._default_registry_path(f["source"])
        data = json.loads(registry.read_text())
        row = data["worktrees"][str(path)]
        for snapshot in (row["prior_owner"], row["transfer_registration"]["predecessor_registration"]):
            snapshot["transfer_registration"]["predecessor_registration"].pop("transfer_registration")
        registry.write_text(json.dumps(data))
        with pytest.raises(cycle.CycleError, match="earlier claimant transfer is unavailable"):
            cycle.native_authority(f["layout"], f["pr"], f["entry"])


@pytest.mark.parametrize("return_to_old", [False, True])
def test_moved_owner_can_transfer_after_path_reuse(tmp_path, monkeypatch, return_to_old):
    f = _authority_transfer_fixture(tmp_path, monkeypatch)
    now, old, source = f["now"], f["worktree"], f["source"]
    cycle.agent_worktree.release_worktree(source, worktree=old, owner="session-successor", now=now - 80)
    moved = old.parent / "moved-successor"
    subprocess.run(["git", "-C", str(source), "worktree", "move", str(old), str(moved)], check=True)
    moved_row = cycle.agent_worktree.register_worktree(source, worktree=moved, owner="session-successor", now=now - 70)
    f["events"].extend([
        {"task_id": f["task_id"], "event_type": "task.released", "actor": "successor", "lease_id": "new-lease",
         "timestamp": _event_time(now - 58), "payload": {"reason": "manual"}},
        {"task_id": f["task_id"], "event_type": "task.claimed", "actor": "third", "lease_id": "third-lease",
         "timestamp": _event_time(now - 57), "payload": {"session": "session-third", "ttl_minutes": 90}},
    ])
    cycle.agent_worktree.release_worktree(source, worktree=moved, owner="session-successor", now=now - 55)
    current = moved
    if return_to_old:
        subprocess.run(["git", "-C", str(source), "worktree", "move", str(moved), str(old)], check=True)
        current = old
    third = cycle.agent_worktree.register_worktree(source, worktree=current, owner="session-third", now=now - 50)
    assert third["prior_owner"]["previous_registration"]["path"] == str(old)
    f["worktree"] = current
    f["entry"].update(owner_worktree=str(current), claimant="third", session="session-third", lease_id="third-lease")
    f["task"].update(claimed_by="third", lease_id="third-lease")
    f["lease"].update(holder="third", lease_id="third-lease")
    latest = _handoff(f, predecessor=("successor", "session-successor"), successor=("third", "session-third"),
                      registration=third, prior_lease="new-lease", pickup_lease="third-lease")
    latest["successor_acknowledgment"]["prior_worktree_release"].update(path=str(moved), generation=moved_row["generation"])
    f["comments"].extend(_prepare_and_pin(f, latest, receipt_at=now - 65, ack_at=now - 20, first_id=51))
    assert cycle.native_authority(f["layout"], f["pr"], f["entry"])["owner"]["lease_id"] == "third-lease"


def test_same_owner_can_move_away_and_return_with_proven_pickups(tmp_path, monkeypatch):
    f = _authority_transfer_fixture(tmp_path, monkeypatch, pin=False)
    now, old, source = f["now"], f["worktree"], f["source"]
    _fallback_transfer(f)
    cycle.agent_worktree.release_worktree(source, worktree=old, owner="session-successor", now=now - 80)
    moved = old.parent / "moved-successor"
    subprocess.run(["git", "-C", str(source), "worktree", "move", str(old), str(moved)], check=True)
    cycle.agent_worktree.register_worktree(source, worktree=moved, owner="session-successor", now=now - 70)
    f["comments"].append(_pickup(10, now - 65, "successor", "session-successor", moved))
    cycle.agent_worktree.release_worktree(source, worktree=moved, owner="session-successor", now=now - 60)
    subprocess.run(["git", "-C", str(source), "worktree", "move", str(moved), str(old)], check=True)
    returned = cycle.agent_worktree.register_worktree(source, worktree=old, owner="session-successor", now=now - 50)
    assert returned["previous_registration"]["path"] == str(moved)
    f["comments"].append(_pickup(11, now - 40, "successor", "session-successor", old))
    f["entry"]["coordination_evidence"] = "github-comment:11"
    material = {**f["pr"], "review_context": {}, "review_material": {}}
    cycle._add_transfer_review_context(f["layout"], f["entry"], material)
    assert cycle.native_authority(f["layout"], f["pr"], f["entry"])["owner"]["caller_session"] == "session-successor"
    cycle.agent_worktree.release_worktree(source, worktree=old, owner="session-successor", now=now - 35)
    subprocess.run(["git", "-C", str(source), "worktree", "move", str(old), str(moved)], check=True)
    cycle.agent_worktree.register_worktree(source, worktree=moved, owner="session-successor", now=now - 30)
    f["comments"].append(_pickup(12, now - 20, "successor", "session-successor", moved))
    f["entry"].update(owner_worktree=str(moved), coordination_evidence="github-comment:12")
    assert cycle.native_authority(f["layout"], f["pr"], f["entry"])["worktree_owner"]["path"] == str(moved)


def test_coordinator_cli_pins_nested_history_without_erasing_conflict(tmp_path, monkeypatch, capsys):
    f = _first_fallback_hop(tmp_path, monkeypatch, second_ttl=3600)
    now, path = f["now"], f["worktree"]
    f["comments"].append(_pickup(10, now - 1150, "second", "session-second", path))
    back = _handoff(f, predecessor=("second", "session-second"), successor=("original", "session-original"),
                    registration=f["second"], prior_lease=None, pickup_lease="unused")
    back["predecessor_pickup_comment_id"] = 10
    back["successor_acknowledgment"]["successor_pickup"] = {
        "mode": "github-label-only-fallback", "agent": "original", "session": "session-original",
        "evidence": "github-comment:8"}
    f["comments"].append(_pickup(8, now - 980, "original", "session-original", path))
    cycle.agent_worktree.release_worktree(f["source"], worktree=path, owner="session-second", now=now - 950)
    cycle.agent_worktree.register_worktree(f["source"], worktree=path, owner="session-original", now=now - 900)
    pending = _two_phase(back, receipt_at=now - 1000, ack_at=now - 800, first_id=51)[0]
    observations = {51: pending}
    monkeypatch.setattr(cycle.agent_worktree, "_read_github_transfer_comment",
                        lambda comment_id, *, cwd: observations[comment_id])
    monkeypatch.setattr(cycle.agent_worktree.time, "time", lambda: now - 810)
    common = ["--cwd", str(f["source"]), "prepare-transfer", "--worktree", str(path),
              "--owner", "session-original", "--workspace-root", str(f["layout"].root),
              "--issue", "6618", "--pr", "10", "--pending-comment-id", "51"]
    assert cycle.agent_worktree.main([*common, "--base-sha", f["live"]["base"]["sha"]]) == 0
    back["successor_acknowledgment"].update(json.loads(capsys.readouterr().out))
    observations[52] = _two_phase(back, receipt_at=now - 1000, ack_at=now - 800, first_id=51)[1]
    monkeypatch.setattr(cycle.agent_worktree.time, "time", lambda: now - 798)
    pin_args = ["--cwd", str(f["source"]), "pin-transfer", "--worktree", str(path),
                "--owner", "session-original", "--workspace-root", str(f["layout"].root),
                "--issue", "6618", "--pr", "10", "--pending-comment-id", "51", "--ack-comment-id", "52"]
    authentic_ack = observations[52]
    observations[52] = copy.deepcopy(authentic_ack)
    observations[52]["user"]["login"] = "unauthorized"
    assert cycle.agent_worktree.main(pin_args) == 1
    assert "unauthenticated" in json.loads(capsys.readouterr().out)["error"]
    assert cycle.agent_worktree.load_lifecycle_records(f["source"])[str(path)]["transfer_registration"]["state"] == "prepared"
    observations[52] = authentic_ack
    assert cycle.agent_worktree.main(pin_args) == 0
    proof = json.loads(capsys.readouterr().out)
    assert proof["predecessor_registration"]["transfer_registration"] == f["second_proof"]
    f["comments"].extend([pending, observations[52]])
    f["entry"].update(claimant="original", session="session-original", coordination_evidence="github-comment:8")
    assert cycle.native_authority(f["layout"], f["pr"], f["entry"])["owner"]["caller_session"] == "session-original"
    f["comments"].append(_pickup(9, now - 1250, "rival", "session-second", path))
    with pytest.raises(cycle.CycleError, match="conflicting fallback pickup"):
        cycle.native_authority(f["layout"], f["pr"], f["entry"])
