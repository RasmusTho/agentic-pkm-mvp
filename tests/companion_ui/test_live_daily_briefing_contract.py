"""Deterministic refusals and real source/renderer paths; never live evidence."""

from __future__ import annotations

from copy import deepcopy
from datetime import date
from html import unescape
from html.parser import HTMLParser
import io
import json
import os
from pathlib import Path
import re
from types import SimpleNamespace
from typing import Any
from urllib.parse import urlparse, quote
import wave
import xml.etree.ElementTree as ET

import pytest

from tests.companion_ui import live_daily_briefing as pilot


def _manifest(tmp_path: Path) -> dict[str, Any]:
    root = tmp_path / "fixture"
    root.mkdir()
    moment = "---\ntype: moment\n---\nsynthetic\n"
    return {"channel": "test", "ui_url": "http://127.0.0.1:8112/", "api_url": "http://127.0.0.1:18002/",
            "expected_sha": "a" * 40, "expected_digest": "sha256:" + "b" * 64, "run_id": "contract-test",
            "output_dir": str(tmp_path / "evidence"), "vault_id": "synthetic-test", "vault_path": str(root),
            "resource_version": "synthetic-fixture-v1", "fixture_marker": ".daily-briefing-test.json",
            "fixture_marker_sha256": "c" * 64, "source_files": {"_system/moments/fixture.md": pilot._hash(moment.encode())},
            "moment_path": "_system/moments/fixture.md", "moment_full_text": moment,
            "calendar": {"calendar_id": "synthetic", "base_url": "http://briefing-calendar-fixture:8080",
                         "calendar_path": "/synthetic/calendar/", "uid": "synthetic-uid", "etag": "synthetic-etag"},
            "date": "2026-10-11", "effects": dict(pilot.EFFECT_LIMITS),
            "native_boundary_ref": "deterministic-fixture-boundary-is-not-live",
            "navigation_ms": 1000, "request_ms": 1000, "playback_ms": 1000}


def _evidence(d: dict[str, Any]) -> dict[str, Any]:
    return {"binding_verified": True, "fixture_verified": True, "gateway_upstream_verified": True,
            "running_sha": d["expected_sha"], "image_digest": d["expected_digest"], "date": d["date"],
            "briefing_exists": False}


class _Trace:
    def start(self, **kwargs: Any) -> None:
        pass

    def stop(self, *, path: str) -> None:
        Path(path).write_bytes(b"deterministic fixture, not a real browser trace")


class _Page:
    def __init__(self, d: dict[str, Any], version: str | None = None) -> None:
        self.d, self.version = d, version
        self.request = self
        self.requests: list[str] = []

    def set_default_timeout(self, _: int) -> None:
        pass

    set_default_navigation_timeout = set_default_timeout

    def fetch(self, url: str, **kwargs: Any) -> Any:
        assert kwargs["method"] == "GET", "mutation before qualified preflight"
        self.requests.append(url)
        return SimpleNamespace(ok=True, url=url, json=lambda: {"git_sha": self.version or self.d["expected_sha"]})

    def screenshot(self) -> bytes:
        return b"fixture screenshot"


class _Context:
    def __init__(self, d: dict[str, Any], version: str | None = None) -> None:
        self.tracing = _Trace()
        self.page = _Page(d, version)

    def new_page(self) -> _Page:
        return self.page

    def route(self, *args: Any) -> None:
        pass

    def add_init_script(self, _: str) -> None:
        pass

    def close(self) -> None:
        pass


class _Browser:
    def __init__(self, d: dict[str, Any], version: str | None = None) -> None:
        self.context = _Context(d, version)

    def new_context(self, **kwargs: Any) -> _Context:
        return self.context

    def close(self) -> None:
        pass


@pytest.mark.parametrize("wrong", ["sha", "digest", "fixture", "binding", "day", "fresh", "version"])
def test_preflight_rejects_wrong_identity_before_effect(tmp_path: Path, wrong: str) -> None:
    d = _manifest(tmp_path)
    observed = _evidence(d)
    key, value = {"sha": ("running_sha", "d" * 40), "digest": ("image_digest", "sha256:" + "d" * 64),
                  "fixture": ("fixture_verified", False), "binding": ("binding_verified", False),
                  "day": ("date", "2026-10-10"), "fresh": ("briefing_exists", True)}.get(wrong, ("unused", None))
    observed[key] = value
    browser = _Browser(d, "d" * 40 if wrong == "version" else None)
    flow = pilot.DailyBriefingFlow(d, browser, probe=lambda *_: observed)
    report = flow.run()
    assert report["scenarios"][0]["status"] == "blocked"
    assert not report["passed"]
    assert all(x == 0 for x in report["effects_consumed"].values())
    assert len(report["scenarios"]) == len(pilot.SCENARIOS)
    if wrong != "version":
        assert browser.context.page.requests == []
    assert json.loads((Path(d["output_dir"]) / "report.json").read_text())["passed"] is False


def test_required_scenarios_and_actual_proof_gate_acceptance() -> None:
    rows = [{"id": name, "status": "passed", "kind": "browser_local_failure" if name == "text_only_degradation" else "actual"} for name in pilot.SCENARIOS]
    good = {"scenarios": rows, "channel": "test", "execution_kind": "actual_native_browser",
            "fixture_restored": True, "native_boundary_ref": "native-operation:qualified",
            "diagnostics": {"audio": {"playback_observed": True, "audio_sha256": "a" * 64,
                                      "source_text_sha256": "b" * 64, "cache_key": "c" * 64,
                                      "frames": 100, "sample_rate": 22050},
                            "working_provenance": {"readable": True, "target": "Synthetic/source.md",
                                                   "source_sha256": "d" * 64, "source_uuid": "synthetic-note-uuid"}},
            "effects_consumed": dict(pilot.EFFECT_LIMITS),
            "end_identity_verified": True, "end_identity_error": None,
            "trace_status": "recorded", "junit_status": "recorded"}
    assert pilot.acceptance_passed(good)
    for status in ("failed", "blocked", "missing", "skipped", "xfail"):
        changed = deepcopy(good)
        changed["scenarios"][4]["status"] = status
        assert not pilot.acceptance_passed(changed)
    for key, value in (("scenarios", rows[:-1]), ("channel", "dev"), ("execution_kind", "deterministic_fixture"),
                       ("fixture_restored", False), ("native_boundary_ref", ""), ("diagnostics", {})):
        assert not pilot.acceptance_passed(good | {key: value})
    replaced = deepcopy(good)
    replaced["scenarios"][4]["kind"] = "browser_local_failure"
    assert not pilot.acceptance_passed(replaced)
    for key in ("audio", "working_provenance"):
        changed = deepcopy(good)
        del changed["diagnostics"][key]
        assert not pilot.acceptance_passed(changed)
    for key in ("end_identity_verified", "trace_status", "junit_status"):
        assert not pilot.acceptance_passed(good | {key: None})


