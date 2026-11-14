"""Report-contract convergence for the actual PR #6628 informational-P3 normal cycle.

Real advance, run state, stop lineage, review gate, premerge, merge intent and readback run here.
Only the engine, agent-server, sandbox, CI, stop, native-authority and GitHub ports are fake.
"""
import copy
import json
from pathlib import Path

import pytest

from app.builderops import epic_workspace as ew
from app.builderops import openhands_pr_cycle as cycle
from tests.builderops.openhands_disposition_test_support import synthetic_disposition
from tests.builderops.test_openhands_pr_cycle import (
    HEAD, bind_worker_endpoint, fake_completed_review_stop, fetch, review_material, setup,
)

ACTUAL = json.loads((Path(__file__).parent / "fixtures" / "pr6628_head6018_p3_review_report.json").read_text())
# The pre-repair premerge park reason, kept for the preserved 6ac8 review repro.
SCOPE_GAP = "independent scope and Verify coverage assessment is incomplete"
PARKED = "review repair belongs to current owner"
# Public #6619 acceptance text; its SHA-256 is the criterion key in the saved report.
CRITERION = ("- [ ] A repeated no-progress case and a self-imposed technical dependency produce a recorded bounded "
             "action through the running coordinator, while an authority stop is preserved and independent work "
             "continues.\n  - Verify: `tests/builderops/test_epic_workspace_coordination.py::"
             "test_no_progress_and_false_blocker_trigger_bounded_action`")
OWNER_DOCS = ["docs/STATUS.md", "docs/development/DEV_WORKFLOW.md", "docs/development/GIT_HYGIENE.md"]


def _limit(kind, detail):
    return {"kind": kind, "detail": detail}


def reconciled(report=ACTUAL):
    """A conforming v2 report that keeps the earlier analysis and classifies every item."""
    report = copy.deepcopy(report)
    scope, child = report["scope_assessment"]["limitations"], report["closing_assessments"]["6619"]["limitations"]
    report["scope_assessment"]["limitations"] = [
        _limit("evidence_not_rerun", scope[0]), _limit("ci_not_observed", scope[1]),
        _limit("out_of_scope_followup", scope[2]), _limit("operator_note", scope[3]),
        _limit("operator_note", scope[4]), _limit("operator_note", scope[5]),
        _limit("out_of_scope_followup", scope[6])]
    report["closing_assessments"]["6619"]["limitations"] = [
        _limit("evidence_not_rerun", child[0]), _limit("ci_not_observed", child[1]),
        _limit("out_of_scope_followup", child[2])]
    report["findings"][0].update(category="documentation", protected_class="none")
    report["owner_doc"].update(outcome="already_updated", updates=[
        {"path": "docs/development/DEV_WORKFLOW.md", "claim": "Coordinator progress judgement (6619) section"},
        {"path": "docs/development/GIT_HYGIENE.md", "claim": "path-reuse refusal and epoch continuity"},
        {"path": "docs/STATUS.md", "claim": "dated non-claiming snapshot"}])
    report["report_contract"] = cycle.REPORT_CONTRACT
    return report


def _cycle(tmp_path, monkeypatch):
    """Real advance/state/stop-lineage logic; only engine, agent-server, sandbox and CI ports are fake."""
    layout, config, server = setup(tmp_path, monkeypatch)
    config[0].update(engine="claude-code", model="claude-opus-5-5", verify_targets=list(ACTUAL["verify_targets"]))
    monkeypatch.setattr(cycle, "native_execution_proof", lambda layout, worker, op, entry, **kw: {
        "operation_id": op, "engine": "claude-code", "model": "claude-opus-5-5", "auth": "claude-subscription",
        "source": "native-session-metadata", "native_session_id": "native", "effort": None,
        "timestamp": "2026-11-14T08:40:00Z", "conversation_id": cycle._mapping(layout, worker)["conversation"]["id"],
        "container_id": cycle._mapping(layout, worker)["container_id"]})
    # The reviewer's material: the PR's changed paths and the exact #6619 closing contract.
    target = layout.checkout("reviewer") / "tests" / "builderops" / "test_epic_workspace_coordination.py"
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text("def test_no_progress_and_false_blocker_trigger_bounded_action(): pass\n")
    material = review_material(paths=ACTUAL["covered_sources"] + OWNER_DOCS,
                               issues={"6619": {"body": "## Acceptance Criteria\n" + CRITERION + "\n"}})
    monkeypatch.setattr(cycle, "_review_context", lambda pr: (
        {"files_digest": "test", "closing_issue_hashes": {}, "check_config_digest": "test"}, material))
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
        old.setattr(cycle, "review_gate", lambda review, expected=None, **kwargs: {"outcome": "pass" if review["verdict"] == "pass"
                    and not review["findings"] else "changes_requested", "blocking": [], "grammar": [],
                    "informational": []}, raising=False)
        tick = cycle.advance(layout, config, fetch=fetch, http=server)
    assert tick["results"][1]["reason"] == PARKED
    saved = cycle._find(layout, 10, identity)
    saved.pop("review_gate", None)  # 9fa8 never persisted a derived gate
    cycle._save(layout, saved)
    return report


