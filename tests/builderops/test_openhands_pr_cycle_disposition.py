"""Owner-bound review dispositions; all engine, CI, merge and authority ports are synthetic."""
import copy
import hashlib
import json

import pytest

from app.builderops import epic_workspace as ew
from app.builderops import openhands_pr_cycle as cycle
from tests.builderops import test_openhands_pr_cycle_p3_gate as prior
from tests.builderops.test_openhands_pr_cycle import (
    HEAD, fake_completed_review_stop, fetch, review_material, setup,
)


def digest(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(",", ":")).encode()).hexdigest()


def report_items(report):
    result = [("findings", i, row) for i, row in enumerate(report["findings"])]
    result += [("scope", i, row) for i, row in enumerate(report["scope_assessment"]["limitations"])]
    for number, child in report["closing_assessments"].items():
        result += [(f"closing:{number}", i, row) for i, row in enumerate(child["limitations"])]
    return result


def matching_original(where, original, current):
    if where == "findings":
        return all(current.get(key) == original.get(key) for key in
                   ("severity", "summary", "file", "line", "failure_scenario"))
    return current.get("detail") == original if isinstance(original, str) else current == original


def owner_disposition(report, pending=None):
    """A synthetic trusted owner describes its item decisions, not a reviewer-supplied claim."""
    current = report_items(report)
    rows = [{"report": "current", "where": where, "index": index, "sha256": digest(item),
             "decision": "nonblocking", "rationale": "Synthetic owner assessed this item against the closing contract."}
            for where, index, item in current]
    original_digest = original_attempt_digest = None
    if pending is not None:
        original = pending["archived"]["review"]
        original_digest = digest(original)
        original_attempt_digest = digest(pending["archived"])
        for where, index, item in report_items(original):
            row = {"report": "original", "where": where, "index": index, "sha256": digest(item),
                   "rationale": "Synthetic owner inspected the original item against the closing contract."}
            match = next(((w, i, v) for w, i, v in current
                          if w == where and matching_original(where, item, v)), None)
            if match is not None:
                row.update(decision="retained", successor={"where": match[0], "index": match[1],
                                                          "sha256": digest(match[2])})
            else:
                row["decision"] = "nonblocking"
            rows.append(row)
    return {"identity": report["identity"], "head_sha": report["head_sha"], "report_sha256": digest(report),
            "original_report_sha256": original_digest, "original_attempt_sha256": original_attempt_digest,
            "assessment": "Synthetic owner checked the entire report and its closing obligations.", "items": rows}


def known_legacy_report():
    """Legacy item classifications with a supported, explicit owner-doc outcome."""
    report = copy.deepcopy(prior.ACTUAL)
    report["owner_doc"] = copy.deepcopy(prior.reconciled()["owner_doc"])
    return report


def case(tmp_path, monkeypatch):
    layout, config, server = setup(tmp_path, monkeypatch)
    config[0].update(engine="codex", model="gpt-6.1-terra", verify_targets=list(prior.ACTUAL["verify_targets"]))
    target = layout.checkout("reviewer") / "tests/builderops/test_epic_workspace_coordination.py"
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text("def test_no_progress_and_false_blocker_trigger_bounded_action(): pass\n")
    material = review_material(paths=prior.ACTUAL["covered_sources"] + prior.OWNER_DOCS,
                               issues={"6619": {"body": "## Acceptance Criteria\n" + prior.CRITERION + "\n"}})
    monkeypatch.setattr(cycle, "_review_context", lambda pr: (
        {"files_digest": "synthetic", "closing_issue_hashes": {}, "check_config_digest": "synthetic"}, material))

    def proof(layout, worker, operation, entry, **kwargs):
        mapping = cycle._mapping(layout, worker)
        return {"operation_id": operation, "engine": "codex", "model": "gpt-6.1-terra", "auth": "chatgpt",
                "source": "native-session-metadata", "native_session_id": "synthetic", "effort": "max",
                "timestamp": "2026-11-14T11:00:00Z", "conversation_id": mapping["conversation"]["id"],
                "container_id": mapping["container_id"]}

    monkeypatch.setattr(cycle, "native_execution_proof", proof)
    calls = []
    monkeypatch.setattr(ew, "stop_worker", lambda layout, worker, **kw:
                        calls.append("stop") or fake_completed_review_stop(layout, worker, **kw))
    monkeypatch.setattr(cycle, "sandbox_verify", lambda layout, worker, head, targets, venv, saved:
                        calls.append("sandbox") or {"head_sha": head, "targets": targets, "passed": True})
    monkeypatch.setattr(cycle, "ci_once", lambda *args: calls.append("ci") or {"exit_code": 0})
    cycle.advance(layout, config, fetch=fetch, http=server)
    state = ew._load_state(layout)
    record = next(row for row in state["compact_receipts"] if row.get("kind") == "pr_cycle")
    cid = state["issue_mappings"]["6618"]["conversation"]["id"]
    server.conversations[cid]["execution_status"] = "finished"
    return layout, config, server, record["identity"], cid, calls


