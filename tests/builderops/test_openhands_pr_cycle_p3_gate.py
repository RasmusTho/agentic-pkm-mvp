"""Severity-gate regressions for the actual PR #6628 informational-P3 normal cycle."""
import copy
import json
from pathlib import Path

import pytest

from app.builderops import epic_workspace as ew
from app.builderops import openhands_pr_cycle as cycle
from tests.builderops.test_openhands_pr_cycle import HEAD, fake_completed_review_stop, fetch, setup

ACTUAL = json.loads((Path(__file__).parent / "fixtures" / "pr6628_head6018_p3_review_report.json").read_text())
SCOPE_GAP = "independent scope and Verify coverage assessment is incomplete"
PARKED = "review repair belongs to current owner"


def _cycle(tmp_path, monkeypatch):
    """Real advance/state/stop-lineage logic; only engine, agent-server, sandbox and CI ports are fake."""
    layout, config, server = setup(tmp_path, monkeypatch)
    config[0].update(engine="claude-code", model="claude-opus-5-5", verify_targets=list(ACTUAL["verify_targets"]))
    monkeypatch.setattr(cycle, "native_execution_proof", lambda layout, worker, op, entry, **kw: {
        "operation_id": op, "engine": "claude-code", "model": "claude-opus-5-5", "auth": "claude-subscription",
        "source": "native-session-metadata", "native_session_id": "native", "effort": None,
        "timestamp": "2026-11-14T08:40:00Z", "conversation_id": cycle._mapping(layout, worker)["conversation"]["id"],
        "container_id": cycle._mapping(layout, worker)["container_id"]})
    calls = []
    monkeypatch.setattr(ew, "stop_worker", lambda layout, worker, **kw:
                        calls.append("stop") or fake_completed_review_stop(layout, worker, **kw))
    monkeypatch.setattr(cycle, "sandbox_verify", lambda layout, worker, head, targets, venv, saved:
                        calls.append("sandbox") or {"head_sha": head, "targets": targets, "passed": True})
    monkeypatch.setattr(cycle, "ci_once", lambda *args: calls.append("ci") or {"exit_code": 0})
    cycle.advance(layout, config, fetch=fetch, http=server)  # reserve and start the one review conversation
    state = ew._load_state(layout)
    record = next(r for r in state["compact_receipts"] if r.get("kind") == "pr_cycle")
    cid = state["issue_mappings"]["6618"]["conversation"]["id"]
    server.conversations[cid]["execution_status"] = "finished"
    return layout, config, server, record["identity"], cid, calls


def _finish(server, cid, identity, report):
    report = {**copy.deepcopy(report), "identity": identity, "head_sha": HEAD}
    server.final_responses[cid] = "Review closeout.\n<BEGIN_PR_CYCLE_REPORT>\n" + json.dumps(report) + "\n<END_PR_CYCLE_REPORT>"
    return report


def _parked_by_9fa8(layout, config, server, identity, cid, monkeypatch):
    """Produce the actual saved record: report, native proof, verified stop and the 9fa8 parked wait."""
    report = _finish(server, cid, identity, ACTUAL)
    with monkeypatch.context() as old:
        old.setattr(cycle, "review_gate", lambda review: {"outcome": "pass" if review["verdict"] == "pass"
                    and not review["findings"] else "changes_requested", "blocking": [], "informational": []}, raising=False)
        tick = cycle.advance(layout, config, fetch=fetch, http=server)
    assert tick["results"][1]["reason"] == PARKED
    saved = cycle._find(layout, 10, identity)
    saved.pop("review_gate", None)  # 9fa8 never persisted a derived gate
    cycle._save(layout, saved)
    return report


