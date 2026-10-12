"""Deterministic regressions at the live runner's admission and effect callsites.

These tests verify the harness. Their fabricated browser/native records never
claim deployed Product acceptance; only the explicit actual TEST runner can.
"""
from __future__ import annotations

from contextlib import nullcontext
from copy import deepcopy
import json
from pathlib import Path
import re
import runpy
import stat
import subprocess
from types import SimpleNamespace
from typing import Any
import xml.etree.ElementTree as ET

import pytest

from tests.companion_ui.live_core_flow import Blocked
from tests.companion_ui.live_deep_review import DeepReview, EFFECT_BUDGET, SCENARIOS, acceptance_passed, execute_manifest, load_manifest
from tests.companion_ui.test_live_core_flow_contract import _Browser, _manifest as _core_manifest


def _manifest(tmp_path: Path) -> dict[str, Any]:
    d = _core_manifest(tmp_path)
    for key in ("embedding_identity", "allow_capture", "allow_ask", "index_seconds"):
        d.pop(key)
    d.update(
        schema="companion_ui_deep_review_manifest.v1", channel="test",
        ui_url="http://127.0.0.1:8112/", api_url="http://127.0.0.1:18002/",
        expected_image_digest="sha256:" + "b" * 64,
        test_resource_version="fixture-version-1", fixture_metadata_path="/private/fixture.json",
        fixture_metadata_sha256="c" * 64, expected_machine_id_sha256="d" * 64,
        effect_budget=dict(EFFECT_BUDGET), qualification_ref="native-operation:fixture-qualified",
        native_channel_lock_path="/private/test.env.lock/owner", native_channel_lock_pid=123,
        memory_candidates={action: "synthetic-" + action for action in ("accept", "reject", "revise", "defer")},
        local_instance_id="synthetic-local-clone",
    )
    return d


def _native(d: dict[str, Any]) -> dict[str, Any]:
    return {
        "binding_verified": True, "gateway_upstream_verified": True,
        "first_contact_navigation_safe": True, "synthetic_fixture_verified": True,
        "native_lock_verified": True, "source_has_marker": False,
        "test_resource_version": d["test_resource_version"], "image_digest": d["expected_image_digest"],
        "configuration_hashes": {"approved-settings": "f" * 64},
    }


def _runner(tmp_path: Path, *, wrong_sha: bool = False) -> DeepReview:
    d = _manifest(tmp_path)
    browser = _Browser(d, wrong_sha=wrong_sha)
    get = browser.page.get

    def response(url: str, **kwargs: Any) -> Any:
        if url.endswith("/api/operator/health"):
            return SimpleNamespace(ok=True, status=200, url=url, json=lambda: {"environment": "test", "ok": True})
        if url.endswith("/api/companion/vault/context"):
            return SimpleNamespace(ok=True, status=200, url=url, json=lambda: {"status": "selected", "active_vault_id": d["vault_id"], "active_vault_path": d["vault_path"], "local_instance_id": d["local_instance_id"]})
        return get(url, **kwargs)

    browser.page.get = response
    return DeepReview(d, browser, probe=lambda *_: _native(d))


class _StrictDOMLocator:
    """Offline DOM adapter with Playwright's single-target consumer semantics."""

    def __init__(self, roots: list[ET.Element]) -> None:
        self.roots = roots

    def locator(self, selector: str) -> _StrictDOMLocator:
        attributes = re.findall(r'\[([^=\]]+)="([^"]*)"\]', selector)
        assert attributes, selector
        return _StrictDOMLocator([
            node for root in self.roots for node in list(root.iter())[1:]
            if all(node.get(key) == value for key, value in attributes)
        ])

    def get_by_test_id(self, test_id: str) -> _StrictDOMLocator:
        return self.locator('[data-testid="' + test_id + '"]')

    def _single(self) -> ET.Element:
        assert len(self.roots) == 1, "strict_locator_count:" + str(len(self.roots))
        return self.roots[0]

    def wait_for(self, *, state: str) -> None:
        assert state == "visible"
        self._single()

    def inner_text(self) -> str:
        return "".join(self._single().itertext())

    def get_attribute(self, name: str) -> str | None:
        return self._single().get(name)