def _restart_reviewer(layout, monkeypatch, container):
    """The existing lifecycle's result: the old conversation ended with its container, a new one runs."""
    mapping = cycle._mapping(layout, "reviewer")
    ew._record_worker(layout, 6618, state="running", container_id=container,
                      conversation={**mapping["conversation"], "status": ew.CONVERSATION_ENDED})
    bind_worker_endpoint(layout, monkeypatch, container)


def _posts(server):
    return [c for c in server.calls if c[0] == "POST"]


def _merge_ports(layout, monkeypatch, identity):
    """GitHub, native-authority and merge command ports for the real premerge, merge and readback."""
    child = {"number": 6619, "state": "open", "title": "issue title", "labels": [],
             "body": "## Acceptance Criteria\n" + CRITERION + "\n"}
    parent = {"number": 6618, "state": "open", "title": "parent", "body": "parent", "labels": []}
    issues = {6618: parent, 6619: child}
    authority = {"number": 10, "head_sha": HEAD, "body": "Governing-Issue: #6618", "title": "",
                 "closing_issues": [6619], "governing_issue": 6618,
                 "governing_issue_hashes": cycle.closure._issue_hashes(parent),
                 "coordination_mode": "github-label-only-fallback", "owner": {"mode": "github-label-only-fallback"}}
    monkeypatch.setattr(cycle, "github_fetch", fetch)
    monkeypatch.setattr(cycle, "native_authority", lambda *args: dict(authority))
    monkeypatch.setattr(cycle.closure, "_issue", lambda executor, cwd, repo, number: dict(issues[number]))
    monkeypatch.setattr(cycle.closure, "_closing_issue_references", lambda *args: [6619])
    monkeypatch.setattr(cycle.closure, "_issue_events", lambda *args: [])
    monkeypatch.setattr(cycle.closure, "_closure_evidence", lambda *args: {})
    monkeypatch.setattr(cycle.closure, "_validate_closure_attribution", lambda *args: None)
    monkeypatch.setattr(cycle, "_dispatcher_after_merge", lambda *args: pytest.fail("fallback has no lease"))
    files = [{"filename": path} for path in sorted(ACTUAL["covered_sources"] + OWNER_DOCS)]
    comments, effects = {}, []

    def pages(executor, cwd, endpoint):
        if endpoint.endswith("/files"):
            return files
        if endpoint.endswith("/commits"):
            return [{"commit": {"message": "Implement coordinator progress judgement"}}]
        return [{"body": body, "user": {"login": "RasmusTho"}} for body in comments.get(endpoint.split("/")[2], [])]
    monkeypatch.setattr(cycle, "_api_pages", pages)

    class Executor:
        def __init__(self, **kwargs):
            pass

        def run(self, argv, *, cwd, input_text=None):
            if "POST" in argv:
                effects.append("comment")
                issue = next(value for value in argv if value.endswith("/comments")).split("/")[4]
                comments.setdefault(issue, []).append(next(value[5:] for value in argv if value.startswith("body=")))
            elif "--remove-label" in argv:
                effects.append("label")
            return cycle.subprocess.CompletedProcess(argv, 0, "", "")
    monkeypatch.setattr(cycle, "SubprocessExecutor", Executor)
    merged = {"state": "open"}

    def pr(*args):
        if merged["state"] == "open":
            return {"state": "open", "merged_at": None, "head": {"sha": HEAD}}
        return {"state": "closed", "merged_at": "now", "head": {"sha": HEAD}, "merge_commit_sha": "b" * 40,
                "body": authority["body"], "title": ""}
    monkeypatch.setattr(cycle.closure, "_pr", pr)

    def merge(argv, *, timeout):
        assert argv[:3] == ["gh", "pr", "merge"] and "--match-head-commit" in argv and HEAD in argv
        assert cycle._find(layout, 10, identity)["merge_intent"]["closing_issues"] == [6619]
        effects.append("merge")
        merged["state"] = "closed"
        child["state"] = "closed"
        return cycle.subprocess.CompletedProcess(argv, 0, "", "")
    monkeypatch.setattr(cycle, "_command", merge)
    return effects


