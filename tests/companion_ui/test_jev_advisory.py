from __future__ import annotations

import json
from pathlib import Path
import subprocess
from typing import Any
import xml.etree.ElementTree as ET

import pytest

from scripts import run_jev_browser_advisory as runner
from tests.companion_ui import jev_advisory as advisory
from tests.companion_ui import focus_jev_advisory as focus_advisory
from tests.companion_ui import focus_state_jev_advisory as state_advisory

SHA = "a" * 40


def _seed_focus_state(directory: Path) -> None:
    observations = directory / "observations"
    observations.mkdir(parents=True)
    for case in state_advisory.CASES:
        for width in state_advisory.WIDTHS:
            value = {"fixture_version": state_advisory.FIXTURE_VERSION, "source_sha": SHA,
                "case_id": case, "width": width, "expected": state_advisory.expected(case),
                "observed": {"state": "Synthetic state", "facts": [], "warnings": [], "next_step": "Legality unavailable"}}
            (observations / f"{case}-{width}.json").write_text(json.dumps(value))
    suite = ET.Element("testsuite")
    for name in sorted(runner.FOCUS_STATE_NAMES):
        ET.SubElement(suite, "testcase", classname="tests.companion_ui.test_focus_evidence_state_runtime", name=name)
    ET.ElementTree(suite).write(directory / "junit.xml")


@pytest.mark.parametrize("mutation", ["missing", "duplicate", "failure", "error", "skip", "xfail", "classname", "stale", "private_field", "numeric_boolean", "private_value", "invalid_id", "watermark", "oversized"])
def test_focus_state_advisory_requires_complete_passing_evidence(tmp_path, monkeypatch, mutation) -> None:
    monkeypatch.setattr(runner.subprocess, "check_output", lambda args, **kwargs: SHA if "rev-parse" in args else "")
    def browser(directory, sha, surface):
        assert surface == "focus-evidence-state" and sha == SHA
        _seed_focus_state(directory)
        assert runner._browser_inventory(directory / "junit.xml", surface) == {"passed": 16, "known_defect_xfails": 0}
        tree = ET.parse(directory / "junit.xml"); first = tree.getroot()[0]
        if mutation == "missing":
            tree.getroot().remove(first)
        elif mutation == "duplicate":
            tree.getroot().append(ET.fromstring(ET.tostring(first)))
        elif mutation in {"failure", "error", "skip", "xfail"}:
            ET.SubElement(first, "skipped" if mutation in {"skip", "xfail"} else mutation, type=mutation)
        elif mutation == "classname":
            first.set("classname", "tests.companion_ui.test_focus_owner_facts_runtime")
        else:
            path = next((directory / "observations").glob("*.json")); value = json.loads(path.read_text())
            if mutation == "stale":
                value["source_sha"] = "b" * 40
            elif mutation == "private_field":
                value["observed"]["source_ref"] = "private-canary"
            elif mutation == "numeric_boolean":
                value["expected"]["warning"] = int(value["expected"]["warning"])
            elif mutation == "invalid_id":
                value["case_id"] = ["unhashable"]
            else:
                value["observed"]["facts"] = ["F" * 64 if mutation == "private_value" else "fixture-scope:0" if mutation == "watermark" else "oversized" * 100]
            path.write_text(json.dumps(value))
        tree.write(directory / "junit.xml")
        return 0
    monkeypatch.setattr(runner, "_run_browser", browser)
    monkeypatch.setattr(runner, "_judge_once", lambda *_: pytest.fail("incomplete/private state evidence was judged"))
    assert runner.run(tmp_path, live_jev=True, surface="focus-evidence-state") == 2
    report = json.loads(next(tmp_path.glob("*/report.json")).read_text())
    assert report["deterministic"]["status"] == "incomplete_evidence" and report["jev"]["origin"] == "not-run"