def finish_original_and_retry(layout, config, server, identity, cid, monkeypatch, original=None):
    original = prior._finish(server, cid, identity, original if original is not None else known_legacy_report())
    cycle.advance(layout, config, fetch=fetch, http=server)
    pending = copy.deepcopy(cycle._find(layout, 10, identity)["report_reconciliations"][0])
    prior._restart_reviewer(layout, monkeypatch, "e" * 64)
    cycle.advance(layout, config, fetch=fetch, http=server)
    cid2 = prior._posts(server)[1][3]["conversation_id"]
    server.conversations[cid2]["execution_status"] = "finished"
    return original, pending, cid2


def test_false_green_p3_cannot_self_authorize_or_reach_any_effect(tmp_path, monkeypatch):
    layout, config, server, identity, cid, calls = case(tmp_path, monkeypatch)
    report = prior.reconciled()
    report["findings"][0].update(category="documentation", severity="P3", protected_class="none",
                                 summary="The merge gate marks a failing CI result as green.",
                                 failure_scenario="A failed current-head check produces false-green merge and closure evidence.")
    report = prior._finish(server, cid, identity, report)
    result = cycle.advance(layout, config, fetch=fetch, http=server)
    saved = cycle._find(layout, 10, identity)
    assert result["results"][1]["action"] == "wait"
    assert saved["review_gate"]["outcome"] == "changes_requested"
    assert "owner disposition" in saved["review_gate"]["blocking"][0]
    assert calls == ["stop"] and "verification" not in saved and "merge_intent" not in saved
    # Neither a reviewer field nor an audit-copy forged in run state supplies controller authority.
    forged = owner_disposition(report)
    assert cycle.review_gate({**report, "review_disposition": forged})["outcome"] != "pass"
    saved["review_disposition"] = forged
    cycle._save(layout, saved)
    cycle.advance(layout, config, fetch=fetch, http=server)
    assert calls == ["stop"] and cycle._find(layout, 10, identity)["review_gate"]["outcome"] == "changes_requested"
    # Even a fabricated passing test receipt cannot bypass the independent premerge check.
    saved["verification"] = {"passed": True, "head_sha": HEAD, "targets": config[0]["verify_targets"]}
    _, material = cycle._review_context({})
    monkeypatch.setattr(cycle, "native_authority", lambda *args: pytest.fail("authority must not be reached"))
    with pytest.raises(cycle.CycleError, match="review report gate is changes_requested"):
        cycle._premerge(layout, {"number": 10, "head_sha": HEAD, "review_material": material}, config[0], saved)