def test_actual_p3_record_continues_after_restart_to_verification_ci_and_premerge(tmp_path, monkeypatch):
    layout, config, server, identity, cid, calls = _cycle(tmp_path, monkeypatch)
    report = _parked_by_9fa8(layout, config, server, identity, cid, monkeypatch)
    parked = cycle._find(layout, 10, identity)
    assert calls == ["stop"] and parked["stop_verified"] is True and "verification" not in parked
    assert parked["execution_proof"]["conversation_id"] == cid and parked["review"] == report

    # Controller restart: a new advance call reads only the durable run state.
    result = cycle.advance(layout, config, fetch=fetch, http=server)
    saved = cycle._find(layout, 10, identity)
    assert calls == ["stop", "sandbox", "ci"]
    assert saved["review"] == report and saved["review"]["findings"] == ACTUAL["findings"]
    assert saved["review_gate"] == {"outcome": "pass", "blocking": [], "informational": [
        {"index": 0, "severity": "P3", "category": "owner-doc-accuracy",
         "file": "docs/development/DEV_WORKFLOW.md", "line": 585}]}
    assert saved["verification"]["stop_id"] == saved["stop_intent"]["stop_id"]
    # The final gate accepts the P3 itself; the report's own scope limitations remain a separate wait.
    assert result["results"][1] == {"number": 10, "action": "wait", "reason": SCOPE_GAP}
    assert len([c for c in server.calls if c[0] == "POST"]) == 1  # same operation and conversation
    assert "merge_intent" not in saved


def test_premerge_reaches_live_authority_for_p3_only_report(tmp_path, monkeypatch):
    layout, config, server, identity, cid, calls = _cycle(tmp_path, monkeypatch)
    clean = copy.deepcopy(ACTUAL)
    clean["scope_assessment"]["limitations"] = []
    clean["owner_doc"]["outcome"] = "no_change"
    _finish(server, cid, identity, clean)
    monkeypatch.setattr(cycle, "github_fetch", fetch)
    def authority(*args):
        raise cycle.CycleError("native authority boundary reached")
    monkeypatch.setattr(cycle, "native_authority", authority)
    result = cycle.advance(layout, config, fetch=fetch, http=server)
    assert calls == ["stop", "sandbox", "ci"]
    # Review, scope, owner-doc and fresh contract gates passed; ownership and CI stay live gates.
    assert result["results"][1]["reason"] == "native authority boundary reached"


def _blocking_reports():
    def finding(**change):
        report = copy.deepcopy(ACTUAL)
        report["findings"][0].update(change)
        return report
    extra = copy.deepcopy(ACTUAL)
    extra["findings"][0]["protected"] = False
    second = copy.deepcopy(ACTUAL)
    second["findings"].append({**ACTUAL["findings"][0], "severity": "P2", "category": "correctness"})
    incomplete = copy.deepcopy(ACTUAL)
    incomplete["closing_assessments"]["6619"]["acceptance"] = "incomplete"
    unverified = copy.deepcopy(ACTUAL)
    unverified["closing_assessments"]["6619"]["verify_coverage"] = "incomplete"
    no_doc = copy.deepcopy(ACTUAL)
    no_doc["owner_doc"]["inspected_paths"] = []
    no_sources = copy.deepcopy(ACTUAL)
    del no_sources["covered_sources"]
    return {"P0": finding(severity="P0"), "P1": finding(severity="P1"), "P2-undispositioned": finding(severity="P2"),
            "P3-plus-P2": second, "unknown-severity": finding(severity="P4"), "lowercase": finding(severity="p3"),
            "no-category": finding(category=""), "bad-line": finding(line=True),
            "protected-acceptance": finding(category="acceptance-gap"),
            "protected-false-green": finding(category="false-green-ci"), "unknown-field": extra,
            "string-finding": {**ACTUAL, "findings": ["repair"]}, "acceptance-incomplete": incomplete,
            "verify-incomplete": unverified, "owner-doc-uninspected": no_doc, "sources-missing": no_sources}


@pytest.mark.parametrize("case", sorted(_blocking_reports()))
def test_blocking_or_unqualified_findings_stay_parked_with_report_unchanged(tmp_path, monkeypatch, case):
    layout, config, server, identity, cid, calls = _cycle(tmp_path, monkeypatch)
    report = _finish(server, cid, identity, _blocking_reports()[case])
    result = cycle.advance(layout, config, fetch=fetch, http=server)
    saved = cycle._find(layout, 10, identity)
    assert result["results"][1]["reason"] == PARKED
    assert calls == ["stop"] and "verification" not in saved and "ci" not in saved
    assert saved["review"] == report and saved["review_gate"]["outcome"] == "changes_requested"
    assert saved["review_gate"]["blocking"]
    cycle.advance(layout, config, fetch=fetch, http=server)  # saved-record replay stays parked
    assert calls == ["stop"]