@pytest.mark.parametrize("result", ["supported", "contradicted", "unknown", "interrupted"])
def test_focus_state_advisory_attempt_is_fenced_and_never_replayed(tmp_path, monkeypatch, result) -> None:
    monkeypatch.setattr(runner.subprocess, "check_output", lambda args, **kwargs: SHA if "rev-parse" in args else "")
    def browser(directory, sha, surface):
        assert surface == "focus-evidence-state" and sha == SHA
        _seed_focus_state(directory)
        return 0
    monkeypatch.setattr(runner, "_run_browser", browser)
    monkeypatch.setattr(runner, "_helper_status", lambda: None)
    path = tmp_path / f"{SHA}-{state_advisory.RUBRIC_VERSION}" / "report.json"
    calls = []
    def judge(request):
        report = json.loads(path.read_text())
        assert report["jev"]["reason"] == "attempt_started" and report["jev"]["origin"] == "live"
        assert report["deterministic"]["passed"] == 16
        assert set(request["questions"]) == {f"{case}.{axis}" for case in state_advisory.CASES for axis in ("state", "authority")}
        assert set(request["state"]) == {"cases", "rubric"}
        calls.append(request)
        if result == "interrupted":
            raise KeyboardInterrupt()
        return {"status": "completed", **advisory.assessed_answers(_response(request, choice=result), request)}
    monkeypatch.setattr(runner, "_judge_once", judge)
    if result == "interrupted":
        with pytest.raises(KeyboardInterrupt):
            runner.run(tmp_path, live_jev=True, surface="focus-evidence-state")
    else:
        assert runner.run(tmp_path, live_jev=True, surface="focus-evidence-state") == 0
    assert runner.run(tmp_path, live_jev=True, surface="focus-evidence-state") == 0 and len(calls) == 1


def _observation(state: str, bound: bool, width: int = 1366) -> dict[str, Any]:
    return {"fixture_version": advisory.FIXTURE_VERSION, "source_sha": SHA,
            "case_id": f"{state}-{'bound' if bound else 'unbound'}", "width": width,
            "expected": {"listing": state, "identity_available": bound,
                         "visible_note_count": int(state in {"partial", "populated"})},
            "observed": {"messages": ["Synthetic status."],
                         "identity_text": "FixtureVault/test" if bound else "unresolved/unknown",
                         "visible_note_count": int(state in {"partial", "populated"})}}


def _seed(directory: Path) -> None:
    observations = directory / "observations"
    observations.mkdir(parents=True)
    for state in advisory.LIST_STATES:
        for bound in (True, False):
            for width in advisory.WIDTHS:
                item = _observation(state, bound, width)
                (observations / f"{item['case_id']}-{width}.json").write_text(json.dumps(item))
    suite = ET.Element("testsuite")
    for name in sorted(runner.ORDINARY_NAMES):
        ET.SubElement(suite, "testcase", classname="tests.companion_ui.test_vault_browser_state_runtime", name=name)
    ET.ElementTree(suite).write(directory / "junit.xml")


def _seed_focus(directory: Path) -> None:
    observations = directory / "observations"
    observations.mkdir(parents=True)
    for case in focus_advisory.CASES:
        for width in focus_advisory.WIDTHS:
            value = {"fixture_version": focus_advisory.FIXTURE_VERSION, "source_sha": SHA,
                "case_id": case, "width": width, "expected": focus_advisory.expected(case),
                "observed": {"facts": ["Synthetic owner fact."], "limitations": [], "next_step": "Legality unavailable"}}
            (observations / f"{case}-{width}.json").write_text(json.dumps(value))
    suite = ET.Element("testsuite")
    for name in sorted(runner.FOCUS_NAMES):
        ET.SubElement(suite, "testcase", classname="tests.companion_ui.test_focus_owner_facts_runtime", name=name)
    ET.ElementTree(suite).write(directory / "junit.xml")


@pytest.fixture
def synthetic_runner(monkeypatch: pytest.MonkeyPatch, tmp_path: Path):
    def checkout(args: list[str], **kwargs: Any):
        return SHA if "rev-parse" in args else ""

    def browser(directory: Path, _sha: str):
        _seed(directory)
        return 0

    monkeypatch.setattr(runner.subprocess, "check_output", checkout)
    monkeypatch.setattr(runner, "_run_browser", browser)
    monkeypatch.setattr(runner, "_helper_status", lambda: None)
    return tmp_path, tmp_path / f"{SHA}-{advisory.RUBRIC_VERSION}" / "report.json"