def test_original_unclassified_false_green_cannot_vanish_in_retry(tmp_path, monkeypatch):
    layout, config, server, identity, cid, calls = case(tmp_path, monkeypatch)
    original = copy.deepcopy(prior.ACTUAL)
    original["findings"][0].update(category="documentation", severity="P3",
                                   summary="The merge gate marks a failing CI result as green.",
                                   failure_scenario="Failed current-head CI produces false-green merge and closure evidence.")
    original, pending, cid2 = finish_original_and_retry(layout, config, server, identity, cid, monkeypatch, original)
    successor = prior.reconciled()
    successor["findings"] = []
    successor["verdict"] = "pass"
    successor["scope_assessment"]["limitations"] = []
    successor["closing_assessments"]["6619"]["limitations"] = []
    prior._finish(server, cid2, identity, successor)
    result = cycle.advance(layout, config, fetch=fetch, http=server)
    saved = cycle._find(layout, 10, identity)
    assert result["results"][1]["action"] == "wait"
    assert saved["review_gate"]["outcome"] == "changes_requested"
    assert saved["report_reconciliations"][0]["archived"] == pending["archived"]
    assert saved["report_reconciliations"][0]["archived"]["review"] == original
    assert calls == ["stop", "stop"] and "verification" not in saved and "merge_intent" not in saved


def test_clean_labels_do_not_hide_contradictory_scope_prose():
    report = prior.reconciled({**prior.ACTUAL, "identity": "identity", "head_sha": HEAD})
    report["findings"] = []
    report["verdict"] = "pass"
    report["scope_assessment"]["limitations"] = []
    report["closing_assessments"]["6619"]["limitations"] = []
    report["scope_assessment"]["verify_coverage"] = "A failed current-head CI check is accepted as green."
    assert cycle.review_gate(report)["outcome"] == "changes_requested"


@pytest.mark.parametrize("where", ["findings", "scope", "closing:6619"])
def test_original_item_cannot_be_silently_deleted(tmp_path, monkeypatch, where):
    layout, config, server, identity, cid, calls = case(tmp_path, monkeypatch)
    original, pending, cid2 = finish_original_and_retry(layout, config, server, identity, cid, monkeypatch)
    successor = prior.reconciled()
    if where == "findings":
        successor["findings"] = []
        successor["verdict"] = "pass"
    elif where == "scope":
        successor["scope_assessment"]["limitations"].pop(1)
    else:
        successor["closing_assessments"]["6619"]["limitations"].pop(1)
    successor = prior._finish(server, cid2, identity, successor)
    # Omit precisely the deleted original from an otherwise owner-bound manifest.
    manifest = owner_disposition(successor, pending)
    manifest["items"] = [row for row in manifest["items"] if not
                         (row["report"] == "original" and row["where"] == where and
                          row["decision"] == "nonblocking")]
    config[0]["review_disposition"] = manifest
    cycle.advance(layout, config, fetch=fetch, http=server)
    saved = cycle._find(layout, 10, identity)
    assert saved["review_gate"]["outcome"] == "changes_requested"
    assert "every original and current item" in saved["review_gate"]["blocking"][0]
    assert saved["report_reconciliations"][0]["archived"] == pending["archived"]
    assert pending["archived"]["review"] == original
    assert calls == ["stop", "stop"] and "verification" not in saved and "merge_intent" not in saved


def test_owning_session_can_explicitly_dispose_of_safe_deleted_item(tmp_path, monkeypatch):
    layout, config, server, identity, cid, calls = case(tmp_path, monkeypatch)
    _, pending, cid2 = finish_original_and_retry(layout, config, server, identity, cid, monkeypatch)
    successor = prior.reconciled()
    successor["scope_assessment"]["limitations"].pop(1)  # CI is separately required at the live gate.
    successor = prior._finish(server, cid2, identity, successor)
    config[0]["review_disposition"] = owner_disposition(successor, pending)
    for row in config[0]["review_disposition"]["items"]:
        if row["report"] == "original" and row["where"] == "scope" and row["index"] == 1:
            assert row["decision"] == "nonblocking"
            row["rationale"] = "Current-head CI is required separately at both CI gates before the guarded merge."
    effects = prior._merge_ports(layout, monkeypatch, identity)
    result = cycle.advance(layout, config, fetch=fetch, http=server)
    assert result["results"][1]["action"] == "merged"
    assert calls == ["stop", "stop", "sandbox", "ci", "ci"]
    assert effects == ["merge", "comment", "comment"]


