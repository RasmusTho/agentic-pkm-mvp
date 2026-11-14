"""Report-authority regressions; external effect ports are synthetic."""
import copy
import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

from app.builderops import openhands_pr_cycle as cycle
from app.builderops import epic_run_state, epic_workspace
from tests.builderops import test_openhands_pr_cycle as base
from tests.builderops import test_openhands_pr_cycle_disposition as support
from tests.builderops import test_openhands_pr_cycle_p3_gate as prior
from tests.builderops.test_openhands_pr_cycle import HEAD, fetch


def _report():
    return {**prior.reconciled(), "identity": "identity", "head_sha": HEAD}


def _child(report):
    return report["closing_assessments"]["6619"]


def _criterion(report):
    return next(iter(_child(report)["criteria"].values()))


@pytest.mark.parametrize("change", [
    lambda r: (_child(r).update(acceptance="incomplete"), _criterion(r).update(rationale="")),
    lambda r: (_child(r).update(verify_coverage="incomplete"), _child(r).update(criteria=None)),
    lambda r: (_criterion(r).update(assessment="incomplete", rationale=None), _child(r).update(acceptance=[])),
    lambda r: (_criterion(r).update(assessment="incomplete"), r["owner_doc"].update(outcome=[])),
    lambda r: r["owner_doc"].update(outcome="required_missing", rationale="", inspected_paths=[]),
    lambda r: r["findings"][0].update(protected_class="false_green", summary=""),
    lambda r: r["findings"][0].update(severity="P1", line=None),
    lambda r: r["findings"][0].update(severity="P3", category="correctness", failure_scenario=""),
    lambda r: (r["scope_assessment"].update(acceptance=None),
               r["scope_assessment"]["limitations"].append({"kind": "verify_gap", "detail": ""})),
    lambda r: (_child(r).update(criteria=None),
               _child(r)["limitations"].append({"kind": "acceptance_gap", "detail": None})),
])
def test_explicit_blockers_precede_adjacent_malformed_fields(change):
    report = _report()
    change(report)
    gate = cycle.review_gate(report)
    assert gate["outcome"] == "changes_requested"
    assert gate["blocking"]


@pytest.mark.parametrize("field,value", [("acceptance", None), ("acceptance", ""),
                                        ("verify_coverage", "unknown"), ("criteria", None)])
def test_unknown_current_required_assessment_never_passes(field, value):
    report = _report()
    _child(report)[field] = value
    assert cycle.review_gate(report, disposition=support.owner_disposition(report))["outcome"] != "pass"


@pytest.mark.parametrize("change", [
    lambda r: r["scope_assessment"].update(unknown_obligation="unclassified"),
    lambda r: r["owner_doc"].update(unknown_obligation="unclassified"),
    lambda r: r["owner_doc"].update(outcome="no_change"),
    lambda r: _child(r).update(unknown_obligation="unclassified"),
    lambda r: _criterion(r).update(unknown_obligation="unclassified"),
])
def test_unknown_current_assessment_material_does_not_pass(change):
    report = _report()
    change(report)
    assert cycle.review_gate(report, disposition=support.owner_disposition(report))["outcome"] == "reconcile_report"


@pytest.mark.parametrize("rationale", [None, "", " ", 5, [], {}])
def test_incomplete_criterion_blocks_with_any_bad_rationale(rationale):
    report = _report()
    _criterion(report).update(assessment="incomplete", rationale=rationale)
    assert cycle.review_gate(report)["outcome"] == "changes_requested"


def test_incomplete_criterion_blocks_when_rationale_is_missing():
    report = _report()
    _criterion(report)["assessment"] = "incomplete"
    _criterion(report).pop("rationale")
    assert cycle.review_gate(report)["outcome"] == "changes_requested"


def _bound_empty_reports():
    current, pending, _ = support.make_bound_reports()
    original = copy.deepcopy(current)
    for report in (current, original):
        report["findings"] = []
        report["verdict"] = "pass"
        report["scope_assessment"]["limitations"] = []
        _child(report)["limitations"] = []
    original["verdict"] = "findings"  # A safe syntax defect that can take the one retry.
    pending["archived"]["review"] = original
    return current, pending


def _bind_original(current, pending):
    archive = pending["archived"]
    pending["original_report_sha256"] = support.digest(archive["review"])
    pending["original_attempt_sha256"] = support.digest(archive)
    return support.owner_disposition(current, pending)