def _response(request: dict[str, Any], *, choice: str = "supported", confidence: float = 0.9) -> bytes:
    return json.dumps({"model": "untrusted-provider-model-text", "answers": {
        key: {"type": "choice", "choice": choice, "confidence": confidence,
              "probabilities": {label: float(label == choice) for label in ("supported", "contradicted", "unknown")}}
        for key in request["questions"]}, "usage": {"input_tokens": 10, "output_tokens": 16}}).encode()


def test_observation_allowlist_and_complete_inventory(tmp_path: Path) -> None:
    _seed(tmp_path)
    observations = advisory.load_observations(tmp_path / "observations", SHA)
    assert len(observations) == 8 and all(item["width"] == 1366 for item in observations)
    request = advisory.build_judgment_request(observations)
    assert len(request["questions"]) == 16
    for index, item in enumerate(observations):
        for axis in ("listing", "identity"):
            question = request["questions"][f"{item['case_id']}.{axis}"]
            assert f"`rubric.{axis}`" in question["instructions"]
            assert f"`cases[{index}].observed`" in question["instructions"]
    assert not {"note_path", "title", "body", "raw_dom", "screenshot"} & set(request["state"])
    path = next((tmp_path / "observations").glob("*.json"))
    item = json.loads(path.read_text()); item["observed"]["raw_dom"] = "private-canary"
    path.write_text(json.dumps(item))
    with pytest.raises(advisory.InvalidObservation):
        advisory.load_observations(tmp_path / "observations", SHA)
    path.unlink()
    with pytest.raises(advisory.InvalidObservation):
        advisory.load_observations(tmp_path / "observations", SHA)


@pytest.mark.parametrize("mutation", ["missing", "duplicate", "failure", "error", "skip", "xfail", "classname", "stale", "private_field", "numeric_boolean"])
def test_focus_advisory_surface_requires_complete_passing_evidence(tmp_path, monkeypatch, mutation) -> None:
    monkeypatch.setattr(runner.subprocess, "check_output", lambda args, **kwargs: SHA if "rev-parse" in args else "")
    def browser(directory, sha, surface):
        assert surface == "focus-owner-facts" and sha == SHA
        _seed_focus(directory)
        assert runner._browser_inventory(directory / "junit.xml", surface) == {"passed": 16, "known_defect_xfails": 0}
        tree = ET.parse(directory / "junit.xml")
        first = tree.getroot()[0]
        if mutation == "missing":
            tree.getroot().remove(first)
        elif mutation == "duplicate":
            tree.getroot().append(ET.fromstring(ET.tostring(first)))
        elif mutation in {"failure", "error", "skip", "xfail"}:
            tag = "skipped" if mutation in {"skip", "xfail"} else mutation
            ET.SubElement(first, tag, type="pytest.xfail" if mutation == "xfail" else mutation)
        elif mutation == "classname":
            first.set("classname", "tests.companion_ui.test_vault_browser_state_runtime")
        else:
            path = next((directory / "observations").glob("*.json"))
            value = json.loads(path.read_text())
            if mutation == "stale":
                value["source_sha"] = "b" * 40
            elif mutation == "private_field":
                value["observed"]["receipt_id"] = "private-canary"
            else:
                value["expected"]["trial"] = int(value["expected"]["trial"])
            path.write_text(json.dumps(value))
        tree.write(directory / "junit.xml")
        return 0
    monkeypatch.setattr(runner, "_run_browser", browser)
    monkeypatch.setattr(runner, "_judge_once", lambda *_: pytest.fail("incomplete Focus evidence was judged"))
    assert runner.run(tmp_path, live_jev=True, surface="focus-owner-facts") == 2
    report = json.loads(next(tmp_path.glob("*/report.json")).read_text())
    assert report["surface"] == "focus-owner-facts"
    assert report["deterministic"]["status"] == "incomplete_evidence"
    assert report["jev"]["origin"] == "not-run"