def test_f1_actual_record_reconciles_once_then_reaches_guarded_merge_and_readback(tmp_path, monkeypatch):
    layout, config, server, identity, cid, calls = _cycle(tmp_path, monkeypatch)
    original = _parked_by_9fa8(layout, config, server, identity, cid, monkeypatch)
    parked = cycle._find(layout, 10, identity)
    op1, stop1 = parked["review_operation"], parked["stop_intent"]
    assert cycle.review_gate(original)["outcome"] == "reconcile_report"

    # Restart on the repaired controller: one reconciliation is recorded and reserved, nothing is re-run.
    for _ in range(3):
        reason = cycle.advance(layout, config, fetch=fetch, http=server)["results"][1]["reason"]
        assert reason.startswith("report reconciliation pr-completion-") and "takeover and start lifecycle" in reason
    saved = cycle._find(layout, 10, identity)
    [row] = saved["report_reconciliations"]
    assert row["archived"]["review"] == original and row["archived"]["stop_intent"] == stop1
    assert row["archived"]["review_operation"] == op1 and row["operation"] == saved["review_operation"] != op1
    assert "review" not in saved and calls == ["stop"] and len(_posts(server)) == 1
    requests = [r for r in ew._load_state(layout)["dispatch_decisions"] if r.get("kind") == "openhands_pr_completion"]
    assert [r["attempt"] for r in requests] == [1, 2]

    # The reviewer runs again through the lifecycle; exactly one reconciliation conversation starts.
    _restart_reviewer(layout, monkeypatch, "e" * 64)
    for _ in range(2):
        cycle.advance(layout, config, fetch=fetch, http=server)
    [first, second] = _posts(server)
    prompt = second[3]["initial_message"]["content"][0]["text"]
    assert cycle.REPORT_CONTRACT in prompt and row["original_report_sha256"] in prompt
    assert json.dumps(original, sort_keys=True) in prompt and "ci_not_observed" in prompt
    cid2 = second[3]["conversation_id"]
    server.conversations[cid2]["execution_status"] = "finished"
    report = _finish(server, cid2, identity, reconciled())
    pending = cycle._find(layout, 10, identity)["report_reconciliations"][0]
    config[0]["review_disposition"] = synthetic_disposition(report, pending)

    effects = _merge_ports(layout, monkeypatch, identity)
    result = cycle.advance(layout, config, fetch=fetch, http=server)
    assert result["results"][1]["action"] == "merged", result
    assert calls == ["stop", "stop", "sandbox", "ci", "ci"]  # review-stage CI, then the premerge CI gate
    assert effects == ["merge", "comment", "comment"]
    saved = cycle._find(layout, 10, identity)
    assert saved["review"] == report and saved["review_gate"]["outcome"] == "pass"
    assert saved["reconciled"] is True and saved["merged_sha"] == "b" * 40
    assert saved["stop_intent"]["previous_stop_id"] == stop1["stop_id"]
    assert saved["report_reconciliations"][0]["archived"]["review"] == original  # still verbatim
    assert "owner docs updated in this PR: docs/development/DEV_WORKFLOW.md" in saved["merge_intent"]["owner_doc_receipt"]
    cycle.advance(layout, config, fetch=fetch, http=server)
    assert effects == ["merge", "comment", "comment"] and len(_posts(server)) == 2


def test_f1_genuine_gap_from_reconciliation_stays_blocking(tmp_path, monkeypatch):
    """A reconciler that files the alternating-mode note as a P2 defect keeps the PR blocked."""
    layout, config, server, identity, cid, calls = _cycle(tmp_path, monkeypatch)
    _parked_by_9fa8(layout, config, server, identity, cid, monkeypatch)
    cycle.advance(layout, config, fetch=fetch, http=server)
    _restart_reviewer(layout, monkeypatch, "e" * 64)
    cycle.advance(layout, config, fetch=fetch, http=server)
    cid2 = _posts(server)[1][3]["conversation_id"]
    server.conversations[cid2]["execution_status"] = "finished"
    report = reconciled()
    report["scope_assessment"]["limitations"].pop(3)
    report["findings"].append({"severity": "P2", "category": "correctness", "protected_class": "none",
                               "summary": ACTUAL["scope_assessment"]["limitations"][3], "file": "app/builderops/epic_coordination.py",
                               "line": 1, "failure_scenario": "Alternating modes reset the ladder."})
    _finish(server, cid2, identity, report)
    for _ in range(2):
        assert cycle.advance(layout, config, fetch=fetch, http=server)["results"][1]["reason"] == PARKED
    assert calls == ["stop", "stop"] and len(_posts(server)) == 2
    assert cycle._find(layout, 10, identity)["review_gate"]["blocking"] == [
        "finding 1: P2 without verified Known Defects disposition"]


