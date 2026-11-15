"""Continuation fences for a reserved repair; external ports are synthetic."""

import copy
import time

import pytest

from app.builderops import epic_run_state
from app.builderops import epic_workspace as ew
from app.builderops import openhands_pr_cycle as cycle
from tests.builderops.test_openhands_pr_cycle import _native_authority_fixture, fetch
from tests.builderops.test_openhands_pr_cycle_repair_author import repair_records, repair_setup


def _interrupt_before_takeover(layout, config, server, monkeypatch):
    original = ew._takeover_locked
    monkeypatch.setattr(ew, "_takeover_locked", lambda *a, **k: (_ for _ in ()).throw(cycle.CycleError("interrupt")))
    result = cycle.advance(layout, config, fetch=fetch, http=server)["results"][1]
    monkeypatch.setattr(ew, "_takeover_locked", original)
    assert result["action"] == "wait" and len(repair_records(layout)) == 1


def _saved_update(layout, update):
    def mutate(state):
        row = next(r for r in state["compact_receipts"] if r.get("kind") == "pr_cycle")
        update(row)
        return state
    epic_run_state.update_epic_run_state(layout.run_id, root=layout.run_state_dir, updater=mutate,
                                         expected_epic_issue_number=layout.epic)


def test_renewal_before_takeover_and_repeated_resume_preserves_one_attempt(tmp_path, monkeypatch):
    layout, config, server, _ = repair_setup(tmp_path, monkeypatch)
    expiry = ["one"]
    def authority(layout, pr, entry, **kwargs):
        return {"owner": {"lease_id": "lease", "lease_holder": "holder", "lease_expires_at": expiry[0]},
                "worktree_owner": {"path": "/source", "generation": "gen", "registration_epoch": "epoch",
                                   "expires_at": expiry[0]},
                "claim_issue": 6618, "head_sha": pr["head_sha"], "branch": "codex/example"}
    monkeypatch.setattr(cycle, "native_authority", authority)
    _interrupt_before_takeover(layout, config, server, monkeypatch)
    expiry[0] = "two"
    first = cycle.advance(layout, config, fetch=fetch, http=server)["results"][1]
    conversation = cycle._mapping(layout, "reviewer")["conversation"]
    expiry[0] = "three"
    second = cycle.advance(layout, config, fetch=fetch, http=server)["results"][1]
    assert first["action"] == "repair-author" and second["operation_id"] == first["operation_id"]
    assert cycle._mapping(layout, "reviewer")["conversation"]["id"] == conversation["id"]
    assert len(repair_records(layout)) == 1 and len([c for c in server.calls if c[0] == "POST"]) == 2


@pytest.mark.parametrize("field", ["lease_id", "lease_holder", "task_id", "linked_pr", "session", "branch", "generation", "registration_epoch"])
def test_changed_authority_identity_blocks_pre_post(tmp_path, monkeypatch, field):
    layout, config, server, _ = repair_setup(tmp_path, monkeypatch)
    snapshot = {"owner": {"lease_id": "lease", "lease_holder": "holder", "task_id": "task", "linked_pr": "10",
                          "session": "session", "lease_expires_at": "one"},
                "worktree_owner": {"generation": "gen", "registration_epoch": "epoch", "expires_at": 1},
                "claim_issue": 6618, "head_sha": "a" * 40, "branch": "codex/example"}
    def authority(layout, pr, entry, **kwargs):
        value = copy.deepcopy(snapshot)
        value["head_sha"] = pr["head_sha"]
        if "repair_writer" in kwargs:
            target = value["worktree_owner"] if field in ("generation", "registration_epoch") else value["owner"]
            if field == "branch":
                target = value
            target[field] = "changed"
            value["owner"]["lease_expires_at"] = "two"
        return value
    monkeypatch.setattr(cycle, "native_authority", authority)
    result = cycle.advance(layout, config, fetch=fetch, http=server)["results"][1]
    assert result["action"] == "wait" and "authority changed" in result["reason"]
    assert len(repair_records(layout)) == 1 and len([c for c in server.calls if c[0] == "POST"]) == 1