def _actual_apply_dom(ack: dict[str, Any], projected: dict[str, Any]) -> _StrictDOMLocator:
    """Run the shipped Apply consumer with a synthetic transport, never an action."""
    from companion_ui.workspace.serve_dev_page import _panel_apply_script, _render_panel_confirm_response

    html = _render_panel_confirm_response(projected)
    attrs = ET.fromstring(html).attrib
    inputs = json.dumps({"ack": ack, "html": html, "attrs": attrs})
    script = _panel_apply_script().removeprefix("\n  <script>").removesuffix("\n  </script>")
    setup = "const input=" + inputs + ";" + r"""
const calls=[];
const rows=['rail','palette'].map(surface => ({surface, html:null,
  getAttribute: name => name === 'data-proposal-id' ? 'synthetic-proposal' : null,
  replaceWith: node => { rows.find(row => row.surface === surface).html=node.html; }}));
const rail={scrollTop:7};
const editor={getAttribute: () => 'note.md'};
const response={html:input.html,getAttribute: name => input.attrs[name]};
global.window={crypto:{randomUUID: () => 'synthetic-operation'}};
global.document={getElementById: () => editor,querySelector: () => rail,
  querySelectorAll: () => rows,importNode: node => ({html:node.html}),addEventListener: () => {}};
global.DOMParser=class {parseFromString() {
  return {querySelector: () => response,querySelectorAll: () => []}; }};
global.fetch=async (path, options) => {
  calls.push({path,options});
  return {ok:true,json:async () => input.ack,text:async () => input.html}; };
const attributes={'data-proposal-id':'synthetic-proposal','data-artifact-id':'synthetic-artifact',
  'data-panel-action':'confirm','data-api-path':'/api/panel/confirm'};
const button={getAttribute: name => attributes[name],
  setAttribute: (name,value) => {attributes[name]=value;},removeAttribute: name => {delete attributes[name];},
  closest: () => null};
"""
    ending = "\nwindow.panelActions.submit(button).then(() => console.log(JSON.stringify({rows,calls,scroll:rail.scrollTop})));"
    result = subprocess.run(["node", "-e", setup + script + ending], check=True, capture_output=True, text=True, timeout=10)
    observed = json.loads(result.stdout)
    assert [call["options"]["method"] for call in observed["calls"]] == ["POST", "GET"]
    assert observed["scroll"] == 7
    assert all(row["html"] == html for row in observed["rows"])
    tree = ET.fromstring('<page><rail data-testid="workspace-agent-rail">' + observed["rows"][0]["html"] + '</rail><palette hidden="true">' + observed["rows"][1]["html"] + '</palette></page>')
    return _StrictDOMLocator([tree])


@pytest.mark.parametrize("fault", [None, "logged", "wrong_receipt"])
def test_actual_apply_consumer_binds_unique_rail_and_acknowledged_receipt(
    tmp_path: Path, fault: str | None,
) -> None:
    """Synthetic renderer/consumer proof, not actual executed-action acceptance."""
    ack = {
        "proposal_id": "synthetic-proposal", "artifact_id": "synthetic-artifact",
        "status": "logged" if fault == "logged" else "executed", "outcome": "logged" if fault == "logged" else "success",
        "receipt": {"receipt_id": "synthetic-receipt", "outcome": "logged" if fault == "logged" else "success", "timestamp": "2026-10-12T00:00:00Z"},
    }
    projected = deepcopy(ack)
    if fault == "wrong_receipt":
        projected["receipt"]["receipt_id"] = "another-receipt"
    dom = _actual_apply_dom(ack, projected)
    # The actual shipped consumer has two clones, even with the palette hidden.
    assert len(dom.get_by_test_id("workspace-panel-confirm-response").roots) == 2
    runner = _runner(tmp_path)
    runner.page = dom
    runner.proposal_id = ack["proposal_id"]
    if fault:
        with pytest.raises(AssertionError, match="strict_locator_count:0" if fault == "logged" else "receipt_link_identity_mismatch"):
            runner._acknowledged_rail_receipt(ack["receipt"]["receipt_id"])
    else:
        assert len(dom.get_by_test_id("workspace-panel-receipt-card").roots) == 2
        applied = runner._acknowledged_rail_receipt(ack["receipt"]["receipt_id"])
        assert len(applied.roots) == 1
        runner.proposal_id = "another-proposal"
        with pytest.raises(AssertionError, match="strict_locator_count:0"):
            runner._acknowledged_rail_receipt(ack["receipt"]["receipt_id"])
    assert not runner.confirmation and not any(runner.effects.values())
    assert not acceptance_passed(json.loads((runner.output / "report.json").read_text()))


