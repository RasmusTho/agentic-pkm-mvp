"""One-shot repair reservation and conversation, with synthetic external effects."""

import json

import pytest

from app.builderops import epic_workspace as ew
from app.builderops import openhands_pr_cycle as cycle
from tests.builderops.test_openhands_pr_cycle import (
    BLOCKING_FINDING, CONFORMING, HEAD, bind_worker_endpoint, fake_completed_review_stop, fetch, setup,
)


def repair_setup(tmp_path, monkeypatch):
    layout, config, server = setup(tmp_path, monkeypatch)
    ew._record_worker(layout, 6618, branch="codex/example", image="worker@sha256:" + "c" * 64,
                      network="epicws", budget={"cpus": "1.0", "memory": "1536m", "pids": 512},
                      lifecycle_owner="owner-6618", builder_session="builder-session-6618")
    config[0].update(claimant="owner-6618", session="builder-session-6618")
    cycle.advance(layout, config, fetch=fetch, http=server)
    state = ew._load_state(layout)
    cid = state["issue_mappings"]["6618"]["conversation"]["id"]
    saved = next(r for r in state["compact_receipts"] if r.get("kind") == "pr_cycle")
    report = {**CONFORMING, "identity": saved["identity"], "head_sha": HEAD, "verdict": "findings",
              "findings": [BLOCKING_FINDING], "verify_targets": config[0]["verify_targets"]}
    server.conversations[cid]["execution_status"] = "finished"
    server.final_responses[cid] = json.dumps(report)
    def stop(layout, worker, **kwargs):
        fake_completed_review_stop(layout, worker, **kwargs)
        mapping = cycle._mapping(layout, worker)
        ew._record_worker(layout, 6618, conversation={**mapping["conversation"], "status": ew.CONVERSATION_ENDED},
                          work_at_stop={**mapping["work_at_stop"], "head": HEAD})
    monkeypatch.setattr(ew, "stop_worker", stop)
    calls = []
    def authority(layout, pr, entry, **kwargs):
        calls.append(kwargs)
        return {"owner": {"lease_id": "synthetic-lease"}, "claim_issue": 6618,
                "head_sha": pr["head_sha"], "branch": "codex/example"}
    monkeypatch.setattr(cycle, "native_authority", authority)
    def takeover(layout, worker, **kwargs):
        mapping = cycle._mapping(layout, worker)
        assert mapping["state"] == "stopped_verified" and kwargs["stop_intent"]["stop_id"] == mapping["stop_id"]
        ew._record_worker(layout, 6618, takeover={"status": "authorized", "stop_id": mapping["stop_id"], "generation": 1})
    def launch(layout, worker, **kwargs):
        mapping = cycle._mapping(layout, worker)
        assert mapping["takeover"]["status"] == "authorized"
        bind_worker_endpoint(layout, monkeypatch, "e" * 64)
        ew._record_worker(layout, 6618, state="running", container_id="e" * 64,
                          takeover={"status": "consumed", "stop_id": mapping["stop_id"], "generation": 1})
    monkeypatch.setattr(ew, "_takeover_locked", takeover)
    monkeypatch.setattr(ew, "_start_openhands_worker_locked", launch)
    return layout, config, server, calls


def repair_records(layout):
    return [r for r in ew._load_state(layout)["dispatch_decisions"]
            if r.get("request") == "repair-author"]


def test_repair_author_reserves_once_and_duplicate_tick_reuses_conversation(tmp_path, monkeypatch):
    layout, config, server, calls = repair_setup(tmp_path, monkeypatch)
    first = cycle.advance(layout, config, fetch=fetch, http=server)["results"][1]
    assert first["action"] == "repair-author" and "created" in first["reason"]
    [reservation] = repair_records(layout)
    assert reservation["operation_id"] == first["operation_id"] and reservation["outcome"] == "unknown"
    assert calls[-1]["purpose"] == "repair" and "repair_writer" in calls[-1]
    second = cycle.advance(layout, config, fetch=fetch, http=server)["results"][1]
    assert second["operation_id"] == first["operation_id"]
    assert len(repair_records(layout)) == 1 and len([c for c in server.calls if c[0] == "POST"]) == 2
    payload = [c[3] for c in server.calls if c[0] == "POST"][-1]
    assert payload["agent_settings"]["acp_server"] == "codex"
    assert payload["agent_settings"]["acp_model"] == "gpt-6.1-terra"
    assert "Do not publish" in payload["initial_message"]["content"][0]["text"]