@pytest.mark.parametrize("change", [
    lambda r: (_child(r).update(acceptance="incomplete"), _criterion(r).update(rationale="")),
    lambda r: _child(r).update(verify_coverage="incomplete", criteria=None),
    lambda r: _criterion(r).update(assessment="incomplete", rationale=None),
    lambda r: r["owner_doc"].update(outcome="required_missing", rationale="", inspected_paths=[]),
    lambda r: r["scope_assessment"]["limitations"].append({"kind": "verify_gap", "detail": ""}),
    lambda r: _child(r)["limitations"].append({"kind": "owner_doc_gap", "detail": None}),
    lambda r: _child(r).pop("acceptance"),
    lambda r: _child(r)["criteria"].clear(),
    lambda r: r["owner_doc"].pop("outcome"),
    lambda r: r["owner_doc"].update(outcome="unsupported"),
    lambda r: r.update(verdict="unknown"),
    lambda r: r["scope_assessment"].update(unknown_obligation="unclassified material"),
])
def test_already_archived_negative_or_unknown_material_cannot_be_waived(change):
    current, pending = _bound_empty_reports()
    original = pending["archived"]["review"]
    change(original)
    # Supply exact lineage and a generic whole-report owner assertion, as in the escape.
    disposition = _bind_original(current, pending)
    gate = cycle.review_gate(current, disposition=disposition, reconciliation=pending)
    assert gate["outcome"] == "changes_requested"
    assert "original" in gate["blocking"][0]
    assert pending["archived"]["review"] == original


def test_known_nonblocking_original_can_reconcile_with_exact_owner_disposition():
    current, pending = _bound_empty_reports()
    disposition = _bind_original(current, pending)
    assert cycle.review_gate(current, disposition=disposition, reconciliation=pending)["outcome"] == "pass"


@pytest.mark.parametrize("kind", ["criterion", "owner_doc"])
def test_existing_archived_gap_stops_real_retry_before_effects(tmp_path, monkeypatch, kind):
    layout, config, server, identity, cid, calls = support.case(tmp_path, monkeypatch)
    original = _report()
    original["findings"] = []
    original["verdict"] = "findings"
    original["scope_assessment"]["limitations"] = []
    _child(original)["limitations"] = []
    _, _, retry_cid = support.finish_original_and_retry(layout, config, server, identity, cid, monkeypatch, original)
    # Construct the already-archived pre-repair state, with matching original and attempt digests.
    saved = cycle._find(layout, 10, identity)
    pending = saved["report_reconciliations"][0]
    archived = pending["archived"]["review"]
    if kind == "criterion":
        _child(archived)["acceptance"] = "incomplete"
        _criterion(archived).update(assessment="incomplete", rationale="")
    else:
        archived["owner_doc"].update(outcome="required_missing", rationale="", inspected_paths=[])
    pending["original_report_sha256"] = support.digest(archived)
    pending["original_attempt_sha256"] = support.digest(pending["archived"])
    cycle._save(layout, saved)
    successor = _report()
    successor["findings"] = []
    successor["verdict"] = "pass"
    successor["scope_assessment"]["limitations"] = []
    _child(successor)["limitations"] = []
    successor = prior._finish(server, retry_cid, identity, successor)
    config[0]["review_disposition"] = support.owner_disposition(successor, pending)
    effects = prior._merge_ports(layout, monkeypatch, identity)
    result = cycle.advance(layout, config, fetch=fetch, http=server)
    retained = cycle._find(layout, 10, identity)
    assert result["results"][1]["action"] == "wait"
    assert "original review has a protected or incomplete obligation" in retained["review_gate"]["blocking"][0]
    assert retained["report_reconciliations"][0]["archived"] == pending["archived"]
    assert calls == ["stop", "stop"] and effects == []
    assert "verification" not in retained and "merge_intent" not in retained


def test_current_valid_real_p3_progresses_with_owner_disposition(tmp_path, monkeypatch):
    # Retain the public report's actual head while all effect ports remain synthetic.
    monkeypatch.setattr(base, "HEAD", prior.ACTUAL["head_sha"])
    monkeypatch.setattr(prior, "HEAD", prior.ACTUAL["head_sha"])
    layout, config, server, identity, cid, calls = support.case(tmp_path, monkeypatch)
    report = prior._finish(server, cid, identity, prior.reconciled())
    assert report["head_sha"] == "6018f93c9b5a0fddfb6cb316159927fcf5313f03"
    config[0]["review_disposition"] = support.owner_disposition(report)
    effects = prior._merge_ports(layout, monkeypatch, identity)
    result = cycle.advance(layout, config, fetch=fetch, http=server)
    assert result["results"][1]["action"] == "merged"
    assert calls == ["stop", "ci", "sandbox", "ci"]
    assert effects == ["merge", "comment", "comment"]