def test_known_legacy_p3_progresses_only_after_bound_owner_disposition(tmp_path, monkeypatch):
    layout, config, server, identity, cid, calls = case(tmp_path, monkeypatch)
    original, pending, cid2 = finish_original_and_retry(layout, config, server, identity, cid, monkeypatch)
    successor = prior._finish(server, cid2, identity, prior.reconciled())
    cycle.advance(layout, config, fetch=fetch, http=server)
    saved = cycle._find(layout, 10, identity)
    assert saved["review_gate"]["outcome"] == "changes_requested" and calls == ["stop", "stop"]
    assert saved["disposition_request"]["original_report_sha256"] == digest(original)
    assert all("decision" not in row for row in saved["disposition_request"]["items"])
    actual_pending = saved["report_reconciliations"][0]
    manifest = owner_disposition(successor, actual_pending)
    for row in manifest["items"]:
        if row["where"] == "findings":
            row["rationale"] = ("Synthetic owner checked the incorrect source-PR reference as an informational "
                                "documentation correction; it does not excuse any acceptance or CI obligation.")
    config[0]["review_disposition"] = manifest
    effects = prior._merge_ports(layout, monkeypatch, identity)
    result = cycle.advance(layout, config, fetch=fetch, http=server)
    saved = cycle._find(layout, 10, identity)
    assert result["results"][1]["action"] == "merged"
    assert calls == ["stop", "stop", "sandbox", "ci", "ci"] and effects == ["merge", "comment", "comment"]
    assert saved["report_reconciliations"][0]["archived"] == pending["archived"]
    assert saved["report_reconciliations"][0]["archived"]["review"] == original
    assert saved["review_disposition"] == manifest
    assert saved["verification"]["disposition_sha256"] == digest(manifest)
    assert saved["stop_intent"]["previous_stop_id"] == pending["archived"]["stop_intent"]["stop_id"]


def test_changed_archived_checkpoint_stops_before_verification(tmp_path, monkeypatch):
    layout, config, server, identity, cid, calls = case(tmp_path, monkeypatch)
    _, _, cid2 = finish_original_and_retry(layout, config, server, identity, cid, monkeypatch)
    successor = prior._finish(server, cid2, identity, prior.reconciled())
    saved = cycle._find(layout, 10, identity)
    pending = saved["report_reconciliations"][0]
    manifest = owner_disposition(successor, pending)
    pending["archived"]["stop_intent"]["checkpoint"]["ref"] = "changed-after-stop"
    cycle._save(layout, saved)
    config[0]["review_disposition"] = manifest
    result = cycle.advance(layout, config, fetch=fetch, http=server)
    saved = cycle._find(layout, 10, identity)
    assert result["results"][1]["action"] == "wait"
    assert "archive changed" in saved["review_gate"]["blocking"][0]
    assert calls == ["stop", "stop"] and "verification" not in saved and "merge_intent" not in saved


@pytest.mark.parametrize("drift", ["contract", "missing_archive", "missing_reservation", "wrong_attempt", "third"])
def test_unknown_retry_history_cannot_be_treated_as_a_first_review(tmp_path, monkeypatch, drift):
    layout, config, server, identity, cid, calls = case(tmp_path, monkeypatch)
    _, _, cid2 = finish_original_and_retry(layout, config, server, identity, cid, monkeypatch)
    successor = prior._finish(server, cid2, identity, prior.reconciled())
    saved = cycle._find(layout, 10, identity)
    pending = saved["report_reconciliations"][0]
    config[0]["review_disposition"] = owner_disposition(successor, pending)
    if drift in ("contract", "missing_archive"):
        if drift == "contract":
            pending["contract"] = "unknown"
        else:
            saved.pop("report_reconciliations")
        cycle._save(layout, saved)
    else:
        def alter(state):
            for row in list(state["dispatch_decisions"]):
                if row.get("operation_id") == pending["original_operation"]:
                    if drift == "missing_reservation":
                        row["operation_id"] = "missing"
                    elif drift == "wrong_attempt":
                        row["attempt"] = 2
                    else:
                        state["dispatch_decisions"].append({**row, "operation_id": "third-op", "attempt": 3})
            return state
        cycle.epic_run_state.update_epic_run_state(layout.run_id, root=layout.run_state_dir,
                                                   expected_epic_issue_number=6615, updater=alter)
    result = cycle.advance(layout, config, fetch=fetch, http=server)
    saved = cycle._find(layout, 10, identity)
    assert result["results"][1]["action"] == "wait"
    assert "history" in result["results"][1]["reason"] or "lineage" in result["results"][1]["reason"]
    assert calls == (["stop"] if drift == "contract" else ["stop", "stop"])
    assert "verification" not in saved and "merge_intent" not in saved