def test_f1_nonconforming_reconciliation_is_bounded_and_actionable(tmp_path, monkeypatch):
    layout, config, server, identity, cid, calls = _cycle(tmp_path, monkeypatch)
    _parked_by_9fa8(layout, config, server, identity, cid, monkeypatch)
    cycle.advance(layout, config, fetch=fetch, http=server)
    _restart_reviewer(layout, monkeypatch, "e" * 64)
    cycle.advance(layout, config, fetch=fetch, http=server)
    cid2 = _posts(server)[1][3]["conversation_id"]
    server.conversations[cid2]["execution_status"] = "finished"
    _finish(server, cid2, identity, ACTUAL)  # the same legacy shape again
    _restart_reviewer(layout, monkeypatch, "f" * 64)  # even a running reviewer gets no third attempt
    for _ in range(2):
        reason = cycle.advance(layout, config, fetch=fetch, http=server)["results"][1]["reason"]
        assert reason.startswith(f"report reconciliation under {cycle.REPORT_CONTRACT} did not produce")
        assert "owning review workflow must repair it" in reason
    assert len(_posts(server)) == 2 and calls == ["stop", "stop"]
    assert len(cycle._find(layout, 10, identity)["report_reconciliations"]) == 1


def test_f1_reconciliation_survives_crash_after_reservation_without_duplicate_dispatch(tmp_path, monkeypatch):
    layout, config, server, identity, cid, calls = _cycle(tmp_path, monkeypatch)
    _parked_by_9fa8(layout, config, server, identity, cid, monkeypatch)
    cycle.advance(layout, config, fetch=fetch, http=server)
    saved = cycle._find(layout, 10, identity)
    op2 = saved.pop("review_operation")  # the crash lost the record write after the intake reservation
    saved["report_reconciliations"][0]["operation"] = None
    cycle._save(layout, saved)
    _restart_reviewer(layout, monkeypatch, "e" * 64)
    cycle.advance(layout, config, fetch=fetch, http=server)
    saved = cycle._find(layout, 10, identity)
    assert saved["review_operation"] == op2 == saved["report_reconciliations"][0]["operation"]
    assert len(_posts(server)) == 2
    assert len([r for r in ew._load_state(layout)["dispatch_decisions"]
                if r.get("kind") == "openhands_pr_completion"]) == 2


def test_f1_competing_writer_blocks_reconciliation_start(tmp_path, monkeypatch):
    layout, config, server, identity, cid, calls = _cycle(tmp_path, monkeypatch)
    _parked_by_9fa8(layout, config, server, identity, cid, monkeypatch)
    cycle.advance(layout, config, fetch=fetch, http=server)
    ew._record_worker(layout, 6618, state="running", container_id="e" * 64)  # old conversation not ended
    bind_worker_endpoint(layout, monkeypatch, "e" * 64)
    reason = cycle.advance(layout, config, fetch=fetch, http=server)["results"][1]["reason"]
    assert reason == "previous conversation may still write" and len(_posts(server)) == 1