def test_actual_authority_worktree_renewal_and_expiry_fences(tmp_path, monkeypatch):
    f = _native_authority_fixture(tmp_path, monkeypatch)
    worktree = cycle.agent_worktree
    worktree.register_worktree(f["source"], worktree=f["worktree"], owner="session-original", now=int(time.time()) - 800)
    first = cycle.native_authority(f["layout"], f["pr"], f["entry"], purpose="repair")
    worktree.heartbeat_worktree(f["source"], worktree=f["worktree"], owner="session-original")
    f["task"]["lease_expires_at"] = f["lease"]["expires_at"] = "2099-01-02T00:00:00Z"
    fresh = cycle.native_authority(f["layout"], f["pr"], f["entry"], purpose="repair")
    assert cycle._repair_authority_continues(first, fresh)
    legacy = copy.deepcopy(first)
    legacy["worktree_owner"].pop("registration_epoch")
    assert not cycle._repair_authority_continues(legacy, fresh)
    f["lease"]["released_at"] = "2020-01-01T00:00:00Z"
    with pytest.raises(cycle.CycleError):
        cycle.native_authority(f["layout"], f["pr"], f["entry"], purpose="repair")
    f["lease"]["released_at"] = None
    f["task"]["lease_expires_at"] = f["lease"]["expires_at"] = "2020-01-01T00:00:00Z"
    with pytest.raises(cycle.CycleError):
        cycle.native_authority(f["layout"], f["pr"], f["entry"], purpose="repair")


@pytest.mark.parametrize("change", ["replaced", "foreign", "provenance", "released_event"])
def test_actual_authority_rejects_changed_claim_lineage(tmp_path, monkeypatch, change):
    f = _native_authority_fixture(tmp_path, monkeypatch)
    cycle.agent_worktree.register_worktree(f["source"], worktree=f["worktree"], owner="session-original",
                                          now=int(time.time()) - 800)
    cycle.native_authority(f["layout"], f["pr"], f["entry"], purpose="repair")
    if change == "replaced":
        f["task"]["lease_id"] = f["lease"]["lease_id"] = "replacement"
    elif change == "foreign":
        f["task"]["claimed_by"] = f["lease"]["holder"] = "foreign"
    elif change == "provenance":
        f["events"][0]["payload"]["session"] = "foreign-session"
    else:
        f["events"].append({"task_id": f["task_id"], "event_type": "task.released",
                            "actor": "original", "lease_id": "old-lease"})
    with pytest.raises(cycle.CycleError):
        cycle.native_authority(f["layout"], f["pr"], f["entry"], purpose="repair")


def test_interruption_before_post_resumes_after_renewal_without_second_launch(tmp_path, monkeypatch):
    layout, config, server, _ = repair_setup(tmp_path, monkeypatch)
    expiry = ["one"]
    monkeypatch.setattr(cycle, "native_authority", lambda layout, pr, entry, **kw:
                        {"owner": {"lease_id": "lease", "lease_expires_at": expiry[0]},
                         "claim_issue": 6618, "head_sha": pr["head_sha"], "branch": "codex/example"})
    start = ew._start_conversation_locked
    monkeypatch.setattr(ew, "_start_conversation_locked",
                        lambda *a, **kw: (_ for _ in ()).throw(cycle.CycleError("interrupt before create")))
    first = cycle.advance(layout, config, fetch=fetch, http=server)["results"][1]
    assert first["action"] == "wait" and cycle._mapping(layout, "reviewer")["state"] == "running"
    container = cycle._mapping(layout, "reviewer")["container_id"]
    monkeypatch.setattr(ew, "_start_conversation_locked", start)
    expiry[0] = "two"
    second = cycle.advance(layout, config, fetch=fetch, http=server)["results"][1]
    third = cycle.advance(layout, config, fetch=fetch, http=server)["results"][1]
    assert second["action"] == "repair-author" and third["operation_id"] == second["operation_id"]
    assert cycle._mapping(layout, "reviewer")["container_id"] == container
    assert len(repair_records(layout)) == 1 and len([c for c in server.calls if c[0] == "POST"]) == 2


def test_authority_rechecked_after_takeover_before_worker_launch(tmp_path, monkeypatch):
    layout, config, server, _ = repair_setup(tmp_path, monkeypatch)
    valid = [True]
    def authority(layout, pr, entry, **kwargs):
        if not valid[0]:
            raise cycle.CycleError("lease released during takeover")
        return {"owner": {"lease_id": "lease"}, "claim_issue": 6618,
                "head_sha": pr["head_sha"], "branch": "codex/example"}
    monkeypatch.setattr(cycle, "native_authority", authority)
    takeover = ew._takeover_locked
    def release_after_takeover(*args, **kwargs):
        takeover(*args, **kwargs)
        valid[0] = False
    monkeypatch.setattr(ew, "_takeover_locked", release_after_takeover)
    result = cycle.advance(layout, config, fetch=fetch, http=server)["results"][1]
    assert result["action"] == "wait" and "lease released" in result["reason"]
    assert cycle._mapping(layout, "reviewer")["state"] == "stopped_verified"
    assert len(repair_records(layout)) == 1 and len([c for c in server.calls if c[0] == "POST"]) == 1