def _private_manifest(tmp_path: Path) -> tuple[Path, dict[str, Any]]:
    d = _manifest(tmp_path)
    path = tmp_path / "manifest.json"
    path.write_text(json.dumps(d))
    path.chmod(0o600)
    return path, d


def _playwright_fixture(monkeypatch: pytest.MonkeyPatch, browser: Any) -> None:
    monkeypatch.setattr("playwright.sync_api.sync_playwright", lambda: nullcontext(SimpleNamespace(chromium=SimpleNamespace(launch=lambda: browser))))


@pytest.mark.parametrize("fault", ["launch", "context", "tracing"])
def test_actual_constructor_startup_failure_retains_inventory_and_fails_wrapper(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, fault: str,
) -> None:
    path, d = _private_manifest(tmp_path)
    browser = _Browser(d)
    browser.close = lambda: None
    _playwright_fixture(monkeypatch, browser)

    def fail(*args: Any, **kwargs: Any) -> None:
        raise RuntimeError("bounded constructor fault")

    if fault == "launch":
        monkeypatch.setattr("playwright.sync_api.sync_playwright", lambda: nullcontext(SimpleNamespace(chromium=SimpleNamespace(launch=fail))))
    elif fault == "context":
        browser.new_context = fail
    else:
        context = browser.new_context()
        context.tracing.start = fail
        browser.new_context = lambda: context
    monkeypatch.setenv("COMPANION_UI_LIVE_DEEP_REVIEW", "1")
    monkeypatch.setenv("COMPANION_UI_DEEP_REVIEW_MANIFEST", str(path))
    wrapper = runpy.run_path(str(Path(__file__).with_name("test_companion_ui_live_deep_review.py")))
    with pytest.raises(AssertionError, match="actual_required_TEST_proof_failed"):
        wrapper["test_deep_review_live_acceptance"]()
    output = Path(d["output_dir"])
    report = json.loads((output / "report.json").read_text())
    assert [row["id"] for row in report["scenarios"]] == list(SCENARIOS)
    assert all(row["status"] == "blocked" and row["reason"] == "runner_startup_failed:RuntimeError" for row in report["scenarios"])
    assert report["passed"] is False and not acceptance_passed(report)
    assert report["identity_verified"] is False and not any(report["effects"].values())
    assert report["expected_sha"] == d["expected_sha"] and report["expected_image_digest"] == d["expected_image_digest"]
    assert report["test_resource_version"] == d["test_resource_version"]
    assert set(report["harness_hashes"]) == {"live_core_flow.py", "live_deep_review.py"}
    assert report["manifest_sha256"] and report["artifacts"] == {} and report["actual_proof"] == {}
    assert all(value is None for value in report["backend_acknowledgements"].values())
    assert browser.page.navigations == []
    assert stat.S_IMODE(output.stat().st_mode) == 0o700
    assert stat.S_IMODE((output / "report.json").stat().st_mode) == 0o600


@pytest.mark.parametrize("prior", ["empty", "report.json", "report.json.next", "effect-reservation.json"])
def test_startup_fallback_never_overwrites_existing_run(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, prior: str,
) -> None:
    path, d = _private_manifest(tmp_path)
    output = Path(d["output_dir"])
    output.mkdir(mode=0o700)
    if prior != "empty":
        (output / prior).write_bytes(b"original private evidence with reserved effects")
    before = {p.name: p.read_bytes() for p in output.iterdir()}
    browser = _Browser(d)
    browser.close = lambda: None
    _playwright_fixture(monkeypatch, browser)
    with pytest.raises(FileExistsError):
        execute_manifest(path)
    assert {p.name: p.read_bytes() for p in output.iterdir()} == before
    assert browser.page.navigations == []


@pytest.mark.parametrize("content", ["report.json", "report.json.next", "effect-reservation.json", "replaced", "removed"])
def test_constructor_fallback_preserves_partial_evidence_and_directory_identity(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, content: str,
) -> None:
    path, d = _private_manifest(tmp_path)
    output = Path(d["output_dir"])
    browser = _Browser(d)
    browser.close = lambda: None

    def fail() -> None:
        # This runs after the actual CoreFlow's exclusive directory creation.
        if content in {"replaced", "removed"}:
            output.rename(output.with_name("retained-original-directory"))
            if content == "replaced":
                output.mkdir(mode=0o700)
        else:
            (output / content).write_bytes(b"partial effect evidence must survive")
        raise RuntimeError("constructor fault after partial evidence")

    browser.new_context = fail
    _playwright_fixture(monkeypatch, browser)
    with pytest.raises(RuntimeError, match="constructor fault after partial evidence"):
        execute_manifest(path)
    if content in {"replaced", "removed"}:
        assert output.exists() is (content == "replaced")
        assert not list(output.with_name("retained-original-directory").iterdir())
        if output.exists():
            assert not list(output.iterdir())
    else:
        assert {p.name: p.read_bytes() for p in output.iterdir()} == {content: b"partial effect evidence must survive"}
    assert browser.page.navigations == []