def test_f1_informational_ci_limit_passes_but_gaps_and_owner_doc_omissions_block():
    report = reconciled({**ACTUAL, "identity": "i", "head_sha": HEAD})
    gate = cycle.review_gate(report, disposition=synthetic_disposition(report))
    assert gate["outcome"] == "pass" and [r["severity"] for r in gate["informational"] if "severity" in r] == ["P3"]
    assert {"where": "scope", "limitation": 1, "kind": "ci_not_observed"} in gate["informational"]
    for where, kind in [("scope", "acceptance_gap"), ("scope", "verify_gap"), ("scope", "owner_doc_gap"),
                        ("child", "evidence_gap"), ("child", "source_gap")]:
        changed = copy.deepcopy(report)
        rows = (changed["scope_assessment"] if where == "scope" else changed["closing_assessments"]["6619"])["limitations"]
        rows.append(_limit(kind, "uncovered"))
        assert cycle.review_gate(changed)["outcome"] == "changes_requested", kind
    missing = copy.deepcopy(report)
    missing["owner_doc"] = {**missing["owner_doc"], "outcome": "required_missing"}
    missing["owner_doc"].pop("updates")
    assert cycle.review_gate(missing)["blocking"] == ["owner_doc: required owner-doc update is missing"]
    for change in ({"outcome": "updated"}, {"updates": []},
                   {"updates": [{"path": "docs/elsewhere.md", "claim": "not inspected"}]}):
        changed = copy.deepcopy(report)
        changed["owner_doc"].update(change)
        assert cycle.review_gate(changed)["outcome"] == "reconcile_report", change
    incomplete = copy.deepcopy(report)
    incomplete["closing_assessments"]["6619"]["verify_coverage"] = "incomplete"
    assert cycle.review_gate(incomplete)["outcome"] == "changes_requested"


def test_f1_prompt_states_every_value_the_gate_accepts():
    prompt = cycle._review_prompt({"number": 10, "head_sha": HEAD, "body": "", "governing_issue": {"body": ""},
                                   "review_material": {}}, "identity", [])
    vocabulary = [cycle.REPORT_CONTRACT, *cycle.PROTECTED_CLASSES, *cycle.ADVISORY_CATEGORIES,
                  *cycle.DEFECT_CATEGORIES, *cycle.LIMITATION_KINDS, *cycle.OWNER_DOC_OUTCOMES, "updates", "claim"]
    assert [value for value in vocabulary if value not in prompt] == []


def _v2_finding(**change):
    report = reconciled({**ACTUAL, "identity": "i", "head_sha": HEAD})
    report["findings"][0].update(change)
    return report


@pytest.mark.parametrize("change,outcome", [
    # F2: an explicit protected class blocks whatever the severity label or prose says.
    ({"protected_class": "false_green", "summary": "Merge proceeds when current-head CI failed."}, "changes_requested"),
    ({"protected_class": "contract_failure"}, "changes_requested"),
    ({"protected_class": "secret_or_auth", "severity": "P1"}, "changes_requested"),
    ({"protected_class": "inconclusive"}, "changes_requested"),
    ({"category": "correctness"}, "changes_requested"),  # a defect cannot be P3
    ({"severity": "P0"}, "changes_requested"), ({"severity": "P1"}, "changes_requested"),
    ({"severity": "P2"}, "changes_requested"),
    # Unknown or missing classification fails closed into the bounded reconciliation.
    ({"protected_class": "probably-fine"}, "reconcile_report"), ({"protected_class": None}, "reconcile_report"),
    ({"category": "authoring"}, "reconcile_report"), ({"severity": "p3"}, "reconcile_report"),
    ({"severity": "P4"}, "reconcile_report"), ({"line": True}, "reconcile_report"),
    ({"protected": False}, "reconcile_report"),
    # Benign P3 prose that mentions CI, merges or receipts is not keyword-scanned.
    ({"summary": "Wording: say 'merged in #6626' and 'current-head CI receipt' consistently."}, "pass"),
    ({"category": "style", "summary": "Rename merge_notes to merge_summary for authoring clarity."}, "pass"),
])
def test_f2_explicit_protected_classification_without_keyword_scanning(change, outcome):
    report = _v2_finding(**change)
    if change.get("protected_class", "absent") is None:
        report["findings"][0].pop("protected_class")
    assert cycle.review_gate(report, disposition=synthetic_disposition(report))["outcome"] == outcome


def test_f2_disguised_protected_p3_cannot_reach_sandbox_or_authority(tmp_path, monkeypatch):
    layout, config, server, identity, cid, calls = _cycle(tmp_path, monkeypatch)
    report = reconciled()
    report["findings"][0].update(category="documentation", protected_class="false_green",
                                 summary="Merge proceeds when current-head CI failed; receipt records green.",
                                 failure_scenario="A failing PR is merged and closure evidence is false-green.")
    _finish(server, cid, identity, report)
    monkeypatch.setattr(cycle, "native_authority", lambda *args: pytest.fail("authority must not be reached"))
    assert cycle.advance(layout, config, fetch=fetch, http=server)["results"][1]["reason"] == PARKED
    assert calls == ["stop"]
    # The legacy shape of the same report has no classification and is reconciled, not passed.
    legacy = copy.deepcopy(ACTUAL)
    legacy["findings"][0].update(category="documentation", summary=report["findings"][0]["summary"])
    assert cycle.review_gate(legacy)["outcome"] == "reconcile_report"


