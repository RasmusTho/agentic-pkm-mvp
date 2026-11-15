"""Default candidate review consumption through real lifecycle and protocol validators."""

import json
import subprocess

import pytest

from app.builderops import epic_workspace as ew
from app.builderops import openhands_pr_cycle as cycle
from tests.builderops.test_openhands_candidate_dispatch_v2 import candidate_fixture


def prepared(tmp_path, capsys, monkeypatch, *, test_source="def test_example(): pass\n", sol=False):
    data, fetch, identity, server, home = candidate_fixture(tmp_path, capsys, monkeypatch, test_source=test_source)
    layout, author, publisher, engine, pr, entry, _, _, _ = data
    if sol:
        entry.update(model="gpt-6.1-sol", effort="high")
    assert cycle.advance(layout, [entry], fetch=fetch, http=server, codex_home=home)["results"][0]["action"] == "awaiting-candidate-review"
    started = cycle.advance(layout, [entry], fetch=fetch, http=server, codex_home=home)["results"][0]
    assert started["action"] == "candidate-review-dispatched", started
    worker, cid = started["worker"], started["conversation_id"]
    state = cycle._find(layout, 10, identity)
    dispatch = state["candidate_review_dispatch"]
    info = server.conversations[cid]
    info.update(execution_status="finished", agent={"kind": "ACPAgent", "acp_server": "codex",
                "acp_model": entry["model"], "acp_effort": entry.get("effort")}, current_model_id=entry["model"],
                current_effort=entry.get("effort", "ultra"), available_efforts=[{"value": entry.get("effort", "ultra")}],
                agent_state={"acp_session_id": "native-review", "acp_session_cwd": "/workspace"})
    server.events = [{"kind": "MessageEvent", "source": "agent"}]
    criterion = cycle.closure._acceptance_criteria(pr["governing_issue"]["body"], repo_root=publisher)[0]["criterion_sha256"]
    report = {"report_contract": cycle.REPORT_CONTRACT, "identity": dispatch["binding_sha256"],
              "head_sha": state["repair_candidate"]["candidate_head"], "verdict": "pass", "findings": [],
              "verify_targets": entry["verify_targets"], "covered_sources": [],
              "scope_assessment": {"acceptance": "covered", "verify_coverage": "covered", "limitations": []},
              "owner_doc": {"outcome": "no_change", "inspected_paths": ["README.md"], "rationale": "unchanged"},
              "closing_assessments": {"6617": {"acceptance": "covered", "verify_coverage": "covered", "limitations": [],
                  "criteria": {criterion: {"assessment": "covered", "rationale": "checked"}}}}}
    server.final_responses[cid] = json.dumps(report)
    original_command = cycle._command
    login = ["Logged in using ChatGPT"]
    container_id = engine.ids[layout.container_name(worker)]

    def command(argv, *, timeout):
        if argv[:2] == ["docker", "inspect"] and worker in engine.containers and argv[-1] == container_id:
            return subprocess.CompletedProcess(argv, 0, json.dumps([{"Id": argv[-1], "Image": "sha256:image",
                "Name": "/" + layout.container_name(worker), "State": {"Running": True},
                "Config": {"Image": ew.OPENHANDS_IMAGE, "Env": [], "Labels": {
                    ew.LABEL_EPIC: str(layout.epic), ew.LABEL_WORKER: worker}}}]), "")
        if argv[1:3] == ["image", "inspect"]:
            return subprocess.CompletedProcess(argv, 0, '[{"Id":"sha256:image"}]', "")
        if argv[1:3] == ["exec", container_id]:
            if argv[-2:] == ["login", "status"]:
                out = login[0]
            elif argv[-2:] == ["codex", cid]:
                out = json.dumps({"engine": "codex", "conversation_id": cid, "session_id": "native-review",
                                  "model": entry["model"], "effort": entry.get("effort", "ultra"), "timestamp": "2026-11-15T00:00:00Z"})
            else:
                out = "route-ok\n"
            return subprocess.CompletedProcess(argv, 0, out, "")
        return original_command(argv, timeout=timeout)

    monkeypatch.setattr(cycle, "_command", command)
    return data, fetch, identity, server, home, worker, cid, report, login


def advance(data, fetch, server, home):
    return cycle.advance(data[0], [data[5]], fetch=fetch, http=server, codex_home=home)["results"][0]


def test_finished_clean_receipt_stop_and_restart(tmp_path, capsys, monkeypatch):
    data, fetch, identity, server, home, worker, cid, report, _ = prepared(tmp_path, capsys, monkeypatch)
    layout, author, _, engine, _, _, _, _, _ = data
    candidate_git = cycle._candidate_git

    def trusted_git(path, *args):
        assert path != layout.checkout(worker), "agent-writable reviewer Git must stay contained"
        return candidate_git(path, *args)

    monkeypatch.setattr(cycle, "_candidate_git", trusted_git)
    (layout.checkout(worker) / "private-review.cache").write_text("reviewer unique work\n")
    answer = advance(data, fetch, server, home)
    assert answer["action"] == "awaiting-candidate-verify", answer
    saved = cycle._find(layout, 10, identity)
    assert saved["candidate_review_receipt"]["report"] == report
    assert saved["candidate_review_receipt"]["native_proof"]["auth"] == "chatgpt"
    assert saved["candidate_review_stop_verified"] is True
    assert cycle._mapping(layout, worker)["state"] == "stopped_verified"
    assert cycle._mapping(layout, worker)["work_at_stop"]["checkpoint"]
    assert (layout.checkout(worker) / "private-review.cache").read_text() == "reviewer unique work\n"
    assert (author / "private.cache").read_text() == "ignored unique work\n"
    assert "verification" not in saved and "repair_publication" not in saved
    calls = len(server.calls)
    # This fixture intentionally has no admitted test venv; automatic Verify holds honestly.
    assert advance(data, fetch, server, home)["action"] == "wait"
    assert len(server.calls) == calls
    assert len([call for call in server.calls if call[0] == "POST"]) == 1
    assert worker not in engine.containers