@pytest.mark.parametrize("fault", ["revision", "fixture", "digest", "lock", "first_contact", "resource"])
def test_preflight_rejects_wrong_identity_before_effect(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, fault: str,
) -> None:
    runner = _runner(tmp_path, wrong_sha=fault == "revision")
    proof = _native(runner.d)
    key, value = {
        "fixture": ("synthetic_fixture_verified", False),
        "digest": ("image_digest", "sha256:" + "e" * 64),
        "lock": ("native_lock_verified", False),
        "first_contact": ("first_contact_navigation_safe", False),
        "resource": ("test_resource_version", "another-resource"),
        "revision": ("binding_verified", True),
    }[fault]
    proof[key] = value
    runner.probe = lambda *_: proof
    if fault != "revision":
        monkeypatch.setattr(runner.page, "get", lambda *a, **k: pytest.fail("HTTP before passive fixture admission"))
    with pytest.raises((Blocked, AssertionError)):
        runner.native_admission()
    assert runner.page.navigations == []
    assert all(count == 0 for count in runner.effects.values())
    assert not runner.identity_ok
    persisted = json.loads((runner.output / "report.json").read_text())
    assert persisted["passed"] is False and persisted["effects"] == runner.effects


def _request(runner: DeepReview, payload: dict[str, Any], *, url: str | None = None) -> Any:
    sent: list[str] = []
    route = SimpleNamespace(
        request=SimpleNamespace(method="POST", url=url or runner.d["ui_url"] + "api/panel/confirm", post_data_json=payload),
        continue_=lambda: sent.append("continued"), abort=lambda *args: sent.append("refused"),
    )
    return route, sent


@pytest.mark.parametrize("fault", [None, "wrong_note", "wrong_proposal", "other_origin", "correction", "no_admission"])
def test_real_request_guard_binds_exact_apply_and_reserves_before_transport(
    tmp_path: Path, fault: str | None,
) -> None:
    runner = _runner(tmp_path)
    runner.native_admission()
    runner.proposal_id = "synthetic-proposal"
    runner.armed = "panel_confirm"
    payload = {"proposal_id": runner.proposal_id, "artifact_id": runner.d["known_note_uuid"], "action": "confirm", "idempotency_key": "one-effect"}
    if fault == "wrong_note":
        payload["artifact_id"] = "another-note"
    if fault == "wrong_proposal":
        payload["proposal_id"] = "operator-proposal"
    if fault == "correction":
        payload["correction"] = {"enabled": True}
    if fault == "no_admission":
        runner.identity_ok = False
    route, sent = _request(runner, payload, url="http://127.0.0.1:8111/api/panel/confirm" if fault == "other_origin" else None)
    runner._guard_request(route)
    report = json.loads((runner.output / "report.json").read_text())
    assert sent == ["continued" if fault is None else "refused"]
    assert report["effects"]["panel_confirm"] == int(fault is None)
    assert report["passed"] is False  # reservation cannot be an outcome.
    if fault is None:
        runner.armed = "panel_confirm"
        again, sent_again = _request(runner, payload)
        runner._guard_request(again)
        assert sent_again == ["refused"] and runner.effects["panel_confirm"] == 1