@pytest.mark.parametrize("review", [
    {**ACTUAL, "verdict": "pass"},  # a pass label cannot carry findings past the gate
    {**ACTUAL, "verdict": "findings", "findings": []}, {**ACTUAL, "verdict": "unknown"},
    {**ACTUAL, "verdict": "pass", "findings": []},  # legacy limitations and owner_doc 'updated' are unclassified
    {**reconciled(), "report_contract": "pr_cycle_report.v9"}])
def test_legacy_unknown_and_malformed_reports_reconcile_and_never_pass_premerge(tmp_path, monkeypatch, review):
    layout, config, server, identity, cid, calls = _cycle(tmp_path, monkeypatch)
    assert cycle.review_gate(review)["outcome"] == "reconcile_report"
    saved = {"review": review, "verification": {"passed": True, "head_sha": HEAD, "targets": config[0]["verify_targets"]},
             "execution_proof": {}}
    with pytest.raises(cycle.CycleError, match="review execution or sandbox verification is incomplete|reconcile_report"):
        cycle._premerge(layout, {"number": 10, "head_sha": HEAD}, config[0], saved)


def test_legacy_clean_report_with_nothing_to_classify_still_passes():
    clean = {**ACTUAL, "verdict": "pass", "findings": [], "closing_assessments": {},
             "scope_assessment": {**ACTUAL["scope_assessment"], "limitations": []},
             "owner_doc": {**ACTUAL["owner_doc"], "outcome": "no_change"}}
    gate = cycle.review_gate(clean, disposition=synthetic_disposition(clean))
    assert gate["outcome"] == "pass" and gate["contract"] == "legacy"
    assert gate["blocking"] == gate["grammar"] == gate["informational"] == []
    assert cycle.review_gate({**clean, "findings": [{"severity": "P0"}], "verdict": "findings"})["outcome"] == \
        "changes_requested"


def test_missing_native_proof_does_not_verify_or_reconcile(tmp_path, monkeypatch):
    layout, config, server, identity, cid, calls = _cycle(tmp_path, monkeypatch)
    _finish(server, cid, identity, ACTUAL)

    def unavailable(*args, **kwargs):
        raise cycle.CycleError("native conversation execution is not established")
    monkeypatch.setattr(cycle, "native_execution_proof", unavailable)
    for _ in range(2):
        result = cycle.advance(layout, config, fetch=fetch, http=server)
        assert result["results"][1]["reason"] == "native conversation execution is not established"
    saved = cycle._find(layout, 10, identity)
    assert calls == [] and "execution_proof" not in saved and "report_reconciliations" not in saved


def test_stale_head_does_not_reuse_or_reconcile_record(tmp_path, monkeypatch):
    layout, config, server, identity, cid, calls = _cycle(tmp_path, monkeypatch)
    _parked_by_9fa8(layout, config, server, identity, cid, monkeypatch)
    moved = lambda path, timeout: (lambda r: (r[0], r[1].replace(HEAD.encode(), b"e" * 40)))(fetch(path, timeout))
    result = cycle.advance(layout, config, fetch=moved, http=server)
    assert result["results"][1]["reason"] == "not admitted at this head"
    assert calls == ["stop"] and "report_reconciliations" not in cycle._find(layout, 10, identity)


def test_held_peer_stays_held_while_reconciliation_progresses(tmp_path, monkeypatch):
    layout, config, server, identity, cid, calls = _cycle(tmp_path, monkeypatch)
    _parked_by_9fa8(layout, config, server, identity, cid, monkeypatch)
    result = cycle.advance(layout, config, fetch=fetch, http=server)
    assert result["results"][0] == {"number": 9, "action": "wait", "reason": "not admitted at this head"}
    assert result["results"][1]["reason"].startswith("report reconciliation")


EXPECTED = {"identity": "i", "head_sha": HEAD, "verify_targets": ACTUAL["verify_targets"],
            "sources": ACTUAL["covered_sources"], "paths": sorted(ACTUAL["covered_sources"] + OWNER_DOCS),
            "criteria": {"6619": ["0b593f5f25fe8621cfa28943c44099a16503e13bcdc00d75f6910e384d0858ff"]}}