@pytest.mark.parametrize("change", ["revoke", "replace", "allowed"])
def test_main_reads_current_file_after_same_lock_owner_update(tmp_path, monkeypatch, capsys, change):
    layout, config, server, identity, cid, calls = support.case(tmp_path, monkeypatch)
    report = prior._finish(server, cid, identity, prior.reconciled())
    config[0]["review_disposition"] = support.owner_disposition(report)
    path = tmp_path / "admission.json"
    path.write_text(json.dumps({"admissions": config}), encoding="utf-8")
    path.chmod(0o600)
    effects = prior._merge_ports(layout, monkeypatch, identity)
    real_advance = cycle.advance

    def owner_then_advance(layout_arg, source):
        assert source == path
        if change != "allowed":
            with cycle._single_advancement(layout_arg):
                on_disk = json.loads(path.read_text(encoding="utf-8"))
                if change == "revoke":
                    del on_disk["admissions"][0]["review_disposition"]
                    path.write_text(json.dumps(on_disk), encoding="utf-8")
                else:
                    on_disk["admissions"][0]["review_disposition"]["identity"] = "replacement"
                    replacement = path.with_suffix(".replacement")
                    replacement.write_text(json.dumps(on_disk), encoding="utf-8")
                    replacement.chmod(0o600)
                    replacement.replace(path)
        return real_advance(layout_arg, source, fetch=fetch, http=server)

    monkeypatch.setattr(cycle, "advance", owner_then_advance)
    status = cycle.main(["--once", "--root", str(tmp_path), "--epic", "6615", "--config", str(path)])
    output = json.loads(capsys.readouterr().out)
    assert status == 0
    if change == "allowed":
        assert output["results"][1]["action"] == "merged"
        assert calls == ["stop", "ci", "sandbox", "ci"] and effects == ["merge", "comment", "comment"]
    else:
        assert output["results"][1]["action"] == "wait"
        assert calls == ["stop"] and effects == []
        saved = cycle._find(layout, 10, identity)
        assert saved["review_gate"]["outcome"] == "changes_requested"
        assert "verification" not in saved and "merge_intent" not in saved


def test_main_refuses_contended_lock_without_nested_deadlock(tmp_path, monkeypatch, capsys):
    layout, config, _, _, _, _ = support.case(tmp_path, monkeypatch)
    path = tmp_path / "admission.json"
    path.write_text(json.dumps({"admissions": config}), encoding="utf-8")
    path.chmod(0o600)
    with cycle._single_advancement(layout):
        assert cycle.main(["--once", "--root", str(tmp_path), "--epic", "6615", "--config", str(path)]) == 2
    assert "another advancement is running" in capsys.readouterr().err


def test_owner_cannot_update_file_during_verification(tmp_path, monkeypatch):
    layout, config, server, identity, cid, calls = support.case(tmp_path, monkeypatch)
    report = prior._finish(server, cid, identity, prior.reconciled())
    config[0]["review_disposition"] = support.owner_disposition(report)
    path = tmp_path / "admission.json"
    path.write_text(json.dumps({"admissions": config}), encoding="utf-8")
    path.chmod(0o600)
    real_verify = cycle.sandbox_verify

    def verify(*args):
        with pytest.raises(cycle.CycleError, match="another advancement"):
            with cycle._single_advancement(layout):
                pytest.fail("cooperative writer acquired the advancement lock")
        return real_verify(*args)

    monkeypatch.setattr(cycle, "sandbox_verify", verify)
    effects = prior._merge_ports(layout, monkeypatch, identity)
    result = cycle.advance(layout, path, fetch=fetch, http=server)
    assert result["results"][1]["action"] == "merged"
    assert calls == ["stop", "ci", "sandbox", "ci"] and effects == ["merge", "comment", "comment"]
    with cycle._single_advancement(layout):
        assert json.loads(path.read_text(encoding="utf-8"))["admissions"][0]["review_disposition"]