def test_lost_repair_create_preserves_original_operation_and_conversation(tmp_path, monkeypatch):
    layout, config, server, _ = repair_setup(tmp_path, monkeypatch)
    server.lose_next_create = server.create_not_applied = True
    first = cycle.advance(layout, config, fetch=fetch, http=server)["results"][1]
    assert first["action"] == "repair-author" and "unknown" in first["reason"]
    conversation = cycle._mapping(layout, "reviewer")["conversation"]
    second = cycle.advance(layout, config, fetch=fetch, http=server)["results"][1]
    assert second["operation_id"] == first["operation_id"]
    assert cycle._mapping(layout, "reviewer")["conversation"]["id"] == conversation["id"]
    assert len(repair_records(layout)) == 1 and len([c for c in server.calls if c[0] == "POST"]) == 2


def test_changed_authority_before_conversation_holds_reserved_operation(tmp_path, monkeypatch):
    layout, config, server, calls = repair_setup(tmp_path, monkeypatch)
    def changed(layout, pr, entry, **kwargs):
        calls.append(kwargs)
        return {"owner": {"lease_id": "changed" if "repair_writer" in kwargs else "synthetic-lease"},
                "claim_issue": 6618, "head_sha": pr["head_sha"], "branch": "codex/example"}
    monkeypatch.setattr(cycle, "native_authority", changed)
    result = cycle.advance(layout, config, fetch=fetch, http=server)["results"][1]
    assert result["action"] == "wait" and "authority changed" in result["reason"]
    assert len(repair_records(layout)) == 1
    assert len([c for c in server.calls if c[0] == "POST"]) == 1
    cycle.advance(layout, config, fetch=fetch, http=server)
    assert len(repair_records(layout)) == 1 and len([c for c in server.calls if c[0] == "POST"]) == 1


def test_unresolved_publication_blocks_repair_without_reserving_another_effect(tmp_path, monkeypatch):
    layout, config, server, _ = repair_setup(tmp_path, monkeypatch)
    ew._record_worker(layout, 6618, publication_ops=[{"id": "branch_push-1", "kind": "branch_push",
                                                      "branch": "codex/example", "status": "intended"}])
    result = cycle.advance(layout, config, fetch=fetch, http=server)["results"][1]
    assert result["action"] == "wait" and "publication remains unresolved" in result["reason"]
    assert repair_records(layout) == [] and len([c for c in server.calls if c[0] == "POST"]) == 1


def test_authority_hold_does_not_block_unrelated_admitted_peer(tmp_path, monkeypatch):
    layout, config, server, _ = repair_setup(tmp_path, monkeypatch)
    ew._reserve_worker(layout, 6619, "peer", state="running", runtime="openhands", port=18701,
                       container_id="f" * 64)
    config.insert(0, {**config[0], "number": 9, "worker": "peer"})
    def peer_fetch(path, timeout):
        if "/issues/6619" in path:
            return 200, json.dumps({"number": 6619, "state": "open", "body": "Peer contract"}).encode()
        status, body = fetch(path, timeout)
        if path.endswith("/pulls/9"):
            row = json.loads(body)
            row["draft"] = False
            row["body"] = "Governing-Issue: #6619"
            body = json.dumps(row).encode()
        return status, body
    def held(layout, pr, entry, **kwargs):
        raise cycle.CycleError("current claim is held")
    monkeypatch.setattr(cycle, "native_authority", held)
    monkeypatch.setattr(cycle, "start_or_reconcile_review", lambda *args, **kwargs:
                        {"id": "synthetic-peer-conversation", "status": "created"})
    results = cycle.advance(layout, config, fetch=peer_fetch, http=server)["results"]
    assert results[0]["number"] == 9 and results[0]["action"] == "independent-review"
    assert results[1]["number"] == 10 and results[1]["action"] == "wait"
    assert results[1]["repair_authority"]["status"] == "unavailable"
    assert repair_records(layout) == []