@pytest.mark.parametrize("during", ["sandbox", "ci"])
def test_changed_disposition_cannot_authorize_later_effects(tmp_path, monkeypatch, during):
    layout, config, server, identity, cid, calls = case(tmp_path, monkeypatch)
    report = prior._finish(server, cid, identity, prior.reconciled())
    manifest = owner_disposition(report)
    config[0]["review_disposition"] = manifest
    effects = prior._merge_ports(layout, monkeypatch, identity)
    if during == "sandbox":
        def sandbox(layout, worker, head, targets, venv, saved):
            calls.append("sandbox")
            manifest["assessment"] = "The owner changed the assessment while verification was running."
            return {"head_sha": head, "targets": targets, "passed": True}
        monkeypatch.setattr(cycle, "sandbox_verify", sandbox)
    else:
        def ci(*args):
            calls.append("ci")
            manifest["assessment"] = "The owner changed the assessment while CI was running."
            return {"exit_code": 0}
        monkeypatch.setattr(cycle, "ci_once", ci)
    result = cycle.advance(layout, config, fetch=fetch, http=server)
    saved = cycle._find(layout, 10, identity)
    assert result["results"][1]["action"] == "wait" and effects == []
    assert calls == (["stop", "sandbox"] if during == "sandbox" else ["stop", "sandbox", "ci"])
    assert "merge_intent" not in saved
    if during == "sandbox":
        assert "verification" not in saved


def make_bound_reports():
    original = {**known_legacy_report(), "identity": "identity", "head_sha": HEAD}
    current = prior.reconciled(original)
    archive = {"review": original, "review_operation": "old-op", "execution_proof": {
        "operation_id": "old-op", "conversation_id": "old-conversation", "container_id": "d" * 64,
        "engine": "codex", "model": "gpt-6.1-terra", "auth": "chatgpt", "source": "native-session-metadata",
        "native_session_id": "synthetic", "timestamp": "2026-11-14T11:00:00Z", "effort": "max"},
        "public_report_conversation": "old-conversation", "conversation_provenance": {"reviewer": "old-conversation"},
        "stop_intent": {"stop_id": "1" * 32, "checkpoint": {"ref": "saved"}, "previous_stop_id": None,
                        "container_id": "d" * 64,
                        "assignment": {"runtime": "openhands", "container_id": "d" * 64,
                                       "conversation": {"id": "old-conversation"}}}, "stop_verified": True}
    pending = {"contract": cycle.REPORT_CONTRACT, "identity": "identity", "head_sha": HEAD,
               "original_operation": "old-op", "original_report_sha256": digest(original),
               "original_attempt_sha256": digest(archive), "operation": "new-op", "archived": archive}
    return current, pending, owner_disposition(current, pending)


@pytest.mark.parametrize("change", [
    lambda d: d.update(identity="other"), lambda d: d.update(head_sha="b" * 40),
    lambda d: d.update(report_sha256="0" * 64), lambda d: d.update(original_report_sha256="0" * 64),
    lambda d: d.update(original_attempt_sha256="0" * 64),
    lambda d: d.update(assessment=" "), lambda d: d.update(assessment="looks fine"),
    lambda d: d["items"][0].update(rationale=""), lambda d: d["items"][0].update(rationale="OK"),
    lambda d: d["items"][0].update(sha256="0" * 64), lambda d: d["items"][0].update(index=999),
    lambda d: d["items"].append(copy.deepcopy(d["items"][0])),
    lambda d: d["items"].pop(),
])
def test_owner_disposition_requires_exact_binding_and_item_coverage(change):
    report, pending, disposition = make_bound_reports()
    assert cycle.review_gate(report, disposition=disposition, reconciliation=pending)["outcome"] == "pass"
    change(disposition)
    assert cycle.review_gate(report, disposition=disposition, reconciliation=pending)["outcome"] != "pass"


