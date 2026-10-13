"""Actual adapter/guard boundaries with synthetic records, never feature PASS."""
from __future__ import annotations

from copy import deepcopy
import hashlib
import json
from pathlib import Path
import runpy
from types import SimpleNamespace
from typing import Any
from urllib.parse import parse_qs, urlparse

import pytest

from app.ops import native_web_acceptance as native
from app.ops import native_web_runtime as runtime
from app.ops.native_web_fixture import CANDIDATE_IDS
from app.ops.native_web_reports import pilot_manifest, report_binding
from tests.companion_ui.live_core_flow import Blocked
from tests.companion_ui.live_deep_review import DeepReview, EFFECT_BUDGET, SCENARIOS, acceptance_passed, execute_manifest, load_manifest
from tests.companion_ui.native_deep_review import NativeDeepBinding
from tests.companion_ui.test_live_core_flow_contract import _Browser


def _fixture(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> tuple[Path, dict[str, Any], dict[str, Any]]:
    """Use the delivered binding/manifest producers with explicit test records."""
    monkeypatch.setattr(native, "CONTEXT_PATH", tmp_path / "context.json")
    monkeypatch.setattr(runtime, "CONTEXT_PATH", native.CONTEXT_PATH)
    monkeypatch.setattr(native, "REPORT_DIRECTORY", tmp_path / "reports")
    import app.ops.native_web_reports as reports
    monkeypatch.setattr(reports, "CONTEXT_PATH", native.CONTEXT_PATH)
    monkeypatch.setattr(reports, "REPORT_DIRECTORY", native.REPORT_DIRECTORY)
    generation = "59690000-0000-4000-8000-000000000099"
    sources = [{"effect": effect, "note_path": path, "note_uuid": uid, "seed_sha256": "c" * 64}
               for effect, path, uid in (("panel_confirm", "review.md", "59690000-0000-4000-8000-000000000010"),
                                        ("capture", "capture.md", "59690000-0000-4000-8000-000000000011"))]
    fixture = {
        "logical_vault_id": "synthetic-vault", "local_clone_id": "synthetic-clone", "resource_generation": generation,
        "note_path": "note.md", "note_uuid": "59690000-0000-4000-8000-000000000012", "note_sha256": "c" * 64,
        "review_note_path": "review.md", "review_note_uuid": sources[0]["note_uuid"],
        "capture_note_path": "capture.md", "capture_note_uuid": sources[1]["note_uuid"],
        "controlled_mutable_sources": sources, "candidate_ids": list(CANDIDATE_IDS), "settings_hash": "d" * 64,
        "daily": {"briefing_path": "briefing.md", "date": "2026-10-12"},
    }
    files = {"tests/companion_ui/" + name: hashlib.sha256(Path(__file__).with_name(name).read_bytes()).hexdigest()
             for name in ("live_core_flow.py", "live_deep_review.py")}
    manifest = {"source_sha": "a" * 40, "image_digest": "sha256:" + "b" * 64, "channel": "test",
                "operation_id": generation, "resource_generation": generation, "resource_tree": "e" * 40,
                "app_image_id": "sha256:" + "f" * 64, "files": files}
    api = {key: manifest[key] for key in ("source_sha", "image_digest", "resource_generation", "resource_tree", "app_image_id")}
    api.update(api_pid=1234, api_module="/app/app/main.py", fixture=fixture)
    start = {"api": api, "ui_pid": 5678, "ui_program_sha256": "f" * 64, "configuration_hash": "e" * 64}
    binding = report_binding(manifest, start)
    context = {"schema": "native-web-context.v1", "report_binding": binding,
               "native_identity": {k: manifest[k] for k in ("source_sha", "image_digest", "channel", "operation_id", "resource_generation", "resource_tree", "app_image_id")},
               "start": start, "fixture": fixture, "api_url": native.API_URL, "ui_url": native.UI_URL, "caldav_url": native.CALDAV_URL,
               "reports": {"deep-review": str(native.REPORT_DIRECTORY / "deep-review/report.json")}}
    native.CONTEXT_PATH.write_text(json.dumps(context))
    native.CONTEXT_PATH.chmod(0o600)
    path = tmp_path / "deep-manifest.json"
    path.write_text(json.dumps(pilot_manifest("deep-review", binding)))
    path.chmod(0o600)
    observed = {"identity": deepcopy(api), "effects": {"deep-review": dict.fromkeys(EFFECT_BUDGET, 0)},
                "acknowledgements": {}, "mutable_versions": {s["note_path"]: s["seed_sha256"] for s in sources},
                "daily_briefing_state": {"target": "briefing.md", "date": "2026-10-12", "healthy_version": "a" * 64, "version": "a" * 64}}
    return path, context, observed


def _transport(monkeypatch: pytest.MonkeyPatch, observed: dict[str, Any], calls: list[str]) -> None:
    def get(url: str) -> dict[str, Any]:
        calls.append(url)
        parsed = urlparse(url)
        if parsed.path == "/healthz":
            return {"ok": True, "service": "companion-ui"}
        assert parsed.path == "/__native_web_identity"
        query = parse_qs(parsed.query)
        if query:
            assert query["pilot"] == ["deep-review"]
            observed["effects"]["deep-review"][query["effect"][0]] += 1
        return deepcopy(observed)
    monkeypatch.setattr(runtime, "_get_json", get)


def _runner(path: Path, monkeypatch: pytest.MonkeyPatch) -> DeepReview:
    d = load_manifest(path)
    browser = _Browser(d)
    get = browser.page.get
    browser.page.get = lambda url, **kw: SimpleNamespace(ok=True, status=200, url=url, json=lambda: {
        "status": "selected", "active_vault_id": d["vault_id"], "active_vault_path": d["vault_path"], "local_instance_id": d["local_instance_id"],
    }) if url.endswith("/api/companion/vault/context") else get(url, **kw)
    runner = DeepReview(d, browser)
    runner.identity_ok = True
    return runner


@pytest.mark.parametrize("fault", [None, "wrong_note", "identity", "hook_failure"])
def test_actual_guard_calls_fixed_hook_after_preserved_reservation_before_transport(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, fault: str | None,
) -> None:
    path, _, observed = _fixture(tmp_path, monkeypatch)
    calls: list[str] = []
    _transport(monkeypatch, observed, calls)
    runner = _runner(path, monkeypatch)
    runner.armed = "queue_review"
    if fault == "identity":
        observed["identity"]["api_pid"] += 1
    if fault == "hook_failure":
        def fail(pilot: str, effect: str) -> None:
            snapshot = json.loads((runner.output / "report.json").read_text())
            assert snapshot["effects"][effect] == 1
            raise RuntimeError("native transport unavailable after reservation")
        monkeypatch.setattr(runtime, "before_effect", fail)
    sent: list[str] = []
    route = SimpleNamespace(request=SimpleNamespace(method="POST", url=runner.d["ui_url"] + "api/companion/vault-browser/actions/queue-review",
                            post_data_json={"note_path": "note.md" if fault == "wrong_note" else "review.md"}),
                            abort=lambda *_: sent.append("refused"), continue_=lambda: sent.append("forwarded"))
    runner._guard_request(route)
    assert sent == ["forwarded" if fault is None else "refused"]
    assert runner.effects["queue_review"] == int(fault in {None, "hook_failure"})
    assert observed["effects"]["deep-review"]["queue_review"] == int(fault is None)
    assert any("effect=queue_review" in url for url in calls) is (fault is None)
    saved = json.loads((runner.output / "report.json").read_text())
    assert saved["passed"] is False and not acceptance_passed(saved)


@pytest.mark.parametrize("fault", [None, "identity", "effects", "ack", "version", "extra_source", "daily"])
def test_actual_end_boundary_rejects_drift_and_unacknowledged_versions(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, fault: str | None,
) -> None:
    path, context, observed = _fixture(tmp_path, monkeypatch)
    binding = NativeDeepBinding(json.loads(path.read_text()))
    ack = {"status": "executed", "receipt": {"receipt_id": "unit-only-receipt"}}
    capture = {"outcome": "written", "trace_id": "unit-only-trace"}
    observed["effects"]["deep-review"] = dict(EFFECT_BUDGET)
    for source, body in zip(context["fixture"]["controlled_mutable_sources"], (ack, capture), strict=True):
        observed["mutable_versions"][source["note_path"]] = "d" * 64
        observed["acknowledgements"][source["effect"]] = {
            "target": source["note_path"], "source_uuid": source["note_uuid"], "pre_sha256": source["seed_sha256"],
            "post_sha256": "d" * 64, "response_sha256": native.hash_json(body),
        }
    if fault == "identity":
        observed["identity"]["image_digest"] = "sha256:" + "0" * 64
    elif fault == "effects":
        observed["effects"]["deep-review"]["capture"] = 0
    elif fault == "ack":
        observed["acknowledgements"]["panel_confirm"]["response_sha256"] = "0" * 64
    elif fault == "version":
        observed["mutable_versions"]["review.md"] = "0" * 64
    elif fault == "extra_source":
        observed["mutable_versions"]["foreign.md"] = "0" * 64
    elif fault == "daily":
        observed["daily_briefing_state"]["version"] = "0" * 64
    calls: list[str] = []
    _transport(monkeypatch, observed, calls)
    if fault:
        with pytest.raises(Blocked):
            binding.end(dict(EFFECT_BUDGET), ack, capture)
    else:
        proof = binding.end(dict(EFFECT_BUDGET), ack, capture)
        assert proof["verified"] and proof["api"] == context["start"]["api"]
    assert not any("effect=" in url for url in calls)  # end proof is read-only.


def test_missing_input_actual_wrapper_retains_refusal_without_fake_identity(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("COMPANION_UI_LIVE_DEEP_REVIEW", "1")
    monkeypatch.delenv("COMPANION_UI_DEEP_REVIEW_MANIFEST", raising=False)
    monkeypatch.setattr(runtime, "_get_json", lambda *_: pytest.fail("native contact before input exists"))
    wrapper = runpy.run_path(str(Path(__file__).with_name("test_companion_ui_live_deep_review.py")))
    with pytest.raises(AssertionError, match="actual_required_TEST_proof_failed"):
        wrapper["test_deep_review_live_acceptance"]()
    reports = list((tmp_path / ".codex-tmp").glob("deep-review-refusal-*/report.json"))
    assert len(reports) == 1
    report = json.loads(reports[0].read_text())
    assert report["schema"] == "companion_ui_deep_review_execution.v1"
    assert [row["id"] for row in report["scenarios"]] == list(SCENARIOS)
    assert all(row["status"] == "blocked" for row in report["scenarios"])
    assert not any(report["effects"].values()) and report["artifacts"] == {}
    assert report["observed_native_identity"] is None and report["expected_image_digest"] is None
    assert report["identity_gaps"] and not report["identity_verified"] and not acceptance_passed(report)


def test_native_context_missing_preserves_declared_expectations_and_prior_output(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    path, _, _ = _fixture(tmp_path, monkeypatch)
    native.CONTEXT_PATH.unlink()
    report = execute_manifest(path)
    assert report["expected_sha"] == "a" * 40 and report["expected_image_digest"] == "sha256:" + "b" * 64
    assert report["observed_native_identity"] is None and not acceptance_passed(report)
    output = native.REPORT_DIRECTORY / "deep-review/report.json"
    before = output.read_bytes()
    with pytest.raises(FileNotFoundError):
        execute_manifest(path)
    assert output.read_bytes() == before


@pytest.mark.parametrize("fault", ["origin", "binding", "generation", "budget_identity", "output"])
def test_native_preflight_rejects_unbound_input_before_contact(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, fault: str,
) -> None:
    path, context, _ = _fixture(tmp_path, monkeypatch)
    envelope = json.loads(path.read_text())
    if fault == "origin":
        context["api_url"] = "http://127.0.0.1:18002"
    elif fault == "binding":
        context["fixture"]["logical_vault_id"] = "foreign-same-name-vault"
    elif fault == "generation":
        envelope["report_binding"]["run_id"] = "not-a-native-generation"
    elif fault == "budget_identity":
        context["start"]["api"]["api_pid"] = 0
    else:
        envelope["output_dir"] = str(tmp_path / "foreign-output")
    path.write_text(json.dumps(envelope))
    native.CONTEXT_PATH.write_text(json.dumps(context))
    monkeypatch.setattr(runtime, "_get_json", lambda *_: pytest.fail("contact before exact input admission"))
    with pytest.raises((ValueError, KeyError)):
        load_manifest(path)