def test_confirmed_publication_readback_is_reused_and_bad_evidence_holds(tmp_path, monkeypatch):
    layout, config, server, _ = repair_setup(tmp_path, monkeypatch)
    confirmed = {"id": "branch_push-1", "kind": "branch_push", "branch": "codex/example", "status": "confirmed",
                 "expect_sha": HEAD, "result": {"branch": "codex/example", "sha": HEAD}}
    ew._record_worker(layout, 6618, publication_ops=[confirmed])
    result = cycle.advance(layout, config, fetch=fetch, http=server)["results"][1]
    assert result["action"] == "repair-author" and len(repair_records(layout)) == 1
    with pytest.raises(cycle.CycleError, match="publication remains unresolved"):
        cycle._assert_repair_publications_settled({"branch": "codex/example", "publication_ops": [
            {**confirmed, "result": {"branch": "codex/example", "sha": "different"}}]})


def test_foreign_source_branch_does_not_reserve_repair(tmp_path, monkeypatch):
    layout, config, server, _ = repair_setup(tmp_path, monkeypatch)
    monkeypatch.setattr(cycle, "native_authority", lambda layout, pr, entry, **kw:
                        {"owner": {"lease_id": "synthetic-lease"}, "claim_issue": 6618,
                         "head_sha": HEAD, "branch": "foreign"})
    result = cycle.advance(layout, config, fetch=fetch, http=server)["results"][1]
    assert result["action"] == "wait" and "source branch and head" in result["reason"]
    assert repair_records(layout) == [] and len([c for c in server.calls if c[0] == "POST"]) == 1


def test_changed_builder_session_before_post_preserves_original_unknown_conversation(tmp_path, monkeypatch):
    layout, config, server, _ = repair_setup(tmp_path, monkeypatch)
    reserve = ew._reserve_conversation
    def changed(layout, issue, worker, record, expected):
        result = reserve(layout, issue, worker, record, expected)
        ew._record_worker(layout, issue, builder_session="different-session")
        return result
    monkeypatch.setattr(ew, "_reserve_conversation", changed)
    result = cycle.advance(layout, config, fetch=fetch, http=server)["results"][1]
    assert result["action"] == "wait" and "changed before creation" in result["reason"]
    conversation = cycle._mapping(layout, "reviewer")["conversation"]
    assert conversation["status"] == "unknown" and len(repair_records(layout)) == 1
    assert len([c for c in server.calls if c[0] == "POST"]) == 1
    resumed = cycle.advance(layout, config, fetch=fetch, http=server)["results"][1]
    assert resumed["operation_id"] == repair_records(layout)[0]["operation_id"]
    assert cycle._mapping(layout, "reviewer")["conversation"]["id"] == conversation["id"]
    assert len([c for c in server.calls if c[0] == "POST"]) == 1


def test_worker_cannot_repair_different_claimed_issue(tmp_path, monkeypatch):
    layout, config, server, _ = repair_setup(tmp_path, monkeypatch)
    monkeypatch.setattr(cycle, "native_authority", lambda layout, pr, entry, **kw:
                        {"owner": {"lease_id": "synthetic-lease"}, "claim_issue": 6619,
                         "head_sha": HEAD, "branch": "codex/example"})
    result = cycle.advance(layout, config, fetch=fetch, http=server)["results"][1]
    assert result["action"] == "wait" and "claimed Issue" in result["reason"]
    assert repair_records(layout) == [] and len([c for c in server.calls if c[0] == "POST"]) == 1