@pytest.mark.parametrize("defect", ["missing-child", "wrong-hash", "missing-source", "extra-child", "identity"])
def test_review_stage_checks_coverage_against_the_reviewed_contract(tmp_path, monkeypatch, defect):
    """Coverage the premerge would reject is classified at review, so no sandbox/CI loop can park."""
    report = reconciled()
    if defect == "missing-child":
        report["closing_assessments"] = {}
    elif defect == "wrong-hash":
        rows = report["closing_assessments"]["6619"]["criteria"]
        rows["f" * 64] = rows.pop(next(iter(rows)))
    elif defect == "missing-source":
        report["covered_sources"] = report["covered_sources"][1:]
    elif defect == "extra-child":
        report["closing_assessments"]["6618"] = report["closing_assessments"]["6619"]
    bound = {**report, "identity": "i", "head_sha": HEAD}
    assert cycle.review_gate(bound, EXPECTED, disposition=synthetic_disposition(bound))["outcome"] == (
        "pass" if defect == "identity" else "reconcile_report")
    if defect == "identity":
        assert cycle.review_gate({**report, "identity": "other", "head_sha": HEAD}, EXPECTED)["outcome"] == \
            "reconcile_report"
        return
    layout, config, server, identity, cid, calls = _cycle(tmp_path, monkeypatch)
    _finish(server, cid, identity, report)
    for _ in range(3):
        reason = cycle.advance(layout, config, fetch=fetch, http=server)["results"][1]["reason"]
        assert reason.startswith("report reconciliation pr-completion-")
    assert calls == ["stop"]  # no sandbox and no repeated CI polling


@pytest.mark.parametrize("text", [
    json.dumps({**ACTUAL, "verdict": "pass"}), json.dumps({**reconciled(), "notes": "extra"}),
    json.dumps({**reconciled(), "verify_targets": []}), "Review done, but no report object.",
    "x" * 65537])
def test_malformed_finished_report_is_reconciled_through_the_real_reader(tmp_path, monkeypatch, text):
    layout, config, server, identity, cid, calls = _cycle(tmp_path, monkeypatch)
    try:
        body = {**json.loads(text), "identity": identity, "head_sha": HEAD}
        text = json.dumps(body)
    except ValueError:
        pass
    server.final_responses[cid] = text
    reason = cycle.advance(layout, config, fetch=fetch, http=server)["results"][1]["reason"]
    assert reason.startswith("report reconciliation pr-completion-") and calls == ["stop"]
    [row] = cycle._find(layout, 10, identity)["report_reconciliations"]
    archived = row["archived"]["review"]
    assert archived == body if text.startswith("{") else set(archived) == {"unreadable_report_sha256", "unreadable_report_text"}
    assert row["original_operation"] != row["operation"]


def test_empty_final_response_is_not_a_terminal_report(tmp_path, monkeypatch):
    layout, config, server, identity, cid, calls = _cycle(tmp_path, monkeypatch)
    server.final_responses[cid] = "  "
    cycle.advance(layout, config, fetch=fetch, http=server)
    assert calls == [] and "report_reconciliations" not in cycle._find(layout, 10, identity)


def test_crash_before_intake_cannot_spend_reconciliation_on_the_original_operation(tmp_path, monkeypatch):
    layout, config, server, identity, cid, calls = _cycle(tmp_path, monkeypatch)
    _finish(server, cid, identity, ACTUAL)
    real = cycle.completion.intake
    crashed = []

    def intake(*args, **kwargs):
        if not crashed:
            crashed.append(True)
            raise OSError("controller interrupted")
        return real(*args, **kwargs)
    monkeypatch.setattr(cycle.completion, "intake", intake)
    assert cycle.advance(layout, config, fetch=fetch, http=server)["results"][1]["reason"] == "controller interrupted"
    cycle.advance(layout, config, fetch=fetch, http=server)
    saved = cycle._find(layout, 10, identity)
    [row] = saved["report_reconciliations"]
    assert row["operation"] and row["operation"] != row["original_operation"] == row["archived"]["review_operation"]
    requests = [(r["attempt"], r["outcome"]) for r in ew._load_state(layout)["dispatch_decisions"]
                if r.get("kind") == "openhands_pr_completion"]
    assert requests == [(1, "completed"), (2, "unknown")]
    _restart_reviewer(layout, monkeypatch, "e" * 64)
    cycle.advance(layout, config, fetch=fetch, http=server)
    assert len(_posts(server)) == 2 and calls == ["stop"]