@pytest.mark.parametrize("review", [
    {**ACTUAL, "verdict": "pass"},  # a pass label cannot carry findings past the gate
    {**ACTUAL, "verdict": "pass", "findings": [{**ACTUAL["findings"][0], "category": "authority-integrity"}]},
    {**ACTUAL, "verdict": "findings", "findings": []}, {**ACTUAL, "verdict": "unknown"}])
def test_saved_record_replay_and_premerge_rederive_gate_from_report(tmp_path, monkeypatch, review):
    layout, config, server, identity, cid, calls = _cycle(tmp_path, monkeypatch)
    _parked_by_9fa8(layout, config, server, identity, cid, monkeypatch)
    saved = cycle._find(layout, 10, identity)
    saved.update(review=review, review_gate={"outcome": "pass", "blocking": [], "informational": []})
    cycle._save(layout, saved)
    result = cycle.advance(layout, config, fetch=fetch, http=server)
    assert result["results"][1]["reason"] == PARKED and calls == ["stop"]
    assert cycle._find(layout, 10, identity)["review_gate"]["outcome"] == "changes_requested"
    saved.update(verification={"passed": True, "head_sha": HEAD, "targets": config[0]["verify_targets"]})
    with pytest.raises(cycle.CycleError, match="review execution or sandbox verification is incomplete"):
        cycle._premerge(layout, {"number": 10, "head_sha": HEAD}, config[0], saved)


def test_missing_native_proof_does_not_verify_p3_report(tmp_path, monkeypatch):
    layout, config, server, identity, cid, calls = _cycle(tmp_path, monkeypatch)
    _finish(server, cid, identity, ACTUAL)
    def unavailable(*args, **kwargs):
        raise cycle.CycleError("native conversation execution is not established")
    monkeypatch.setattr(cycle, "native_execution_proof", unavailable)
    for _ in range(2):
        result = cycle.advance(layout, config, fetch=fetch, http=server)
        assert result["results"][1]["reason"] == "native conversation execution is not established"
    saved = cycle._find(layout, 10, identity)
    assert calls == [] and "execution_proof" not in saved and "verification" not in saved


def test_stale_head_does_not_reuse_p3_record(tmp_path, monkeypatch):
    layout, config, server, identity, cid, calls = _cycle(tmp_path, monkeypatch)
    _parked_by_9fa8(layout, config, server, identity, cid, monkeypatch)
    moved = lambda path, timeout: (lambda r: (r[0], r[1].replace(HEAD.encode(), b"e" * 40)))(fetch(path, timeout))
    result = cycle.advance(layout, config, fetch=moved, http=server)
    assert result["results"][1]["reason"] == "not admitted at this head"
    assert calls == ["stop"] and "verification" not in cycle._find(layout, 10, identity)


def test_competing_writer_assignment_blocks_p3_continuation(tmp_path, monkeypatch):
    layout, config, server, identity, cid, calls = _cycle(tmp_path, monkeypatch)
    _parked_by_9fa8(layout, config, server, identity, cid, monkeypatch)
    ew._record_worker(layout, 6618, container_id="f" * 64)  # another writer now owns the worker slot
    result = cycle.advance(layout, config, fetch=fetch, http=server)
    assert result["results"][1]["action"] == "wait" and result["results"][1]["reason"] != SCOPE_GAP
    assert calls == ["stop"] and "verification" not in cycle._find(layout, 10, identity)


def test_review_gate_on_actual_report_is_pass_with_visible_p3():
    gate = cycle.review_gate(ACTUAL)
    assert gate["outcome"] == "pass" and [row["severity"] for row in gate["informational"]] == ["P3"]
    assert cycle.review_gate({**ACTUAL, "verdict": "pass", "findings": []}) == {
        "outcome": "pass", "blocking": [], "informational": []}