@pytest.mark.parametrize("result", ["supported", "contradicted", "unknown", "interrupted"])
def test_focus_advisory_attempt_is_fenced_and_never_replayed(tmp_path, monkeypatch, result) -> None:
    monkeypatch.setattr(runner.subprocess, "check_output", lambda args, **kwargs: SHA if "rev-parse" in args else "")
    def browser(directory, sha, surface):
        assert surface == "focus-owner-facts" and sha == SHA
        _seed_focus(directory)
        return 0
    monkeypatch.setattr(runner, "_run_browser", browser)
    monkeypatch.setattr(runner, "_helper_status", lambda: None)
    path = tmp_path / f"{SHA}-{focus_advisory.RUBRIC_VERSION}" / "report.json"
    calls = []
    def judge(request):
        report = json.loads(path.read_text())
        assert report["jev"]["reason"] == "attempt_started" and report["jev"]["origin"] == "live"
        assert report["deterministic"] == {"status": "passed", "exit_code": 0, "passed": 16, "known_defect_xfails": 0}
        assert len(request["questions"]) == 16
        assert set(request["questions"]) == {f"{case}.{axis}" for case in focus_advisory.CASES for axis in ("facts", "authority")}
        for index, row in enumerate(report["observations"]):
            for axis in ("facts", "authority"):
                question = request["questions"][f"{row['case_id']}.{axis}"]
                assert f"rubric.{axis}" in question["instructions"]
                assert f"cases[{index}].observed" in question["instructions"]
        assert not {"receipt_id", "locator", "source_ref", "title", "raw_dom", "screenshot"} & set(request["state"])
        calls.append(request)
        if result == "interrupted":
            raise KeyboardInterrupt()
        return {"status": "completed", **advisory.assessed_answers(_response(request, choice=result), request)}
    monkeypatch.setattr(runner, "_judge_once", judge)
    if result == "interrupted":
        with pytest.raises(KeyboardInterrupt):
            runner.run(tmp_path, live_jev=True, surface="focus-owner-facts")
    else:
        assert runner.run(tmp_path, live_jev=True, surface="focus-owner-facts") == 0
    assert runner.run(tmp_path, live_jev=True, surface="focus-owner-facts") == 0
    assert len(calls) == 1
    report = json.loads(path.read_text())
    if result != "interrupted":
        wanted = "unassessed" if result == "unknown" else result
        assert {row["status"] for row in report["jev"]["results"].values()} == {wanted}


@pytest.mark.parametrize("mutation", ["stale", "duplicate", "long_text", "bad_count", "extra_note"])
def test_invalid_fixture_observations_are_not_dispatched(tmp_path: Path, mutation: str) -> None:
    _seed(tmp_path)
    path = next((tmp_path / "observations").glob("*.json"))
    item = json.loads(path.read_text())
    if mutation == "stale":
        item["source_sha"] = "b" * 40
    elif mutation == "duplicate":
        (path.parent / "duplicate.json").write_text(path.read_text())
    elif mutation == "long_text":
        item["observed"]["messages"] = ["x" * 201]
    elif mutation == "bad_count":
        item["observed"]["visible_note_count"] = True
    else:
        item["note_path"] = "private-canary"
    path.write_text(json.dumps(item))
    with pytest.raises(advisory.InvalidObservation):
        advisory.load_observations(path.parent, SHA)


@pytest.mark.parametrize("choice,confidence,status", [("supported", 0.9, "supported"),
    ("contradicted", 0.9, "contradicted"), ("unknown", 0.9, "unassessed"), ("supported", 0.4, "unassessed")])
def test_advisory_results_never_replace_deterministic_gate(synthetic_runner, monkeypatch, choice, confidence, status) -> None:
    root, path = synthetic_runner
    def judge(request):
        return {"status": "completed", **advisory.assessed_answers(_response(request, choice=choice, confidence=confidence), request)}
    monkeypatch.setattr(runner, "_judge_once", judge)
    assert runner.run(root, live_jev=True) == 0
    report = json.loads(path.read_text())
    assert report["advisory_only"] is True and report["deterministic"]["status"] == "passed"
    assert {item["status"] for item in report["jev"]["results"].values()} == {status}
    assert report["jev"]["model"] == "jev-latest"
    other = root / "exact-failure"
    monkeypatch.setattr(runner, "_run_browser", lambda *_: 1)
    monkeypatch.setattr(runner, "_judge_once", lambda *_: pytest.fail("model must not run after exact failure"))
    assert runner.run(other, live_jev=True) == 1
    failed = next(other.glob("*/report.json"))
    assert json.loads(failed.read_text())["jev"]["reason"] == "deterministic_failed"