def test_owner_doc_update_outside_the_changed_paths_reconciles_before_sandbox(tmp_path, monkeypatch):
    layout, config, server, identity, cid, calls = _cycle(tmp_path, monkeypatch)
    report = reconciled()
    report["owner_doc"]["inspected_paths"].append("docs/development/PR_HOT_PATH.md")
    report["owner_doc"]["updates"].append({"path": "docs/development/PR_HOT_PATH.md", "claim": "not changed"})
    _finish(server, cid, identity, report)
    for _ in range(3):
        assert cycle.advance(layout, config, fetch=fetch, http=server)["results"][1]["reason"].startswith(
            "report reconciliation pr-completion-")
    assert calls == ["stop"]


@pytest.mark.parametrize("path,value", [
    (("owner_doc", "outcome"), ["no_change"]), (("scope_assessment", "limitations"), [{"kind": [], "detail": "x"}]),
    (("findings",), [{**reconciled()["findings"][0], "protected_class": ["none"]}]), (("findings",), [{"severity": []}])])
def test_wrong_typed_fields_reconcile_instead_of_crashing(tmp_path, monkeypatch, path, value):
    report = reconciled()
    target = report
    for key in path[:-1]:
        target = target[key]
    target[path[-1]] = value
    assert cycle.review_gate({**report, "identity": "i", "head_sha": HEAD}, EXPECTED)["outcome"] == "reconcile_report"
    layout, config, server, identity, cid, calls = _cycle(tmp_path, monkeypatch)
    _finish(server, cid, identity, report)
    reason = cycle.advance(layout, config, fetch=fetch, http=server)["results"][1]["reason"]
    assert reason.startswith("report reconciliation pr-completion-") and calls == ["stop"]


def test_findings_bound_to_other_content_reconcile_rather_than_route_repair():
    report = {**reconciled(), "identity": "other", "head_sha": HEAD}
    report["findings"][0]["severity"] = "P0"
    assert cycle.review_gate(report, EXPECTED)["outcome"] == "reconcile_report"
    assert cycle.review_gate({**report, "identity": "i"}, EXPECTED)["outcome"] == "changes_requested"


def test_unreadable_answer_text_is_kept_bounded_for_audit_and_the_reconciler(tmp_path, monkeypatch):
    layout, config, server, identity, cid, calls = _cycle(tmp_path, monkeypatch)
    server.final_responses[cid] = "Found a CI bypass; report omitted. " + "y" * 70000
    cycle.advance(layout, config, fetch=fetch, http=server)
    archived = cycle._find(layout, 10, identity)["report_reconciliations"][0]["archived"]["review"]
    assert archived["unreadable_report_text"].startswith("Found a CI bypass")
    assert len(archived["unreadable_report_text"]) == 65536


def test_uncovered_closing_verify_target_is_an_explicit_admission_wait_before_sandbox(tmp_path, monkeypatch):
    layout, config, server, identity, cid, calls = _cycle(tmp_path, monkeypatch)
    _finish(server, cid, identity, reconciled())
    config[0]["verify_targets"] = [t for t in config[0]["verify_targets"] if "coordination" not in t]
    # The admission no longer covers #6619's Verify target; the identity changes, so use the gate seam.
    with pytest.raises(cycle.CycleError, match="not covered by the admitted Verify targets"):
        cycle.report_expectations(layout, config[0], {"head_sha": HEAD, "review_material": cycle._review_context({})[1]},
                                  identity)


def test_changed_paths_come_from_the_files_api_list_not_diff_headers(tmp_path, monkeypatch):
    """Non-ASCII and ' b/' paths: the review stage uses the same filenames premerge re-reads."""
    layout, config, server, identity, cid, calls = _cycle(tmp_path, monkeypatch)
    material = {"diff": 'diff --git "a/app/\\303\\251.py" "b/app/\\303\\251.py"\n', "issues": {},
                "paths": ["app/x b/c.py", "app/\u00e9.py", "docs/x.md"]}
    got = cycle.report_expectations(layout, config[0], {"head_sha": HEAD, "review_material": material}, identity)
    assert got["paths"] == sorted(material["paths"]) and got["sources"] == ["app/x b/c.py", "app/\u00e9.py"]
    with pytest.raises(cycle.CycleError, match="review material is unavailable"):
        cycle.report_expectations(layout, config[0], {"head_sha": HEAD, "review_material": {"diff": "", "issues": {}}},
                                  identity)