@pytest.mark.parametrize("legacy", [False, True])
def test_historical_handoff_resume_keeps_original_admission_and_one_operation(tmp_path, monkeypatch, legacy):
    layout, config, server, _ = repair_setup(tmp_path, monkeypatch)
    saved = next(r for r in ew._load_state(layout)["compact_receipts"] if r.get("kind") == "pr_cycle")
    ew._record_worker(layout, 6618, engine_handoff={"status": "complete", "operation_id": saved["review_operation"]})
    config[0].update(engine="claude-code", model="claude-sonnet-5-5")
    original = copy.deepcopy(config)
    _interrupt_before_takeover(layout, config, server, monkeypatch)
    if legacy:
        _saved_update(layout, lambda row: (row.pop("repair_admission_selection"), row.pop("repair_handoff_binding")))
    result = cycle.advance(layout, config, fetch=fetch, http=server)["results"][1]
    assert config == original and result["action"] == "repair-author"
    assert cycle.advance(layout, config, fetch=fetch, http=server)["results"][1]["operation_id"] == result["operation_id"]
    assert len(repair_records(layout)) == 1 and len([c for c in server.calls if c[0] == "POST"]) == 2


def test_unfinished_review_handoff_cannot_authorize_repair_post(tmp_path, monkeypatch):
    layout, config, server, _ = repair_setup(tmp_path, monkeypatch)
    saved = next(r for r in ew._load_state(layout)["compact_receipts"] if r.get("kind") == "pr_cycle")
    ew._record_worker(layout, 6618, engine_handoff={"status": "awaiting_pr_cycle", "operation_id": saved["review_operation"]})
    config[0].update(engine="claude-code", model="claude-sonnet-5-5")
    result = cycle.advance(layout, config, fetch=fetch, http=server)["results"][1]
    assert result["action"] == "wait" and "handoff" in result["reason"]
    assert repair_records(layout) == [] and len([c for c in server.calls if c[0] == "POST"]) == 1
    ew._record_worker(layout, 6618, engine_handoff={"status": "complete", "operation_id": saved["review_operation"]})
    result = cycle.advance(layout, config, fetch=fetch, http=server)["results"][1]
    assert result["action"] == "repair-author" and len(repair_records(layout)) == 1
    assert len([c for c in server.calls if c[0] == "POST"]) == 2


def test_current_codex_admission_does_not_return_to_claude(tmp_path, monkeypatch):
    layout, config, server, _ = repair_setup(tmp_path, monkeypatch)
    saved = next(r for r in ew._load_state(layout)["compact_receipts"] if r.get("kind") == "pr_cycle")
    ew._record_worker(layout, 6618, engine_handoff={"status": "complete", "operation_id": saved["review_operation"],
                                                   "confirmation": {"engine": "claude-code", "model": "claude-old"}})
    result = cycle.advance(layout, config, fetch=fetch, http=server)["results"][1]
    assert result["action"] == "repair-author"
    payload = [call[3] for call in server.calls if call[0] == "POST"][-1]
    assert payload["agent_settings"]["acp_server"] == "codex"
    assert payload["agent_settings"]["acp_model"] == "gpt-6.1-terra"


@pytest.mark.parametrize("change", ["model", "engine", "handoff", "owner"])
def test_handoff_or_selection_changes_block_reserved_attempt(tmp_path, monkeypatch, change):
    layout, config, server, _ = repair_setup(tmp_path, monkeypatch)
    saved = next(r for r in ew._load_state(layout)["compact_receipts"] if r.get("kind") == "pr_cycle")
    handoff = {"status": "complete", "operation_id": saved["review_operation"]}
    ew._record_worker(layout, 6618, engine_handoff=handoff)
    config[0].update(engine="claude-code", model="claude-sonnet-5-5")
    _interrupt_before_takeover(layout, config, server, monkeypatch)
    if change == "model":
        config[0]["model"] = "claude-sonnet-4-5"
    elif change == "engine":
        config[0].update(engine="codex", model="gpt-6.1-terra")
    elif change == "handoff":
        ew._record_worker(layout, 6618, engine_handoff={**handoff, "operation_id": "another-review"})
    else:
        ew._record_worker(layout, 6618, builder_session="foreign")
    result = cycle.advance(layout, config, fetch=fetch, http=server)["results"][1]
    assert result["action"] == "wait"
    assert len(repair_records(layout)) == 1 and len([c for c in server.calls if c[0] == "POST"]) == 1