@pytest.mark.parametrize("change", [
    lambda p: p.update(identity="wrong"), lambda p: p.update(head_sha="b" * 40),
    lambda p: p.update(original_report_sha256="0" * 64), lambda p: p.update(operation="old-op"),
    lambda p: p["archived"]["execution_proof"].update(operation_id="different"),
    lambda p: p["archived"]["execution_proof"].update(conversation_id="different"),
    lambda p: p["archived"]["stop_intent"]["checkpoint"].update(ref="different"),
    lambda p: p["archived"].update(stop_verified=False),
    lambda p: p["archived"]["stop_intent"].pop("checkpoint"),
])
def test_unknown_original_lineage_fails_closed(change):
    report, pending, disposition = make_bound_reports()
    change(pending)
    assert cycle.review_gate(report, disposition=disposition, reconciliation=pending)["outcome"] != "pass"


@pytest.mark.parametrize("change", [
    lambda item: item.update(severity="P1"), lambda item: item.update(severity="P2"),
    lambda item: item.update(protected_class="false_green"), lambda item: item.update(category="correctness"),
])
def test_explicit_original_protected_or_defect_obligation_cannot_be_softened(change):
    report, pending, _ = make_bound_reports()
    change(pending["archived"]["review"]["findings"][0])
    pending["original_report_sha256"] = digest(pending["archived"]["review"])
    pending["original_attempt_sha256"] = digest(pending["archived"])
    disposition = owner_disposition(report, pending)
    assert cycle.review_gate(report, disposition=disposition, reconciliation=pending)["outcome"] != "pass"


@pytest.mark.parametrize("where", ["findings", "scope", "closing:6619"])
def test_retained_original_item_cannot_be_rewritten(where):
    report, pending, _ = make_bound_reports()
    if where == "findings":
        report["findings"][0]["failure_scenario"] = "The claimed failure was softened."
        item = report["findings"][0]
    elif where == "scope":
        report["scope_assessment"]["limitations"][0]["detail"] = "The limitation was rewritten."
        item = report["scope_assessment"]["limitations"][0]
    else:
        report["closing_assessments"]["6619"]["limitations"][0]["detail"] = "The limitation was rewritten."
        item = report["closing_assessments"]["6619"]["limitations"][0]
    disposition = owner_disposition(report, pending)
    row = next(row for row in disposition["items"]
               if row["report"] == "original" and row["where"] == where and row["index"] == 0)
    row.update(decision="retained", successor={"where": where, "index": 0, "sha256": digest(item)})
    gate = cycle.review_gate(report, disposition=disposition, reconciliation=pending)
    assert gate["outcome"] == "changes_requested"
    assert "omitted, changed or softened" in gate["blocking"][0]


def test_no_third_report_retry_after_missing_disposition_or_second_bad_report(tmp_path, monkeypatch):
    layout, config, server, identity, cid, calls = case(tmp_path, monkeypatch)
    original, pending, cid2 = finish_original_and_retry(layout, config, server, identity, cid, monkeypatch)
    prior._finish(server, cid2, identity, prior.ACTUAL)
    for _ in range(3):
        result = cycle.advance(layout, config, fetch=fetch, http=server)
        assert result["results"][1]["action"] == "wait"
    saved = cycle._find(layout, 10, identity)
    assert len(prior._posts(server)) == 2 and calls == ["stop", "stop"]
    assert saved["report_reconciliations"][0]["archived"] == pending["archived"]
    assert saved["report_reconciliations"][0]["archived"]["review"] == original
    assert "verification" not in saved and "merge_intent" not in saved
