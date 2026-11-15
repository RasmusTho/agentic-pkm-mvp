"""Operator worktree receipts are distinct from predecessor handoffs."""
import copy
import hashlib
import json
import subprocess
from datetime import datetime, timezone

import pytest

from scripts import agent_worktree as worktrees


def _git(repo, *args):
    return subprocess.check_output(["git", "-C", str(repo), *args], text=True).strip()


def _comment(body, ident, at):
    timestamp = datetime.fromtimestamp(at, timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    return {"id": ident, "user": {"login": "RasmusTho"}, "author_association": "OWNER",
            "created_at": timestamp, "updated_at": timestamp,
            "issue_url": "https://api.github.com/repos/RasmusTho/agentic-pkm-mvp/issues/6636",
            "body": json.dumps({"operator_reconciliation.v1": body})}


@pytest.fixture
def fixture(tmp_path):
    repo = tmp_path / "repo"
    repo.mkdir()
    _git(repo, "init", "-b", "main")
    _git(repo, "config", "user.email", "test@example.com")
    _git(repo, "config", "user.name", "test")
    (repo / "file").write_text("data\n")
    _git(repo, "add", "file")
    _git(repo, "commit", "-m", "init")
    checkout = tmp_path / "checkout"
    _git(repo, "worktree", "add", "-b", "codex/example", str(checkout))
    repo = checkout
    old = worktrees.register_worktree(repo, worktree=repo, owner="old", now=9000, ttl_seconds=100)
    registry = worktrees._default_registry_path(repo)
    history = worktrees._branch_history_digest(worktrees._locked_lifecycle_snapshot(registry), "codex/example")
    head = _git(repo, "rev-parse", "HEAD")
    receipt = {"issue": 6636, "branch": "codex/example", "writable_worktree": str(repo),
               "successor": {"session": "new"}, "predecessor_registration": old,
               "branch_history_digest": history, "base": head, "unpublished_candidate_head": head,
               "changed_files": [], "registration": {**{k: old[k] for k in ("path", "branch", "generation", "owner")},
               "history_digest": hashlib.sha256(json.dumps(old, sort_keys=True).encode()).hexdigest()},
               "candidate": {"path": str(repo), "branch": "codex/example", "generation": old["generation"],
                             "head": head, "tree": _git(repo, "rev-parse", "HEAD^{tree}"),
                             "status_digest": hashlib.sha256(b"").hexdigest()}}
    return repo, registry, history, receipt, head, tmp_path / "model"


def _prepare(f):
    repo, _, history, receipt, head, workspace = f
    return worktrees.prepare_operator_registration(repo, worktree=repo, owner="new", issue=6636,
             pending_comment=_comment(receipt, 1, 9500), base_sha=head, workspace_root=workspace,
             expected_branch_history_digest=history, now=9600)


def _begin(f, *, at=9601):
    repo, _, _, receipt, _, workspace = f
    return worktrees.begin_operator_ack(repo, worktree=repo, owner="new", issue=6636,
             pending_comment=_comment(receipt, 1, 9500), workspace_root=workspace, now=at)


def _pin(f, readbacks, *, at=9702):
    repo, registry, _, receipt, _, workspace = f
    row = worktrees._locked_lifecycle_snapshot(registry)[str(repo)]
    intent = row["operator_registration"].get("ack_intent")
    if intent is None:
        intent = _begin(f)
    acknowledgment = {**copy.deepcopy(readbacks), "ack_attempt_id": intent["attempt_id"]}
    ack = {**copy.deepcopy(receipt), "successor_acknowledgment": acknowledgment}
    return worktrees.pin_operator_registration(repo, worktree=repo, owner="new", issue=6636,
             pending_comment=_comment(receipt, 1, 9500), ack_comment=_comment(ack, 2, 9700),
             workspace_root=workspace, now=at)


def test_operator_registration_preserves_old_record_and_pins_ack(fixture):
    f = fixture
    readbacks = _prepare(f)
    row = worktrees._locked_lifecycle_snapshot(f[1])[str(f[0])]
    assert row["operator_registration"]["state"] == "prepared"
    assert row["operator_registration"]["predecessor"] == f[3]["predecessor_registration"]
    assert row["prior_owner"]["released_at"] is None
    proof = _pin(f, readbacks)
    assert proof["state"] == "pinned"
    assert proof["epoch"] == readbacks["successor_registration"]["epoch"]
    assert _pin(f, readbacks, at=9703) == proof
    with pytest.raises(worktrees.WorktreeLifecycleError):
        _prepare(f)


def test_operator_refuses_changed_history_candidate_and_wrong_ack(fixture):
    f = fixture
    old = copy.deepcopy(f[3])
    f[3]["registration"]["history_digest"] = "0" * 64
    with pytest.raises(worktrees.WorktreeLifecycleError):
        _prepare(f)
    f[3].clear(); f[3].update(old)
    (f[0] / "file").write_text("dirty\n")
    with pytest.raises(worktrees.WorktreeLifecycleError):
        _prepare(f)
    (f[0] / "file").write_text("data\n")
    readbacks = _prepare(f)
    wrong = copy.deepcopy(readbacks)
    wrong["successor_registration"]["epoch"] = "f" * 32
    with pytest.raises(worktrees.WorktreeLifecycleError):
        _pin(f, wrong)
    with worktrees._locked_registry(f[1]) as payload:
        payload["worktrees"][str(f[0])]["registration_epoch"] = "e" * 32
    with pytest.raises(worktrees.WorktreeLifecycleError):
        _pin(f, readbacks)


def test_operator_rejects_hidden_index_and_history_drift(fixture):
    f = fixture
    _git(f[0], "update-index", "--assume-unchanged", "file")
    with pytest.raises(worktrees.WorktreeLifecycleError, match="index flags"):
        _prepare(f)
    _git(f[0], "update-index", "--no-assume-unchanged", "file")
    with worktrees._locked_registry(f[1]) as payload:
        payload["worktrees"][str(f[0])]["heartbeat_at"] += 1
    with pytest.raises(worktrees.WorktreeLifecycleError, match="history changed"):
        _prepare(f)


def test_operator_ack_rejects_candidate_drift_and_mixed_roots(fixture):
    f = fixture
    readbacks = _prepare(f)
    (f[0] / "file").write_text("changed\n")
    with pytest.raises(worktrees.WorktreeLifecycleError):
        _pin(f, readbacks)
    mixed = _comment(f[3], 1, 9500)
    body = json.loads(mixed["body"])
    body["lifecycle_handoff_receipt.v1"] = {}
    mixed["body"] = json.dumps(body)
    with pytest.raises(worktrees.WorktreeLifecycleError, match="mixed"):
        worktrees._transfer_comment(mixed, issue=6636, pr=None)


def test_prepared_operator_is_not_generic_authority_or_pickup(fixture):
    f = fixture
    _prepare(f)
    before = worktrees._locked_lifecycle_snapshot(f[1])[str(f[0])]
    with pytest.raises(worktrees.WorktreeLifecycleError, match="unpinned"):
        worktrees.assert_operator_registration_pinned(before)
    with pytest.raises(worktrees.WorktreeLifecycleError, match="unpinned"):
        worktrees._validate_authority_record(str(f[0]), before)
    with pytest.raises(worktrees.WorktreeLifecycleError, match="unpinned"):
        worktrees.load_lifecycle_authority(f[0], candidate_branch="codex/example")
    with pytest.raises(worktrees.WorktreeLifecycleError, match="unpinned"):
        worktrees.heartbeat_worktree(f[0], worktree=f[0], owner="new", now=9610)
    with pytest.raises(worktrees.WorktreeLifecycleError, match="unpinned"):
        worktrees.release_worktree(f[0], worktree=f[0], owner="new", now=9610)
    assert worktrees._locked_lifecycle_snapshot(f[1])[str(f[0])] == before
    renewed = worktrees.heartbeat_worktree(f[0], worktree=f[0], owner="new", now=9610,
                                           ttl_seconds=100, allow_prepared_operator=True)
    assert renewed["registration_epoch"] == before["registration_epoch"]
    with pytest.raises(worktrees.WorktreeLifecycleError, match="cannot be revived"):
        worktrees.heartbeat_worktree(f[0], worktree=f[0], owner="new", now=9710,
                                    allow_prepared_operator=True)
    assert worktrees._locked_lifecycle_snapshot(f[1])[str(f[0])] == renewed


def test_pinned_check_accepts_only_current_epoch(fixture):
    f = fixture
    readbacks = _prepare(f)
    _pin(f, readbacks)
    row = worktrees._locked_lifecycle_snapshot(f[1])[str(f[0])]
    worktrees.assert_operator_registration_pinned(row)
    assert worktrees.load_lifecycle_authority(f[0], candidate_branch="codex/example")[str(f[0])] == row
    row["registration_epoch"] = "f" * 32
    with pytest.raises(worktrees.WorktreeLifecycleError, match="epoch"):
        worktrees.assert_operator_registration_pinned(row)
    worktrees.assert_operator_registration_pinned({"owner": "ordinary"})


@pytest.mark.parametrize("field", ["issue", "predecessor", "branch_history_digest", "candidate_readback"])
def test_pinned_check_rejects_malformed_proof(fixture, field):
    f = fixture
    readbacks = _prepare(f)
    _pin(f, readbacks)
    row = worktrees._locked_lifecycle_snapshot(f[1])[str(f[0])]
    row["operator_registration"][field] = None
    with pytest.raises(worktrees.WorktreeLifecycleError):
        worktrees.assert_operator_registration_pinned(row)


def test_ack_intent_survives_interruption_and_refuses_second_post(fixture):
    f = fixture
    readbacks = _prepare(f)
    row = worktrees._locked_lifecycle_snapshot(f[1])[str(f[0])]
    assert "ack_intent" not in row["operator_registration"]
    ack = {**copy.deepcopy(f[3]), "successor_acknowledgment": {**readbacks, "ack_attempt_id": "a" * 32}}
    with pytest.raises(worktrees.WorktreeLifecycleError):
        worktrees.pin_operator_registration(f[0], worktree=f[0], owner="new", issue=6636,
             pending_comment=_comment(f[3], 1, 9500), ack_comment=_comment(ack, 2, 9700),
             workspace_root=f[5], now=9702)
    intent = _begin(f)
    assert worktrees._locked_lifecycle_snapshot(f[1])[str(f[0])]["operator_registration"]["ack_intent"] == intent
    with pytest.raises(worktrees.WorktreeLifecycleError, match="already exists"):
        _begin(f)
    with pytest.raises(worktrees.WorktreeLifecycleError, match="unpinned"):
        worktrees.load_lifecycle_authority(f[0], candidate_branch="codex/example")
    assert _pin(f, readbacks)["ack_intent"] == intent
    with pytest.raises(worktrees.WorktreeLifecycleError):
        _begin(f)


def test_ack_intent_refuses_changed_epoch_and_candidate(fixture):
    f = fixture
    _prepare(f)
    with worktrees._locked_registry(f[1]) as payload:
        payload["worktrees"][str(f[0])]["registration_epoch"] = "e" * 32
    with pytest.raises(worktrees.WorktreeLifecycleError, match="epoch"):
        _begin(f)
    row = worktrees._locked_lifecycle_snapshot(f[1])[str(f[0])]
    assert "ack_intent" not in row["operator_registration"]


def test_ack_requires_exact_attempt_id(fixture):
    f = fixture
    readbacks = _prepare(f)
    intent = _begin(f)
    ack = {**copy.deepcopy(f[3]), "successor_acknowledgment": {**readbacks, "ack_attempt_id": "f" * 32}}
    assert intent["attempt_id"] != "f" * 32
    with pytest.raises(worktrees.WorktreeLifecycleError):
        worktrees.pin_operator_registration(f[0], worktree=f[0], owner="new", issue=6636,
             pending_comment=_comment(f[3], 1, 9500), ack_comment=_comment(ack, 2, 9700),
             workspace_root=f[5], now=9702)


def test_ack_intent_rechecks_candidate_after_prepare(fixture):
    f = fixture
    _prepare(f)
    (f[0] / "file").write_text("changed\n")
    with pytest.raises(worktrees.WorktreeLifecycleError):
        _begin(f)
    row = worktrees._locked_lifecycle_snapshot(f[1])[str(f[0])]
    assert "ack_intent" not in row["operator_registration"]