def test_live_attempt_is_fenced_before_dispatch_and_never_replayed(synthetic_runner, monkeypatch) -> None:
    root, path = synthetic_runner
    calls = []
    def interrupted(request):
        saved = json.loads(path.read_text())
        assert saved["jev"]["reason"] == "attempt_started" and saved["jev"]["origin"] == "live"
        assert saved["deterministic"]["status"] == "passed"
        calls.append(request)
        raise KeyboardInterrupt()
    monkeypatch.setattr(runner, "_judge_once", interrupted)
    with pytest.raises(KeyboardInterrupt):
        runner.run(root, live_jev=True)
    assert runner.run(root, live_jev=True) == 0
    assert len(calls) == 1
    saved = json.loads(path.read_text())
    assert saved["jev"]["status"] == "unassessed"


@pytest.mark.parametrize("failure", ["nonzero", "timeout", "malformed", "missing", "oversized"])
def test_helper_failures_are_sanitized_and_not_retried(synthetic_runner, monkeypatch, capsys, failure) -> None:
    root, path = synthetic_runner
    calls = []
    def helper(args, **kwargs):
        calls.append(args)
        assert args == [runner.sys.executable, "-I", str(runner.HELPER)]
        assert kwargs["stderr"] is subprocess.DEVNULL and kwargs["timeout"] == 45
        assert set(kwargs["env"]) == {"HOME", "PATH", "LANG"}
        request = json.loads(kwargs["input"])
        if failure == "timeout":
            raise subprocess.TimeoutExpired("private-canary", 45)
        raw = _response(request)
        if failure == "malformed":
            raw = b"private-canary"
        elif failure == "missing":
            response = json.loads(raw); response["answers"].pop(next(iter(response["answers"]))); raw = json.dumps(response).encode()
        elif failure == "oversized":
            raw = b"private-canary" * 2000
        return subprocess.CompletedProcess(args, 1 if failure == "nonzero" else 0, stdout=raw)
    monkeypatch.setattr(runner.subprocess, "run", helper)
    assert runner.run(root, live_jev=True) == 0
    report = json.loads(path.read_text())
    assert report["jev"]["status"] == "unassessed"
    assert "private-canary" not in path.read_text() + capsys.readouterr().out
    assert runner.run(root, live_jev=True) == 0 and len(calls) == 1


@pytest.mark.parametrize("reason", ["helper_unavailable", "helper_out_of_date", "live_disabled"])
def test_unavailable_or_disabled_helper_has_no_live_origin(synthetic_runner, monkeypatch, reason) -> None:
    root, path = synthetic_runner
    monkeypatch.setattr(runner, "_helper_status", lambda: reason)
    monkeypatch.setattr(runner, "_judge_once", lambda *_: pytest.fail("unavailable/disabled helper was dispatched"))
    assert runner.run(root, live_jev=reason != "live_disabled") == 0
    assert json.loads(path.read_text())["jev"] == {"status": "unassessed", "reason": reason, "origin": "not-run", "results": {}}


def test_missing_or_skipped_browser_evidence_remains_blocking(synthetic_runner, monkeypatch) -> None:
    root, path = synthetic_runner
    def incomplete(directory, _sha):
        _seed(directory)
        tree = ET.parse(directory / "junit.xml")
        ordinary = next(case for case in tree.getroot() if case.get("name") in runner.ORDINARY_NAMES)
        ET.SubElement(ordinary, "skipped", type="pytest.skip", message="missing browser")
        tree.write(directory / "junit.xml")
        return 0
    monkeypatch.setattr(runner, "_run_browser", incomplete)
    monkeypatch.setattr(runner, "_judge_once", lambda *_: pytest.fail("incomplete browser evidence was judged"))
    assert runner.run(root, live_jev=True) == 2
    assert json.loads(path.read_text())["deterministic"]["status"] == "incomplete_evidence"