def test_module_cli_uses_interpreter_cwd_import_and_real_config_boundary(tmp_path):
    """Run the actual -m entrypoint; only the gh network executable is synthetic."""
    layout = epic_workspace.Layout(tmp_path, 6615)
    epic_run_state.create_epic_run_state(6615, layout.run_id, root=layout.run_state_dir)
    path = tmp_path / "admission.json"
    path.write_text(json.dumps({"admissions": []}), encoding="utf-8")
    path.chmod(0o600)
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    gh = bin_dir / "gh"
    gh.write_text("#!/bin/sh\nprintf '[]\\n'\n", encoding="utf-8")
    gh.chmod(0o700)
    root = Path(__file__).resolve().parents[2]
    env = {**os.environ, "PATH": str(bin_dir) + os.pathsep + os.environ["PATH"], "PYTHONPATH": str(root),
           "PYTHONDONTWRITEBYTECODE": "1"}
    command = [sys.executable, "-m", "app.builderops.openhands_pr_cycle", "--once", "--root", str(tmp_path),
               "--epic", "6615", "--config", str(path)]
    result = subprocess.run(command, cwd=root, env=env, capture_output=True, text=True, check=False, timeout=15)
    assert result.returncode == 0, result.stderr
    assert json.loads(result.stdout)["inventory_complete"] is True
    path.chmod(0o666)
    refused = subprocess.run(command, cwd=root, env=env, capture_output=True, text=True, check=False, timeout=15)
    assert refused.returncode == 2
    assert "admission configuration must be controller-owned" in refused.stderr


def test_changed_file_disposition_invalidates_saved_verification(tmp_path, monkeypatch, capsys):
    layout, config, server, identity, cid, calls = support.case(tmp_path, monkeypatch)
    report = prior._finish(server, cid, identity, prior.reconciled())
    config[0]["review_disposition"] = support.owner_disposition(report)
    path = tmp_path / "admission.json"
    path.write_text(json.dumps({"admissions": config}), encoding="utf-8")
    path.chmod(0o600)
    statuses = iter([0, 1, 0, 1])
    monkeypatch.setattr(cycle, "ci_once", lambda *args: calls.append("ci") or {"exit_code": next(statuses)})
    effects = prior._merge_ports(layout, monkeypatch, identity)
    real_advance = cycle.advance
    monkeypatch.setattr(cycle, "advance", lambda layout, source: real_advance(layout, source, fetch=fetch, http=server))
    argv = ["--once", "--root", str(tmp_path), "--epic", "6615", "--config", str(path)]
    assert cycle.main(argv) == 0
    capsys.readouterr()
    first = cycle._find(layout, 10, identity)["verification"]["disposition_sha256"]
    with cycle._single_advancement(layout):
        config[0]["review_disposition"]["assessment"] = "Synthetic owner repeated the complete assessment with new evidence."
        path.write_text(json.dumps({"admissions": config}), encoding="utf-8")
    assert cycle.main(argv) == 0
    capsys.readouterr()
    second = cycle._find(layout, 10, identity)["verification"]["disposition_sha256"]
    assert first != second and second == support.digest(config[0]["review_disposition"])
    assert calls == ["stop", "ci", "sandbox", "ci", "ci", "sandbox", "ci"] and effects == []


def test_revoked_disposition_waits_then_restores_with_current_verify(tmp_path, monkeypatch, capsys):
    layout, config, server, identity, cid, calls = support.case(tmp_path, monkeypatch)
    report = prior._finish(server, cid, identity, prior.reconciled())
    config[0]["review_disposition"] = support.owner_disposition(report)
    path = tmp_path / "admission.json"
    path.write_text(json.dumps({"admissions": config}), encoding="utf-8")
    path.chmod(0o600)
    statuses = iter([0, 1, 0, 1])
    monkeypatch.setattr(cycle, "ci_once", lambda *args: calls.append("ci") or {"exit_code": next(statuses)})
    effects = prior._merge_ports(layout, monkeypatch, identity)
    real_advance = cycle.advance
    monkeypatch.setattr(cycle, "advance", lambda layout, source: real_advance(layout, source, fetch=fetch, http=server))
    argv = ["--once", "--root", str(tmp_path), "--epic", "6615", "--config", str(path)]
    assert cycle.main(argv) == 0
    capsys.readouterr()
    assert cycle._find(layout, 10, identity)["verification"]["passed"] is True
    with cycle._single_advancement(layout):
        revoked = copy.deepcopy(config)
        del revoked[0]["review_disposition"]
        path.write_text(json.dumps({"admissions": revoked}), encoding="utf-8")
    assert cycle.main(argv) == 0
    capsys.readouterr()
    saved = cycle._find(layout, 10, identity)
    assert saved["review_gate"]["outcome"] == "changes_requested"
    assert "verification" not in saved and "ci" not in saved
    assert calls == ["stop", "ci", "sandbox", "ci"] and effects == []
    with cycle._single_advancement(layout):
        path.write_text(json.dumps({"admissions": config}), encoding="utf-8")
    assert cycle.main(argv) == 0
    capsys.readouterr()
    assert calls == ["stop", "ci", "sandbox", "ci", "ci", "sandbox", "ci"] and effects == []