def test_finished_candidate_findings_are_retained_for_candidate_aware_repair(tmp_path, capsys, monkeypatch):
    data, fetch, identity, server, home, _, cid, report, _ = prepared(tmp_path, capsys, monkeypatch)
    finding = {"severity": "P1", "category": "correctness", "protected_class": "none", "summary": "repair",
               "file": "new.py", "line": 1, "failure_scenario": "failure"}
    report.update(verdict="findings", findings=[finding])
    server.final_responses[cid] = json.dumps(report)
    answer = advance(data, fetch, server, home)
    assert answer["action"] == "awaiting-candidate-repair", answer
    saved = cycle._find(data[0], 10, identity)
    assert saved["candidate_review_receipt"]["report"]["findings"] == [finding]
    assert saved["candidate_review_result"]["bounded_repair"]["finding_indexes"] == [0]
    assert saved["candidate_review_result"]["candidate_head"] == report["head_sha"]
    assert saved["candidate_review_stop_verified"] is True


@pytest.mark.parametrize("failure", ["wrong_candidate", "wrong_scope", "malformed", "native_auth"])
def test_invalid_finished_review_holds_and_stops_exact_worker(tmp_path, capsys, monkeypatch, failure):
    data, fetch, identity, server, home, worker, cid, report, login = prepared(tmp_path, capsys, monkeypatch)
    if failure == "wrong_candidate":
        report["head_sha"] = "f" * 40
    elif failure == "wrong_scope":
        report["closing_assessments"] = {}
    elif failure == "native_auth":
        login[0] = "API key"
    server.final_responses[cid] = "not json" if failure == "malformed" else json.dumps(report)
    answer = advance(data, fetch, server, home)
    assert answer["action"] in ("candidate-review-held", "wait"), answer
    saved = cycle._find(data[0], 10, identity)
    assert cycle._mapping(data[0], worker)["state"] == "stopped_verified"
    assert worker not in data[3].containers
    if failure != "native_auth":
        assert saved["candidate_review_stop_verified"] is True
        assert saved["candidate_review_result"]["state"] == "review_held"
    else:
        assert "candidate_review_receipt" not in saved
    assert (data[1] / "private.cache").read_text() == "ignored unique work\n"


def test_interrupted_stop_reuses_receipt_and_same_stop_without_endpoint(tmp_path, capsys, monkeypatch):
    data, fetch, identity, server, home, worker, cid, report, _ = prepared(tmp_path, capsys, monkeypatch)
    layout, _, _, engine, _, _, _, _, _ = data
    stop_ids = []

    def unavailable_remove(argv, **kwargs):
        if argv[:2] == ["docker", "rm"] and argv[-1] == engine.ids[layout.container_name(worker)]:
            saved = cycle._find(layout, 10, identity)
            assert saved["candidate_review_receipt"]["report"] == report
            assert saved["candidate_review_execution_proof"]["conversation_id"] == cid
            stop_ids.append(saved["candidate_review_stop_intent"]["stop_id"])
            return subprocess.CompletedProcess(argv, 1, "", "synthetic interruption")
        return engine(argv, **kwargs)

    monkeypatch.setattr(cycle, "_worker_runner", unavailable_remove)
    held = advance(data, fetch, server, home)
    assert held["action"] == "wait", held
    saved = cycle._find(layout, 10, identity)
    assert stop_ids and len(set(stop_ids)) == 1
    assert saved["candidate_review_stop_intent"]["stop_id"] == stop_ids[0]
    calls = len(server.calls)
    monkeypatch.setattr(cycle, "_worker_runner", engine)
    resumed = advance(data, fetch, server, home)
    assert resumed["action"] == "awaiting-candidate-verify", resumed
    assert len(server.calls) == calls
    assert cycle._find(layout, 10, identity)["candidate_review_stop_intent"]["stop_id"] == stop_ids[0]
    assert len([call for call in server.calls if call[0] == "POST"]) == 1


def test_publisher_dirty_after_dispatch_holds_and_stops_reviewer(tmp_path, capsys, monkeypatch):
    data, fetch, identity, server, home, worker, _, _, _ = prepared(tmp_path, capsys, monkeypatch)
    foreign = data[2] / "foreign-untracked.txt"
    foreign.write_text("preserve publisher work\n")
    held = advance(data, fetch, server, home)
    assert held["action"] == "wait", held
    assert cycle._mapping(data[0], worker)["state"] == "stopped_verified"
    assert "candidate_review_receipt" not in cycle._find(data[0], 10, identity)
    assert foreign.read_text() == "preserve publisher work\n"