def test_invocation_evidence_preserves_failure_without_feature_acceptance(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.chdir(tmp_path)
    d = _manifest(tmp_path)
    path = tmp_path / "native-manifest.json"
    path.write_text(json.dumps({"schema": "native-web-pilot-manifest.v1", "pilot": "daily-briefing",
        "native_context": str(pilot.NATIVE_CONTEXT), "output_dir": d["output_dir"],
        "report_binding": {"channel": "test", "source_sha": d["expected_sha"], "image_digest": d["expected_digest"],
                           "run_id": d["run_id"], "resource_version": d["resource_version"]}}))
    path.chmod(0o600)

    def missing_seam() -> Any:
        raise pilot.Blocked("reviewed_native_web_seam_not_available")

    monkeypatch.setattr(pilot, "_native_seam", missing_seam)
    report = pilot.execute_manifest(path)
    assert pilot.invocation_evidence_recorded(report)
    assert not pilot.acceptance_passed(report) and report["passed"] is False
    assert report["qualification"] == "not_established"
    assert report["execution_kind"] == "actual_invocation_refused"
    assert all(x["status"] == "blocked" and x["observation"] == "not_executed" for x in report["scenarios"])
    assert report["effects_consumed"] == dict.fromkeys(pilot.EFFECT_LIMITS, 0)
    retained = Path(report["output_dir"]) / "report.json"
    assert json.loads(retained.read_text()) == report
    assert retained.stat().st_mode & 0o777 == 0o600
    assert report["trace_status"] == "not_started" and not retained.with_name("trace.zip").exists()
    assert not pilot.invocation_evidence_recorded(report | {"scenarios": report["scenarios"][:-1]})
    assert not pilot.invocation_evidence_recorded(report | {"passed": True})


@pytest.mark.parametrize("fault", ["launch", "context", "tracing"])
def test_constructor_failure_records_original_eight_without_overwrite(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, fault: str,
) -> None:
    from tests.companion_ui.test_live_deep_review_contract import _playwright_fixture
    path, _ = _fixed_native_manifest(tmp_path, monkeypatch)
    d = pilot.load_manifest(path)
    browser = _Browser(d)
    sync_api = _playwright_fixture(monkeypatch, browser)
    monkeypatch.setattr(pilot, "_native_seam", lambda: object())
    monkeypatch.setattr(pilot, "native_probe", lambda *_: pytest.fail("contact before startup admission"))

    def fail(**kwargs: Any) -> Any:
        raise RuntimeError("explicit constructor failure")

    if fault == "launch":
        from contextlib import nullcontext
        sync_api.sync_playwright = lambda: nullcontext(SimpleNamespace(chromium=SimpleNamespace(launch=fail)))
    elif fault == "context":
        browser.new_context = fail
    else:
        browser.context.tracing.start = fail
    report = pilot.execute_manifest(path)
    assert [row["id"] for row in report["scenarios"]] == list(pilot.SCENARIOS)
    assert all(row["status"] == "blocked" and row["reason"] == "runner_startup_failed:RuntimeError"
               for row in report["scenarios"])
    assert report["effects_consumed"] == dict.fromkeys(pilot.EFFECT_LIMITS, 0)
    assert report["observed_native_identity"] is None and not report["end_identity_verified"]
    assert pilot.invocation_evidence_recorded(report) and not pilot.acceptance_passed(report)
    output = Path(report["output_dir"])
    before = {p.name: p.read_bytes() for p in output.iterdir()}
    with pytest.raises(pilot.Blocked, match="must_be_preserved"):
        pilot.execute_manifest(path)
    assert {p.name: p.read_bytes() for p in output.iterdir()} == before


@pytest.mark.parametrize("fault", ["report.json.next", "trace.zip", "removed", "replaced"])
def test_constructor_failure_preserves_partial_and_removed_or_replaced_directory(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, fault: str,
) -> None:
    from tests.companion_ui.test_live_deep_review_contract import _playwright_fixture
    path, _ = _fixed_native_manifest(tmp_path, monkeypatch)
    d = pilot.load_manifest(path)
    output = Path(d["output_dir"])
    browser = _Browser(d)
    _playwright_fixture(monkeypatch, browser)
    monkeypatch.setattr(pilot, "_native_seam", lambda: object())

    def fail(**kwargs: Any) -> Any:
        if fault == "removed":
            output.rmdir()
        elif fault == "replaced":
            output.rename(output.with_name("original-owned-directory"))
            output.mkdir()
            (output / "foreign.txt").write_text("preserve foreign evidence")
        else:
            (output / fault).write_text("preserve partial evidence")
        raise RuntimeError("startup after partial evidence")

    browser.new_context = fail
    with pytest.raises(pilot.Blocked, match="must_be_preserved"):
        pilot.execute_manifest(path)
    if fault == "removed":
        assert not output.exists()
    elif fault == "replaced":
        assert (output / "foreign.txt").read_text() == "preserve foreign evidence"
        assert not (output / "report.json").exists()
    else:
        assert (output / fault).read_text() == "preserve partial evidence"
        assert list(output.iterdir()) == [output / fault]


def test_startup_junit_failure_keeps_truthful_original_eight_partial_report(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.chdir(tmp_path)
    opened = os.open
    def reject_junit(path: Any, *args: Any, **kwargs: Any) -> int:
        if path == "junit.xml":
            raise OSError("bounded JUnit writer failure")
        return opened(path, *args, **kwargs)
    monkeypatch.setattr(pilot.os, "open", reject_junit)
    with pytest.raises(OSError, match="JUnit"):
        pilot.execute_manifest(None)
    report_path, = (tmp_path / ".codex-tmp").glob("daily-briefing-refusal-*/report.json")
    report = json.loads(report_path.read_bytes())
    assert [row["id"] for row in report["scenarios"]] == list(pilot.SCENARIOS)
    assert all(row["status"] == "blocked" for row in report["scenarios"])
    assert report["junit_status"] == "not_started" and not report_path.with_name("junit.xml").exists()
    assert report["effects_consumed"] == dict.fromkeys(pilot.EFFECT_LIMITS, 0)
    assert not report["passed"] and report_path.stat().st_mode & 0o777 == 0o600


@pytest.mark.parametrize("artifact", ["preflight.png", "trace.zip", "junit.xml"])
def test_run_preserves_prior_failure_artifact_bytes(tmp_path: Path, artifact: str) -> None:
    d = _manifest(tmp_path)
    flow = pilot.DailyBriefingFlow(d, _Browser(d), probe=lambda *_: _evidence(d) | {"binding_verified": False})
    prior = flow.output / artifact
    prior.write_bytes(b"foreign existing artifact")
    if artifact == "junit.xml":
        with pytest.raises(FileExistsError):
            flow.run()
    else:
        assert not flow.run()["passed"]
    assert prior.read_bytes() == b"foreign existing artifact"
    report = json.loads((flow.output / "report.json").read_bytes())
    assert [row["id"] for row in report["scenarios"]] == list(pilot.SCENARIOS)
    assert report["effects_consumed"] == dict.fromkeys(pilot.EFFECT_LIMITS, 0)
    assert not report["passed"]


@pytest.mark.parametrize("fault", [None, "native_identity", "configuration_hashes", "source_sha256", "tts_routes", "effects", "runner"])
def test_end_identity_required_before_acceptance(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, fault: str | None,
) -> None:
    d = _manifest(tmp_path)
    baseline = _evidence(d) | {"native_identity": {"api_pid": 123}, "configuration_hashes": {"vault": "a"},
                               "source_sha256": "c" * 64, "tts_config": {"local_only": True}, "tts_routes": {"sv-SE": "piper"}}
    observed = deepcopy(baseline) | {"briefing_exists": True, "briefing_sha256": "b" * 64,
                                    "degraded_sections": [], "native_effects": dict(pilot.EFFECT_LIMITS)}
    flow = pilot.DailyBriefingFlow(d, _Browser(d), probe=lambda *_: observed)
    flow.admitted = flow.generated = flow.restored = True
    flow.effects = dict(pilot.EFFECT_LIMITS)
    flow.baseline = baseline
    flow.diagnostics["generation"] = {"briefing_sha256": "b" * 64}
    if fault == "runner":
        monkeypatch.setattr(pilot, "_harness_hashes", lambda: {})
    elif fault == "effects":
        observed["native_effects"]["first_contact"] = 1
    elif fault:
        observed[fault] = "foreign"
    if fault:
        with pytest.raises(pilot.Blocked):
            flow._verify_end()
        assert not flow.end_identity_verified
    else:
        flow._verify_end()
        assert flow.end_identity_verified
    report = flow._snapshot()
    assert report["end_identity_verified"] == (fault is None)
    assert not pilot.acceptance_passed(report)  # No actual eight native/browser outcomes.


@pytest.mark.parametrize("fault", [None, "end_identity", "partial_scenario"])
def test_run_retains_all_eight_and_enforces_final_observation(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, fault: str | None,
) -> None:
    d = _manifest(tmp_path)
    observed = _evidence(d) | {"briefing_exists": True, "briefing_sha256": "b" * 64,
        "degraded_sections": [], "native_identity": {"api_pid": 123}, "configuration_hashes": {"vault": "a"},
        "source_sha256": "c" * 64, "tts_config": {"local_only": True}, "tts_routes": {"sv-SE": "piper"},
        "native_effects": dict.fromkeys(pilot.EFFECT_LIMITS, 0)}
    flow = pilot.DailyBriefingFlow(d, _Browser(d), probe=lambda *_: observed)
    flow.baseline = deepcopy(observed)
    flow.admitted = flow.generated = flow.restored = True
    flow.diagnostics["generation"] = {"briefing_sha256": "b" * 64}
    calls = []
    for name in pilot.SCENARIOS:
        def scenario(scenario_name: str = name) -> None:
            calls.append(scenario_name)
            if fault == "partial_scenario" and scenario_name == "partial_source":
                raise pilot.Blocked("bounded_fixture_scenario_refusal")
        monkeypatch.setattr(flow, name, scenario)
    if fault == "end_identity":
        observed["native_identity"] = {"api_pid": 456}
    report = flow.run()
    assert calls == list(pilot.SCENARIOS)
    assert [row["id"] for row in report["scenarios"]] == list(pilot.SCENARIOS)
    assert report["end_identity_verified"] == (fault != "end_identity")
    assert report["trace_status"] == report["junit_status"] == "recorded"
    assert report["effects_consumed"] == dict.fromkeys(pilot.EFFECT_LIMITS, 0)
    cases = ET.parse(flow.output / "junit.xml").findall("testcase")
    assert [case.get("name") for case in cases] == list(pilot.SCENARIOS)
    assert sum(case.find("failure") is not None for case in cases) == int(fault is not None)
    assert not report["passed"] and report["execution_kind"] == "deterministic_fixture"
    assert json.loads((flow.output / "report.json").read_bytes()) == report
    assert all((flow.output / name).stat().st_mode & 0o777 == 0o600 for name in ("report.json", "trace.zip", "junit.xml"))


@pytest.mark.parametrize("fault", ["content", "replacement", "reservation", "during_snapshot"])
def test_report_drift_never_overwrites_foreign_bytes_or_forwards_effect(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, fault: str,
) -> None:
    d = _manifest(tmp_path)
    flow = pilot.DailyBriefingFlow(d, _Browser(d), probe=lambda *_: _evidence(d))
    flow.admitted = True
    forwarded = []
    flow.probe = pilot.native_probe
    monkeypatch.setattr(pilot, "_native_seam", lambda: SimpleNamespace(before_effect=lambda *args: forwarded.append(args)))
    report = flow.output / "report.json"
    if fault == "content":
        report.write_bytes(b"foreign changed report")
    elif fault == "replacement":
        prior = report.read_bytes()
        report.rename(flow.output / "original-report.json")
        report.write_bytes(prior)
    elif fault == "reservation":
        (flow.output / "report.json.next").write_bytes(b"foreign reserved candidate")
    else:
        sync = os.fsync
        def drift_at_flush(descriptor: int) -> None:
            candidate = flow.output / "report.json.next"
            if candidate.exists() and os.fstat(descriptor).st_ino == candidate.stat().st_ino:
                report.write_bytes(b"foreign changed during snapshot")
            sync(descriptor)
        monkeypatch.setattr(pilot.os, "fsync", drift_at_flush)
    expected = report.read_bytes()
    with pytest.raises((pilot.Blocked, FileExistsError)):
        flow._consume("tts_plan")
    assert forwarded == []
    assert report.read_bytes() == (b"foreign changed during snapshot" if fault == "during_snapshot" else expected)
    if fault == "reservation":
        assert (flow.output / "report.json.next").read_bytes() == b"foreign reserved candidate"


def test_failed_version_read_never_admits_later_effect(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    d = _manifest(tmp_path)
    browser = _Browser(d)

    def unavailable(*args: Any, **kwargs: Any) -> Any:
        raise RuntimeError("bounded transport failure")

    monkeypatch.setattr(browser.context.page, "fetch", unavailable)
    flow = pilot.DailyBriefingFlow(d, browser, probe=lambda *_: _evidence(d))
    report = flow.run()
    assert report["scenarios"][0]["status"] == "failed"
    assert flow.admitted is False
    assert report["effects_consumed"] == dict.fromkeys(pilot.EFFECT_LIMITS, 0)


@pytest.mark.parametrize(("visible_date", "date_visible", "time_count", "accepted"), [
    pytest.param("2026-10-11", True, 1, True, id="visible-current"),
    pytest.param("2026-10-11", False, 1, False, id="hidden-current"),
    pytest.param("2026-10-10", True, 1, False, id="stale"),
    pytest.param(None, True, 1, False, id="undated"),
    pytest.param("2026-10-11", True, 0, False, id="absent-time"),
    pytest.param("2026-10-11", True, 2, False, id="ambiguous-time"),
])
def test_stale_or_undated_served_card_cannot_pass(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, visible_date: str | None,
    date_visible: bool, time_count: int, accepted: bool,
) -> None:
    from companion_ui.workspace.day_start_card import render_day_start_card_html

    d = _manifest(tmp_path)
    rendered = render_day_start_card_html({"state": "full", "date": visible_date, "sections": []})
    dates = re.findall(r"<time>(.*?)</time>", rendered)
    attributes = dict(re.findall(r'(data-[a-z-]+)="([^"]*)"', rendered))
    calls = {"visibility": 0, "date_text": 0, "summary": 0}

    def is_visible() -> bool:
        calls["visibility"] += 1
        return date_visible

    def date_text() -> str:
        calls["date_text"] += 1
        return unescape("".join(dates))

    def click_summary() -> None:
        calls["summary"] += 1

    date_locator = SimpleNamespace(count=lambda: time_count, is_visible=is_visible, inner_text=date_text)
    card = SimpleNamespace(
        count=lambda: 1, get_attribute=attributes.get,
        locator=lambda selector: date_locator if selector == "time" else SimpleNamespace(
            count=lambda: 0, click=click_summary,
        ),
    )
    flow = pilot.DailyBriefingFlow(d, _Browser(d), probe=lambda *_: _evidence(d))
    flow.generated = True
    flow.projection = {"sections": []}
    monkeypatch.setattr(flow, "_navigate", lambda: None)
    monkeypatch.setattr(flow.page, "get_by_test_id", lambda _: card, raising=False)
    if accepted:
        flow.one_read_only_card()
    else:
        with pytest.raises(AssertionError, match="card_date_does_not_match_admitted_day"):
            flow.one_read_only_card()
    assert calls["visibility"] == int(time_count == 1)
    assert calls["date_text"] == int(time_count == 1 and date_visible)
    assert calls["summary"] == int(accepted)
    assert flow.effects == dict.fromkeys(pilot.EFFECT_LIMITS, 0)


@pytest.mark.parametrize("source", ["", pilot._PROBE.replace("from app.vault.paths import get_vault_capture_note_rel\n", "")])
def test_passive_prefix_drift_cannot_extend_into_capture_or_effects(source: str) -> None:
    with pytest.raises(pilot.Blocked, match="prefix_drift"):
        pilot.passive_binding_prefix(source)


def test_pending_dated_note_refuses_before_scheduled_producer(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    d = _manifest(tmp_path)
    flow = pilot.DailyBriefingFlow(d, _Browser(d), probe=lambda *_: _evidence(d))
    monkeypatch.setattr(pilot, "_native_seam", lambda: pytest.fail("native scheduled producer reached an absent artifact"))
    with pytest.raises(pilot.Blocked, match="existing_dated"):
        flow._scheduled_replay()
    assert all(x == 0 for x in flow.effects.values())


def test_scheduled_replay_consumes_existing_native_zero_write_ack(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    d = _manifest(tmp_path)
    observed = _evidence(d) | {"briefing_exists": True, "briefing_path": "_system/briefings/today.md",
                               "briefing_sha256": "b" * 64}
    flow = pilot.DailyBriefingFlow(d, _Browser(d), probe=lambda *_: observed)
    replay = {"target": observed["briefing_path"], "date": d["date"], "triggered": False,
              "reason": "already_generated_today", "durable_writes": 0, "briefing_sha256": "b" * 64}
    calls = []
    def scheduled() -> dict[str, Any]:
        calls.append("actual_native_transport_boundary")
        return replay
    monkeypatch.setattr(pilot, "_native_seam", lambda: SimpleNamespace(scheduled_replay=scheduled))
    assert flow._scheduled_replay() == replay
    replay["durable_writes"] = 1
    with pytest.raises(pilot.Blocked, match="producer_mismatch"):
        flow._scheduled_replay()
    assert len(calls) == 2
    assert flow.effects == dict.fromkeys(pilot.EFFECT_LIMITS, 0)


@pytest.mark.parametrize("fault", [None, "source_count", "regeneration_count", "source_prestate", "source_poststate",
                                   "regeneration_prestate", "regeneration_poststate", "receipt", "observer", "restored_version"])
def test_fixed_source_cas_and_normal_regeneration_ack_require_actual_lineage(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, fault: str | None,
) -> None:
    d = _manifest(tmp_path)
    flow = pilot.DailyBriefingFlow(d, _Browser(d), probe=lambda *_: _evidence(d))
    target = "_system/briefings/" + d["date"] + ".md"
    healthy, partial = "b" * 64, "c" * 64
    bad = pilot._hash(b"---\ninvalid: [\n---\nSynthetic unavailable source.\n")
    seed = d["source_files"][d["moment_path"]]
    flow.baseline["briefing_path"] = target
    flow.diagnostics["generation"] = {"briefing_sha256": healthy}
    def ack(effect: str) -> dict[str, Any]:
        return {"target": d["moment_path"], "receipt": {"operation": "write_note", "outcome": "written",
                "locator": {"path": d["moment_path"]}}, "pre_sha256": seed if effect == "degrade_source" else bad,
                "post_sha256": bad if effect == "degrade_source" else seed, "source_writes": 1, "regenerations": 1,
                "regeneration": {"receipt": {"operation": "write_note", "outcome": "written", "locator": {"path": target}},
                    "target": target, "pre_sha256": healthy if effect == "degrade_source" else partial,
                    "post_sha256": partial if effect == "degrade_source" else healthy,
                    "degraded_sections": ["moments"] if effect == "degrade_source" else []}}
    degradation, restoration = ack("degrade_source"), ack("restore_source")
    flow.diagnostics["partial_source"] = deepcopy(degradation)
    result = restoration if fault == "restored_version" else degradation
    observer = deepcopy(result)
    if fault == "source_count":
        result["source_writes"] = True
    elif fault == "regeneration_count":
        result["regenerations"] = 0
    elif fault == "source_prestate":
        result["pre_sha256"] = "d" * 64
    elif fault == "source_poststate":
        result["post_sha256"] = "d" * 64
    elif fault == "regeneration_prestate":
        result["regeneration"]["pre_sha256"] = "d" * 64
    elif fault == "regeneration_poststate":
        result["regeneration"]["post_sha256"] = healthy
    elif fault == "receipt":
        result["regeneration"]["receipt"]["operation"] = "unrelated_write"
    elif fault == "observer":
        observer["post_sha256"] = "d" * 64
    elif fault == "restored_version":
        result["regeneration"]["post_sha256"] = "d" * 64
    effect = "restore_source" if fault == "restored_version" else "degrade_source"
    observed = {"source_acknowledgements": {effect: observer}, "briefing_sha256": observer["regeneration"]["post_sha256"],
                "degraded_sections": observer["regeneration"]["degraded_sections"]}
    monkeypatch.setattr(flow, "_native", lambda: observed)
    if fault:
        with pytest.raises((pilot.Blocked, AssertionError)):
            flow._require_regeneration_ack(result, effect)
    else:
        flow._require_regeneration_ack(degradation, "degrade_source")
        observed.update(source_acknowledgements={"restore_source": restoration}, briefing_sha256=healthy, degraded_sections=[])
        flow._require_regeneration_ack(restoration, "restore_source")
    assert flow.effects == dict.fromkeys(pilot.EFFECT_LIMITS, 0)


@pytest.mark.parametrize("transition", [None, {}, {"moment_path": "foreign.md"}])
def test_unadmitted_source_regeneration_refuses_before_source_write(tmp_path: Path, transition: Any) -> None:
    d = _manifest(tmp_path)
    observed = _evidence(d) | {"source_transition": transition}
    flow = pilot.DailyBriefingFlow(d, _Browser(d), probe=lambda *_: observed)
    flow.generated = flow.admitted = True
    flow.baseline["briefing_path"] = "_system/briefings/" + d["date"] + ".md"
    with pytest.raises(pilot.Blocked, match="regeneration_not_admitted"):
        flow.partial_source()
    assert flow.effects["degrade_source"] == 0 and flow.degraded is False


def test_tts_request_uses_exact_served_payload_before_forwarding(tmp_path: Path) -> None:
    d = _manifest(tmp_path)
    flow = pilot.DailyBriefingFlow(d, _Browser(d), probe=lambda *_: _evidence(d))
    flow.admitted = flow.playback_armed = True
    flow.tts_payloads = {"tts_plan": {"text": "Explicit synthetic served text", "rate": 1.0}}

    class Route:
        def __init__(self, payload: Any) -> None:
            self.request = SimpleNamespace(url=d["ui_url"] + "api/companion/tts/plan", method="POST", post_data_json=payload)
            self.forwarded = False

        def continue_(self) -> None:
            self.forwarded = True

        def abort(self, reason: str) -> None:
            pass

    for payload in ({"text": "Different input", "rate": 1.0}, {"text": "Explicit synthetic served text", "rate": True}, {}):
        route = Route(payload)
        flow._guard(route)
        assert not route.forwarded and flow.effects["tts_plan"] == 0
    exact = Route(flow.tts_payloads["tts_plan"])
    flow._guard(exact)
    assert exact.forwarded and flow.effects["tts_plan"] == 1
    replay = Route(flow.tts_payloads["tts_plan"])
    flow._guard(replay)
    assert not replay.forwarded and flow.effects["tts_plan"] == 1


def test_gateway_document_contact_requires_one_precharged_target(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    d = _manifest(tmp_path)
    flow = pilot.DailyBriefingFlow(d, _Browser(d), probe=lambda *_: _evidence(d) | {"briefing_exists": True})
    flow.admitted = True
    routes = []
    class Route:
        request = SimpleNamespace(url=d["ui_url"], method="GET")
        def continue_(self) -> None:
            routes.append("forwarded")
        def abort(self, _: str) -> None:
            routes.append("refused")
    flow._guard(Route())
    assert routes == ["refused"] and flow.effects["navigation"] == 0
    with pytest.raises(pilot.Blocked, match="fixed_gateway"):
        flow._navigate(d["ui_url"] + "?unadmitted=1")
    assert flow.effects["navigation"] == 0
    def goto(url: str, **kwargs: Any) -> Any:
        assert flow.effects["navigation"] == 1  # Reserved before the gateway's first-contact GET.
        flow._guard(Route())
        flow._guard(Route())  # A duplicate document contact is refused.
        return SimpleNamespace(ok=True)
    flow.page.url = d["ui_url"]
    monkeypatch.setattr(flow.page, "goto", goto, raising=False)
    monkeypatch.setattr(flow.page, "locator", lambda selector: SimpleNamespace(
        get_attribute=lambda _: d["channel"] if "channel" in selector else d["expected_sha"],
    ), raising=False)
    flow._navigate()
    assert routes == ["refused", "forwarded", "refused"]
    assert flow.effects["navigation"] == 1 and flow.navigation_target is None


@pytest.mark.parametrize("destination", ["native_root", "served_note"])
def test_actual_native_root_and_selected_note_are_canonical_once(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, destination: str,
) -> None:
    path, _ = _fixed_native_manifest(tmp_path, monkeypatch)
    d = pilot.load_manifest(path)
    assert d["ui_url"] == "http://127.0.0.1:8090"  # Actual delivered producer's shape.
    flow = pilot.DailyBriefingFlow(d, _Browser(d), probe=lambda *_: _evidence(d) | {"briefing_exists": True})
    flow.admitted = True
    flow.provenance_href = d["ui_url"] + "/?note_path=Synthetic%2Fsource.md"
    flow.provenance_path = "Synthetic/source.md"
    routes = []
    class Route:
        def __init__(self, url: str) -> None:
            self.request = SimpleNamespace(url=url, method="GET")
        def continue_(self) -> None:
            routes.append("forwarded")
        def abort(self, _: str) -> None:
            routes.append("refused")
    def goto(target: str, **kwargs: Any) -> Any:
        parsed = urlparse(target)
        canonical = parsed._replace(path=parsed.path or "/").geturl()
        flow.page.url = canonical
        assert flow.effects["navigation"] == 1
        flow._guard(Route(canonical))
        flow._guard(Route(canonical))
        flow._guard(Route(canonical + ("&" if parsed.query else "?") + "unadmitted=1"))
        return SimpleNamespace(ok=True)
    monkeypatch.setattr(flow.page, "goto", goto, raising=False)
    monkeypatch.setattr(flow.page, "locator", lambda selector: SimpleNamespace(
        get_attribute=lambda _: d["channel"] if "channel" in selector else d["expected_sha"],
    ), raising=False)
    flow._navigate(None if destination == "native_root" else flow.provenance_href)
    assert routes == ["forwarded", "refused", "refused"]
    assert flow.effects["navigation"] == 1 and flow.navigation_target is None


class _RenderedReadingText(HTMLParser):
    """Collect only the real served renderer's reading region; no Markdown renderer."""
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.depth = 0
        self.text = []
        self.visible = []
    def handle_starttag(self, tag: str, attrs: Any) -> None:
        if dict(attrs).get("data-testid") == "workspace-note-rendered":
            self.depth = 1
        elif self.depth and tag not in {"br", "hr", "img", "input", "meta", "link"}:
            self.depth += 1
    def handle_endtag(self, tag: str) -> None:
        if self.depth:
            if tag in {"p", "li", "h1", "h2", "h3", "pre"}:
                self.visible.append("\n")
            self.depth -= 1
    def handle_data(self, data: str) -> None:
        if self.depth:
            self.text.append(data)
            self.visible.append(data)


@pytest.mark.parametrize("formatting", [False, True], ids=["canonical-prepared", "ordinary-markdown"])
@pytest.mark.parametrize("fault", [None, "api_path", "api_uuid", "source_hash", "api_body", "invisible",
                                   "dom_path", "dom_text", "visible_omission"])
def test_opened_provenance_binds_canonical_raw_source_and_actual_rendered_reading(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, formatting: bool, fault: str | None,
) -> None:
    from app.knowledge.write_ops import write_note_relative
    from app.rebuildability.product_total_loss import parse_bounded_frontmatter
    from companion_ui.workspace.serve_dev_page import render_index_html

    d = _native_fixture(tmp_path, monkeypatch)  # Calls actual canonical prepare_sources/writers.
    target, = (p for p in d["source_files"] if p.startswith("Synthetic/") and p.endswith(".md"))
    source = Path(d["vault_path"]) / target
    raw = source.read_bytes()
    frontmatter, _, error = parse_bounded_frontmatter(raw.decode())
    assert error is None and frontmatter["synthetic"] is True
    if formatting:
        original_frontmatter = raw.decode().split("---", 2)[1]
        text = "---" + original_frontmatter + "---\n# Synthetic source\n\n**Bold evidence** and _readable prose_.\n\n- One source\n- Two details\n"
        write_note_relative(target, text, vault_root=Path(d["vault_path"]), expected_version=pilot._hash(raw))
        raw = source.read_bytes()
        d["source_files"][target] = pilot._hash(raw)
    artifact = {"note_path": target, "artifact_id": frontmatter["uuid"], "body": raw.decode(),
                "content_hash": pilot._hash(raw)}
    html = render_index_html(api_base_url=d["api_url"], note_path=target,
                             fields={"title": "Synthetic source", "note_path": target,
                                     "artifact_id": artifact["artifact_id"], "body": artifact["body"],
                                     "content_hash": artifact["content_hash"]})
    parsed = _RenderedReadingText()
    parsed.feed(html)
    dom_text, visible_text = "".join(parsed.text), "".join(parsed.visible)
    assert dom_text and "uuid:" not in dom_text and "synthetic:" not in dom_text
    if formatting:
        assert "Bold evidence" in dom_text and "**Bold evidence**" not in dom_text
    flow = pilot.DailyBriefingFlow(d, _Browser(d), probe=lambda *_: _evidence(d))
    flow.provenance_path, flow.provenance_href = target, d["ui_url"] + "?note_path=" + quote(target, safe="")
    flow.page.url = flow.provenance_href
    if fault == "api_path":
        artifact["note_path"] = "Synthetic/foreign.md"
    elif fault == "api_uuid":
        artifact["artifact_id"] = "foreign-uuid"
    elif fault == "source_hash":
        d["source_files"][target] = "f" * 64
    elif fault == "api_body":
        artifact["body"] += "\nUnadmitted API bytes."
    elif fault == "dom_text":
        dom_text += "Foreign source"
    elif fault == "visible_omission":
        visible_text = "Source text exists"  # Nonempty cannot prove complete readability.
    reading = SimpleNamespace(count=lambda: 1, is_visible=lambda: fault != "invisible",
                              inner_text=lambda: visible_text, text_content=lambda: dom_text)
    marker = SimpleNamespace(count=lambda: 1, get_attribute=lambda key:
        ("Synthetic/foreign.md" if fault == "dom_path" else target) if key == "data-note-path" else artifact["content_hash"])
    monkeypatch.setattr(flow.page, "get_by_test_id", lambda name: reading if name == "workspace-note-rendered" else marker, raising=False)
    monkeypatch.setattr(flow.page, "locator", lambda _: reading, raising=False)  # Old failing .note-body consumer.
    monkeypatch.setattr(flow, "_json", lambda _: {"artifact": artifact})
    if fault:
        with pytest.raises((AssertionError, pilot.Blocked)):
            flow._prove_opened_source()
        assert "working_provenance" not in flow.diagnostics
    else:
        flow._prove_opened_source()
        assert flow.diagnostics["working_provenance"] == {"target": target, "source_sha256": pilot._hash(raw),
                                                         "source_uuid": artifact["artifact_id"], "readable": True}
    assert flow.effects == dict.fromkeys(pilot.EFFECT_LIMITS, 0)


def _fixed_native_manifest(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> tuple[Path, dict[str, Any]]:
    d = _manifest(tmp_path)
    native_context = tmp_path / "native-context.json"
    monkeypatch.setattr(pilot, "NATIVE_CONTEXT", native_context)
    monkeypatch.setattr(pilot, "NATIVE_OUTPUT", Path(d["output_dir"]))
    monkeypatch.setenv("VAULT_ROOT", d["vault_path"])
    identity = {"source_sha": d["expected_sha"], "image_digest": d["expected_digest"], "channel": "test",
                "resource_generation": "00000000-0000-4000-8000-000000000001", "resource_tree": "c" * 40,
                "operation_id": "00000000-0000-4000-8000-000000000002", "app_image_id": "sha256:" + "d" * 64}
    fixture = {"logical_vault_id": d["vault_id"], "local_clone_id": "synthetic-clone", "settings_hash": "e" * 64}
    start = {"api": identity | {"fixture": fixture, "api_pid": 123, "api_module": "/app/app/main.py"},
             "ui_pid": 124, "configuration_hash": "f" * 64}
    binding = {"source_sha": d["expected_sha"], "image_digest": d["expected_digest"], "channel": "test",
               "run_id": identity["resource_generation"], "resource_version": identity["resource_tree"],
               "native_boundary_ref": pilot._hash_json({"native_identity": identity, "start": start}),
               "fixture_metadata_sha256": pilot._hash_json(fixture), "local_instance_id": "synthetic-clone",
               "harness_hashes": {"live_core_flow.py": pilot._harness_hashes()["live_core_flow.py"],
                                  "live_deep_review.py": "0" * 64},
               "configuration_hashes": {"runtime": start["configuration_hash"], "vault": fixture["settings_hash"]}}
    ctx = {"schema": "native-web-context.v1", "native_identity": identity, "start": start,
           "fixture": fixture, "report_binding": binding, "api_url": "http://127.0.0.1:8000",
           "ui_url": "http://127.0.0.1:8090", "caldav_url": "http://127.0.0.1:8870",
           "reports": {"daily-briefing": str(Path(d["output_dir"]) / "report.json")},
           "calendar": {"calendar_uid": "synthetic-uid", "calendar_etag": "synthetic-etag"},
           "daily_start_sources": {k: d[k] for k in ("source_files", "moment_path", "moment_full_text", "fixture_marker", "fixture_marker_sha256")}}
    native_context.write_text(json.dumps(ctx))
    native_context.chmod(0o600)
    path = tmp_path / "pilot-manifest.json"
    path.write_text(json.dumps({"schema": "native-web-pilot-manifest.v1", "pilot": "daily-briefing",
                               "native_context": str(native_context), "output_dir": d["output_dir"], "report_binding": binding}))
    path.chmod(0o600)
    return path, ctx


def test_native_manifest_binds_actual_start_sources_after_serial_wrapper(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    path, ctx = _fixed_native_manifest(tmp_path, monkeypatch)
    loaded = pilot.load_manifest(path)
    assert loaded["source_files"] == ctx["daily_start_sources"]["source_files"]
    assert loaded["native_context"]["start"] == ctx["start"]
    assert loaded["effects"] == pilot.EFFECT_LIMITS


@pytest.mark.parametrize("fault", ["manifest", "context", "harness"])
def test_frozen_native_inputs_refuse_before_source_read_or_effect(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, fault: str,
) -> None:
    path, ctx = _fixed_native_manifest(tmp_path, monkeypatch)
    d = pilot.load_manifest(path)
    if fault == "harness":
        monkeypatch.setattr(pilot, "_harness_hashes", lambda: {})
    else:
        target = path if fault == "manifest" else pilot.NATIVE_CONTEXT
        raw = json.loads(target.read_bytes()) | {"unadmitted_change": True}
        target.write_text(json.dumps(raw))
    monkeypatch.setattr(pilot, "_native_seam", lambda: object())
    monkeypatch.setattr(pilot, "_read_json_url", lambda *_: {"identity": ctx["start"]["api"]})
    monkeypatch.setattr(pilot, "_local_fixture_read", lambda *_: pytest.fail("source read after frozen input changed"))
    with pytest.raises(pilot.Blocked, match="runner_changed|input_identity_changed"):
        pilot.native_probe(d)


@pytest.mark.parametrize("fault", ["source", "origin", "start_inventory", "marker"])
def test_native_context_drift_cannot_admit_a_browser_effect(tmp_path: Path, monkeypatch: pytest.MonkeyPatch, fault: str) -> None:
    path, ctx = _fixed_native_manifest(tmp_path, monkeypatch)
    if fault == "source":
        ctx["native_identity"]["source_sha"] = "f" * 40
    elif fault == "origin":
        ctx["api_url"] = "http://127.0.0.1:18002"
    elif fault == "start_inventory":
        del ctx["daily_start_sources"]
    else:
        ctx["daily_start_sources"]["fixture_marker"] = "../owner.json"
    pilot.NATIVE_CONTEXT.write_text(json.dumps(ctx))
    with pytest.raises((ValueError, pilot.Blocked)):
        pilot.load_manifest(path)


def test_unqualified_host_cannot_fall_back_to_legacy_native_probe(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    d = _manifest(tmp_path)
    monkeypatch.setattr(pilot, "_read_json_url", lambda *_: pytest.fail("HTTP before qualified same-image native context"))
    with pytest.raises(pilot.Blocked):
        pilot.native_probe(d)


@pytest.mark.parametrize("change", [{"effects": {}}, {"channel": "prod"}, {"ui_url": "http://127.0.0.1:8111/"},
                                    {"moment_path": "../owner.md"}, {"expected_digest": "unpinned"},
                                    {"calendar": {"base_url": "https://calendar.example.com"}}])
def test_manifest_refuses_unbounded_effects(tmp_path: Path, change: dict[str, Any]) -> None:
    d = _manifest(tmp_path) | change
    path = tmp_path / "manifest.json"
    path.write_text(json.dumps(d))
    path.chmod(0o600)
    with pytest.raises(ValueError):
        pilot.validate_legacy_manifest(path)


def test_manifest_and_evidence_are_private(tmp_path: Path) -> None:
    d = _manifest(tmp_path)
    path = tmp_path / "manifest.json"
    path.write_text(json.dumps(d))
    with pytest.raises(ValueError, match="private"):
        pilot.validate_legacy_manifest(path)
    path.chmod(0o600)
    assert pilot.validate_legacy_manifest(path)["run_id"] == d["run_id"]
    link = tmp_path / "alias.json"
    link.symlink_to(path)
    with pytest.raises(OSError):
        pilot.validate_legacy_manifest(link)


def test_actual_native_gateway_refuses_foreign_digest_before_source_probe(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    d = _manifest(tmp_path)
    identity = {"source_sha": d["expected_sha"], "image_digest": d["expected_digest"]}
    d["native_context"] = {"start": {"api": identity}}
    monkeypatch.setattr(pilot, "_native_seam", lambda: object())
    monkeypatch.setattr(pilot, "_read_json_url", lambda *_: {"identity": identity | {"image_digest": "sha256:" + "d" * 64}})
    monkeypatch.setattr(pilot, "_local_fixture_read", lambda *_: pytest.fail("source read before actual identity admission"))
    with pytest.raises(pilot.Blocked, match="identity_drift"):
        pilot.native_probe(d)


def test_effect_budget_is_consumed_before_forwarding(tmp_path: Path) -> None:
    d = _manifest(tmp_path)
    flow = pilot.DailyBriefingFlow(d, _Browser(d), probe=lambda *_: _evidence(d))
    flow.admitted = True
    flow._consume("tts_synthesis")
    report = json.loads((Path(d["output_dir"]) / "report.json").read_text())
    assert report["effects_consumed"]["tts_synthesis"] == 1
    with pytest.raises(pilot.Blocked):
        flow._consume("tts_synthesis")
    assert report["execution_kind"] == "deterministic_fixture"


def _audio() -> tuple[dict[str, Any], dict[str, Any], dict[str, Any], bytes]:
    routes = {"sv-SE": {"provider": "piper", "voice_id": "sv-test", "available": True},
              "en-US": {"provider": "kokoro", "voice_id": "en-test", "available": True}}
    segments = [{"language": language, "provider_available": True} | {k: route[k] for k in ("provider", "voice_id")} for language, route in routes.items()]
    plan = {"enabled": True, "local_only": True, "allow_cloud_fallback": False, "allow_browser_fallback": False,
            "normalized_text": "Jag läser i dag. We will review today.",
            "mixed_language": True, "cached": False, "segments": segments, "cache_key": "a" * 64,
            "audio_url": "/api/companion/tts/audio/" + "a" * 64 + ".wav"}
    synth = {"ok": True, "state": "generated", "cached": False, "cache_key": plan["cache_key"], "audio_url": plan["audio_url"]}
    out = io.BytesIO()
    with wave.open(out, "wb") as audio:
        audio.setnchannels(1)
        audio.setsampwidth(2)
        audio.setframerate(24000)
        audio.writeframes(b"\x01\x00" * 2400)
    return plan, synth, routes, out.getvalue()


@pytest.mark.parametrize("fault", ["route", "fake", "cache", "lineage", "empty", "corrupt"])
def test_audio_fallback_and_fabricated_lineage_cannot_pass(fault: str) -> None:
    plan, synth, routes, raw = _audio()
    if fault == "route":
        plan["segments"][1]["voice_id"] = "other"
    elif fault == "fake":
        plan["segments"][0]["provider"] = "mock"
    elif fault == "cache":
        synth["state"], synth["cached"] = "cached", True
    elif fault == "lineage":
        synth["cache_key"] = "b" * 64
    else:
        raw = b"" if fault == "empty" else b"not WAV"
    with pytest.raises(AssertionError):
        pilot.validate_audio(plan, synth, routes, raw, source_text="Jag läser i dag. We will review today.")


def test_audio_validator_checks_decoding_and_source_selected_segments() -> None:
    evidence = pilot.validate_audio(*_audio(), source_text="Jag läser i dag. We will review today.")
    assert evidence["frames"] == 2400 and evidence["sample_rate"] == 24000
    assert [x["provider"] for x in evidence["segments"]] == ["piper", "kokoro"]


@pytest.mark.parametrize("malformed", [
    "---\ninvalid_synthetic_moment: true\n---\n",
    "---\ninvalid: [\n---\nSynthetic unavailable source.\n",
    "",
])
def test_malformed_actual_moment_must_name_partial_source(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, malformed: str,
) -> None:
    from app.briefing import compose as composer
    from app.briefing import compose_briefing, load_briefing
    from app.vault.manager import VaultContext
    from app.write_guard import WriteGuard
    from tests.briefing.test_compose_briefing import _seed_moment
    from tests.briefing.test_briefing_calendar_section import _calendar_registry

    monkeypatch.setenv("VAULT_SYSTEM_DIR_REL", "_system")
    monkeypatch.setattr(composer, "load_registry", _calendar_registry)
    monkeypatch.setattr(composer, "read_calendar_raw_items_for_tick", lambda: ([], []))
    context = VaultContext(status="selected", active_vault_path=str(tmp_path))
    path = _seed_moment(tmp_path, "actual-source")
    _seed_moment(tmp_path, "healthy-source")
    path.write_text(malformed)
    from app.relevance.now_surface import collect_now_moments
    assert [x["moment_id"] for x in collect_now_moments(context)] == ["healthy-source"]
    compose_briefing(vault_context=context, for_date=date(2026, 7, 10), write_guard=WriteGuard(lambda: {"state": "healthy"}))
    note = load_briefing(vault_context=context, for_date=date(2026, 7, 10))
    assert note is not None and note.degraded_sections == ("moments",)
    assert note.sections["commitments"].status == "available"
    assert note.sections["decision_receipts"].status == "available"
    assert note.sections["calendar_episodes"].status == "available"


def _native_fixture(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> dict[str, Any]:
    from tests.companion_ui.test_live_core_flow_contract import _probe_input
    from app.briefing.trigger import _local_now
    from app.vault.manager import VaultContext
    from app.write_guard import DEFAULT_WRITE_GUARD

    p = _probe_input(tmp_path, monkeypatch)
    monkeypatch.setenv("VAULT_SYSTEM_DIR_REL", "_system")
    monkeypatch.setattr(DEFAULT_WRITE_GUARD, "snapshot_fn", lambda: {"state": "healthy"})
    d = _manifest(tmp_path) | {"channel": "dev", "vault_path": str(tmp_path), "vault_id": p["vault_id"],
                               "date": _local_now(None).date().isoformat()}
    (tmp_path / "fixture").rmdir()
    marker = tmp_path / d["fixture_marker"]
    marker.write_text(json.dumps({"schema": "daily-briefing-synthetic-fixture.v1", "synthetic": True,
                                 "run_id": d["run_id"], "resource_version": d["resource_version"],
                                 "vault_id": d["vault_id"], "vault_path": d["vault_path"]}))
    context = VaultContext(status="selected", active_vault_id=d["vault_id"], active_vault_path=str(tmp_path))
    fields = pilot.prepare_sources(vault_context=context, for_date=date.fromisoformat(d["date"]), run_id=d["run_id"], marker_path=d["fixture_marker"])
    d.update({k: fields[k] for k in ("source_files", "moment_path", "moment_full_text", "fixture_marker_sha256")})
    d["calendar"] = d["calendar"] | {"base_url": "http://127.0.0.1:8080", "uid": fields["calendar_uid"], "etag": fields["calendar_etag"]}
    monkeypatch.setenv("CALDAV_CALENDARS_JSON", json.dumps([d["calendar"] | {"username": "synthetic", "app_password": "synthetic", "scope": "synthetic"}]))
    for key in ("CALDAV_URL", "CALDAV_USERNAME", "CALDAV_APP_PASSWORD", "CALDAV_CALENDAR_PATH", "CALDAV_SCOPE"):
        monkeypatch.delenv(key, raising=False)
    return d


def _run_native_read(d: dict[str, Any], monkeypatch: pytest.MonkeyPatch) -> dict[str, Any]:
    import sys
    from contextlib import redirect_stdout
    monkeypatch.setattr(sys, "stdin", io.StringIO(json.dumps(d | {"action": "read"})))
    output = io.StringIO()
    with redirect_stdout(output):
        exec(pilot._NATIVE_READ + pilot._NATIVE_ACTION, {})
    return json.loads(output.getvalue())


def test_real_passive_fixture_admission_needs_no_capture_ask_or_producer_effect(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    d = _native_fixture(tmp_path, monkeypatch)
    from app.briefing import trigger
    monkeypatch.setattr(trigger, "first_contact_briefing", lambda **_: pytest.fail("passive admission called generation"))
    before = {p: p.read_bytes() for p in tmp_path.rglob("*") if p.is_file()}
    result = _run_native_read(d, monkeypatch)
    assert result["fixture_verified"] and result["binding_verified"]
    assert result["briefing_exists"] is False
    assert {p: p.read_bytes() for p in tmp_path.rglob("*") if p.is_file()} == before


@pytest.mark.parametrize("fault", ["marker", "undeclared_note", "source_hash", "calendar"])
def test_native_fixture_refusal_precedes_tts_and_mutation(tmp_path: Path, monkeypatch: pytest.MonkeyPatch, fault: str) -> None:
    d = _native_fixture(tmp_path, monkeypatch)
    if fault == "marker":
        d["fixture_marker_sha256"] = "f" * 64
    elif fault == "undeclared_note":
        (tmp_path / "owner.md").write_text("Not admitted input")
    elif fault == "source_hash":
        d["source_files"][d["moment_path"]] = "f" * 64
    else:
        monkeypatch.setenv("CALDAV_CALENDARS_JSON", json.dumps([d["calendar"] | {"base_url": "https://calendar.example.com", "username": "owner", "app_password": "owner", "scope": "work"}]))
    from app.tts import status
    monkeypatch.setattr(status, "tts_runtime_status", lambda *_: pytest.fail("TTS inspection before synthetic source admission"))
    with pytest.raises(AssertionError):
        _run_native_read(d, monkeypatch)