def _validator_report() -> dict[str, Any]:
    """A structural validator input, explicitly synthetic test data."""
    native = _native(_manifest(Path("/private/tmp/contract-only")))
    proof: dict[str, dict[str, Any]] = {
        "native_admission": {"native": native, "served_sha": "a" * 40},
        "a1_overlay_selection_continuity": {"cycles": 2, "selection": {"start": 3, "end": 8}},
        "a1_runtime_resume_position": {"runtime_leave_point": {"status": "present", "artifact_ref": {"artifact_uuid": "synthetic", "logical_ref": "note.md"}}, "prior_view": {"artifact_id": "synthetic", "note_path": "note.md", "start": 3, "end": 8, "editor_scroll": 0, "reading_scroll": 10}, "restored": {"start": 3, "end": 8, "editor_scroll": 0, "reading_scroll": 10}},
        "b4_all_overlay_focus_escape_return": {"overlays": {name: {"focus_trap": True, "escape": True, "focus_return": True} for name in ("cmd", "capture", "receipts", "settings", "memory", "map")}},
        "populated_vault_list_and_inspector": {"note_uuid": "synthetic", "list_count": 1, "inspector": True},
        "populated_governed_apply_exact_receipt": {"confirmation": {"status": "executed", "outcome": "success", "receipt": {"receipt_id": "synthetic"}}, "exact_persisted_readback": True, "receipt_history": True},
        "populated_capture_confirmation_and_caret": {"capture": {"outcome": "written", "trace_id": "synthetic"}, "source_readback": True, "selection_restored": True},
        "public_copy_populated_and_entry": {"surfaces": ["shell", "entry", "cmd", "memory", "receipts", "settings", "map"], "public_copy_clean": True},
        "public_copy_degraded": {"kind": "browser_fault_injection", "calm_unavailable": True},
    }
    for action, status in (("accept", "accepted"), ("reject", "rejected"), ("revise", "revised"), ("defer", "deferred")):
        proof["populated_memory_" + action] = {"decision": {"status": status}, "actual_pending_ids": [], "server_authority": {"authority": "non_authoritative"}}
    api_identity = {"source_sha": "a" * 40, "image_digest": "sha256:" + "b" * 64, "resource_tree": "fixture-version-1",
                    "resource_generation": "unit-only-generation", "fixture": {"local_clone_id": "unit-only-clone"},
                    "api_pid": 1234, "api_module": "/app/app/main.py"}
    return {
        "execution_kind": "live", "channel": "test", "identity_verified": True, "refused_requests": [],
        "expected_sha": "a" * 40, "expected_image_digest": "sha256:" + "b" * 64, "test_resource_version": "fixture-version-1",
        "run_id": "unit-only-generation", "local_instance_id": "unit-only-clone",
        "required_scenarios": list(SCENARIOS), "effects": dict(EFFECT_BUDGET), "artifacts": {"trace": "trace.zip", "junit": "junit.xml"},
        "scenarios": [{"id": name, "status": "passed", "kind": "browser_fault_injection" if name == "public_copy_degraded" else "live", "proof": {"source": "served_product", **proof[name]}} for name in SCENARIOS],
        "end_identity_verified": True, "end_identity_error": None,
        "actual_proof": {"native": {"api_identity": deepcopy(api_identity)},
                         "end": {"verified": True, "api": api_identity, "effects": dict(EFFECT_BUDGET)}},
    }


@pytest.mark.parametrize("fault", ["missing", "duplicate", "skipped", "xfail", "blocked", "failed", "empty_proof", "fixture_proof", "partial_receipt", "no_trace", "contract_test", "dev", "over_budget", "no_end", "changed_end", "end_effects"])
def test_required_scenarios_and_actual_proof_gate_acceptance(fault: str) -> None:
    report = _validator_report()
    assert acceptance_passed(report)
    if fault == "missing":
        report["scenarios"].pop()
    elif fault == "duplicate":
        report["scenarios"][-1] = deepcopy(report["scenarios"][0])
    elif fault in {"skipped", "xfail", "blocked", "failed"}:
        report["scenarios"][3]["status"] = fault
    elif fault == "empty_proof":
        report["scenarios"][3]["proof"] = {}
    elif fault == "fixture_proof":
        report["scenarios"][3]["proof"] = {"source": "mocked_success"}
    elif fault == "partial_receipt":
        report["scenarios"][5]["proof"]["exact_persisted_readback"] = False
    elif fault == "no_trace":
        report["artifacts"].pop("trace")
    elif fault == "contract_test":
        report["execution_kind"] = fault
    elif fault == "dev":
        report["channel"] = fault
    elif fault == "no_end":
        report["end_identity_verified"] = False
    elif fault == "changed_end":
        report["actual_proof"]["end"]["api"]["source_sha"] = "e" * 40
    elif fault == "end_effects":
        report["actual_proof"]["end"]["effects"]["capture"] = 0
    else:
        report["effects"]["capture"] = 2
    assert not acceptance_passed(report)