@pytest.mark.parametrize("mutation", ["duplicate", "missing", "failure", "error"])
def test_browser_inventory_requires_all_cases_and_rejects_duplicates(tmp_path: Path, mutation: str) -> None:
    _seed(tmp_path)
    tree = ET.parse(tmp_path / "junit.xml")
    assert runner._browser_inventory(tmp_path / "junit.xml") == {"passed": 20, "known_defect_xfails": 0}
    cases = list(tree.getroot())
    if mutation == "duplicate":
        cases[0].set("name", cases[1].get("name"))
    elif mutation == "missing":
        tree.getroot().remove(cases[0])
    else:
        ET.SubElement(cases[0], mutation, message="matrix did not pass")
    tree.write(tmp_path / "junit.xml")
    with pytest.raises(advisory.InvalidObservation):
        runner._browser_inventory(tmp_path / "junit.xml")


@pytest.mark.parametrize("viewport", ["desktop", "narrow-pane"])
@pytest.mark.parametrize("state", ["partial", "error"])
@pytest.mark.parametrize("skip_type", ["pytest.skip", "pytest.xfail"])
def test_combined_regression_skip_or_xfail_blocks_advisory_dispatch(
    synthetic_runner, monkeypatch, viewport: str, state: str, skip_type: str,
) -> None:
    root, path = synthetic_runner

    def incomplete(directory, _sha):
        _seed(directory)
        tree = ET.parse(directory / "junit.xml")
        name = f"test_combined_degradation_discloses_identity_unavailable[{viewport}-{state}]"
        case = next(case for case in tree.getroot() if case.get("name") == name)
        ET.SubElement(case, "skipped", type=skip_type, message="KD-87DEE784B97A")
        tree.write(directory / "junit.xml")
        return 0

    monkeypatch.setattr(runner, "_run_browser", incomplete)
    monkeypatch.setattr(runner, "_judge_once", lambda *_: pytest.fail("skipped regression was judged"))
    assert runner.run(root, live_jev=True) == 2
    report = json.loads(path.read_text())
    assert report["deterministic"]["status"] == "incomplete_evidence"
    assert report["jev"]["origin"] == "not-run"


def test_attempt_directories_are_synced_before_dispatch(synthetic_runner, monkeypatch) -> None:
    root, path = synthetic_runner
    synced = []
    real_sync = runner._fsync_directory
    def sync(directory):
        real_sync(directory)
        synced.append(directory)
    def judge(_request):
        assert root in synced and path.parent in synced
        return {"status": "unassessed", "reason": "synthetic", "results": {}}
    monkeypatch.setattr(runner, "_fsync_directory", sync)
    monkeypatch.setattr(runner, "_judge_once", judge)
    assert runner.run(root, live_jev=True) == 0


@pytest.mark.parametrize("preexisting", ["source", "root", "ancestors"])
def test_preexisting_unsynced_directory_is_repaired_before_dispatch(synthetic_runner, monkeypatch, preexisting) -> None:
    root, _ = synthetic_runner
    if preexisting == "ancestors":
        root = root / "new-ancestor" / "new-root"
    target = root / f"{SHA}-{advisory.RUBRIC_VERSION}"
    (target if preexisting == "source" else root).mkdir(parents=True, exist_ok=True)
    synced = []
    real_sync = runner._fsync_directory
    def sync(directory):
        real_sync(directory)
        synced.append(directory)
    def judge(_request):
        assert root in synced and root.parent in synced and target in synced
        return {"status": "unassessed", "reason": "synthetic", "results": {}}
    monkeypatch.setattr(runner, "_fsync_directory", sync)
    monkeypatch.setattr(runner, "_judge_once", judge)
    assert runner.run(root, live_jev=True) == 0


def test_hidden_identity_is_never_read_as_visible_evidence(tmp_path: Path) -> None:
    class HiddenIdentity:
        def is_visible(self):
            return False
        def inner_text(self):
            pytest.fail("hidden text must never enter model evidence")
    class VisibleLink:
        def is_visible(self):
            return True
    class Items:
        def __init__(self, items):
            self.items = items
        def all(self):
            return self.items
    class Surface:
        def locator(self, _selector):
            return Items([])
        def get_by_test_id(self, selector):
            return HiddenIdentity() if selector.endswith("active-identity") else Items([VisibleLink()])
    advisory.capture_observation(Surface(), list_state="populated", identity_available=True,
                                 width=1366, source_sha=SHA, output_dir=tmp_path)
    observation = json.loads(next(tmp_path.glob("*.json")).read_text())
    assert observation["observed"]["identity_text"] == ""
    assert observation["expected"]["identity_available"] is True