def test_runner_retains_all_outcomes_and_partial_backend_acknowledgement(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    runner = _runner(tmp_path)
    runner.native_admission()
    for name in SCENARIOS:
        def scenario(current: str = name) -> None:
            runner._need_identity()
            if current == "populated_governed_apply_exact_receipt":
                runner.confirmation = {"status": "executed", "receipt": {"receipt_id": "actual-callsite-unit-record"}}
                runner.effects["panel_confirm"] = 1
                runner._write_report()
                raise AssertionError("later_ui_failed")
            runner._proof(observed=current)
        monkeypatch.setattr(runner, name, scenario)
    report = runner.run()
    assert [row["id"] for row in report["scenarios"]] == list(SCENARIOS)
    assert report["scenarios"][5]["status"] == "failed"
    assert report["backend_acknowledgements"]["panel_confirm"] == runner.confirmation
    assert report["effects"]["panel_confirm"] == 1
    assert not acceptance_passed(report)
    assert (runner.output / "trace.zip").is_file() and (runner.output / "junit.xml").is_file()
    assert "failure" in (runner.output / "junit.xml").read_text()


@pytest.mark.parametrize("fault", [None, "prod", "digest", "budget", "shared_candidates", "missing_fixture"])
def test_private_manifest_refuses_unsafe_or_incomplete_effect_contract(tmp_path: Path, fault: str | None) -> None:
    d = _manifest(tmp_path)
    if fault == "prod":
        d["channel"] = "prod"
    elif fault == "digest":
        d["expected_image_digest"] = "latest"
    elif fault == "budget":
        d["effect_budget"]["capture"] = 2
    elif fault == "shared_candidates":
        d["memory_candidates"]["defer"] = d["memory_candidates"]["accept"]
    elif fault == "missing_fixture":
        d.pop("fixture_metadata_sha256")
    path = tmp_path / "manifest.json"
    path.write_text(json.dumps(d))
    path.chmod(0o600)
    if fault is None:
        assert load_manifest(path)["effect_budget"] == EFFECT_BUDGET
    else:
        with pytest.raises(ValueError):
            load_manifest(path)


def test_native_digest_refusal_reaches_actual_docker_admission_boundary(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    import tests.companion_ui.live_deep_review as live
    import tests.companion_ui.live_core_flow as core
    from tests.companion_ui.test_live_core_flow_contract import _native_rows

    runner = _runner(tmp_path)
    d = runner.d
    api, ui = _native_rows(d)
    for row in (api, ui):
        row["Config"]["Labels"]["com.docker.compose.project"] = "pkm-test"
        row["Image"] = "sha256:" + "e" * 64
    api["NetworkSettings"]["Ports"] = {"8000/tcp": [{"HostIp": "127.0.0.1", "HostPort": "18002"}]}
    ui["Config"]["Env"] = ["COMPANION_API_BASE_URL=http://api:8000", "PORT=8112"]
    ui["NetworkSettings"]["Ports"] = {"8112/tcp": [{"HostIp": "127.0.0.1", "HostPort": "8112"}]}
    calls: list[list[str]] = []

    def command(argv: list[str], **kwargs: Any) -> str:
        calls.append(argv)
        if argv[:3] == ["docker", "ps", "-q"]:
            return "a" * 12 if argv[-1].endswith("=api") else "b" * 12
        if argv[:2] == ["docker", "inspect"]:
            return json.dumps([api if argv[-1] == "a" * 12 else ui])
        if argv[:3] == ["docker", "image", "inspect"]:
            return json.dumps([{"RepoDigests": ["repo@sha256:" + "f" * 64]}])
        if argv[:2] == ["docker", "exec"] and argv[2] == "b" * 12:
            return json.dumps(["172.18.0.5"])
        pytest.fail("fixture Docker exec after wrong image admission")

    monkeypatch.setattr(core, "native_command", command)
    monkeypatch.setattr(live, "native_command", command)
    monkeypatch.setattr(live, "verify_channel_lock", lambda *_: None)
    read_bytes = Path.read_bytes
    monkeypatch.setattr(Path, "read_bytes", lambda p: b"synthetic-host" if str(p) == "/etc/machine-id" else read_bytes(p))
    import hashlib
    d["expected_machine_id_sha256"] = hashlib.sha256(b"synthetic-host").hexdigest()
    runner.probe = live.native_probe
    monkeypatch.setattr(runner.page, "get", lambda *a, **k: pytest.fail("HTTP after wrong native digest"))
    with pytest.raises(Blocked, match="running_image_digest_mismatch"):
        runner.native_admission()
    assert ["docker", "image", "inspect", api["Image"]] in calls
    assert not runner.page.navigations and not any(runner.effects.values())
