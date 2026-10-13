"""Serial, opted-in #2443 acceptance through the qualified native TEST routes.

The runner never provisions a fixture, deploys, resets a store or invents a
Product receipt. Admission precedes document GETs, which can have server-side
first-contact effects. All mutations use the served UI's ordinary interfaces.
"""
from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
import re
import stat
import time
from typing import Any, Callable
from urllib.parse import quote, urljoin, urlparse
from uuid import uuid4
import xml.etree.ElementTree as ET

from tests.companion_ui.live_core_flow import (
    Blocked,
    CoreFlow,
    _BINDING_PROBE,
    _NAVIGATION_PROBE,
    _origin,
    native_command,
    native_gateway,
    read_private_json,
    validate_capture_ack,
    validate_manifest,
)
from tests.companion_ui import live_core_flow
from tests.companion_ui.native_deep_review import NativeDeepBinding

SCENARIOS = (
    "native_admission",
    "a1_overlay_selection_continuity",
    "a1_runtime_resume_position",
    "b4_all_overlay_focus_escape_return",
    "populated_vault_list_and_inspector",
    "populated_governed_apply_exact_receipt",
    "populated_memory_accept",
    "populated_memory_reject",
    "populated_memory_revise",
    "populated_memory_defer",
    "populated_capture_confirmation_and_caret",
    "public_copy_populated_and_entry",
    "public_copy_degraded",
)
EFFECT_BUDGET = {
    "queue_review": 1,
    "panel_confirm": 1,
    "memory_accept": 1,
    "memory_reject": 1,
    "memory_revise": 1,
    "memory_defer": 1,
    "capture": 1,
}
FORBIDDEN_COPY = re.compile(
    r"errno|name or service not known|connection refused|failed to fetch|"
    r"HTTP [45]\d\d|resurfacing_source_unavailable|entry_state_[a-z_]+|"
    r"guard state|\b(?:prop|art|rcpt)-[a-z0-9-]+\b|\blifecycle\.[a-z_]+\b|"
    r"\b[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}\b|"
    r"\b(?:issue|PR)\s*#\d+",
    re.IGNORECASE,
)


def load_manifest(path: Path) -> dict[str, Any]:
    d = read_private_json(path)
    if d.get("schema") == "native-web-pilot-manifest.v1":
        return NativeDeepBinding(d).data()
    core_keys = {
        "channel", "ui_url", "api_url", "expected_sha", "run_id", "output_dir",
        "vault_id", "vault_path", "known_note_path", "known_note_uuid", "known_excerpt",
        "capture_note_path", "capture_note_uuid", "vault_binding_id", "navigation_ms", "request_ms",
    }
    required = core_keys - {"navigation_ms", "request_ms"}
    extra = {
        "schema", "expected_image_digest", "test_resource_version", "fixture_metadata_path",
        "fixture_metadata_sha256", "expected_machine_id_sha256", "effect_budget", "memory_candidates",
        "native_channel_lock_path", "native_channel_lock_pid", "qualification_ref",
        "local_instance_id",
    }
    if not required | extra <= d.keys() or d.keys() - core_keys - extra:
        raise ValueError("deep_review_manifest_fields_invalid")
    if d["schema"] != "companion_ui_deep_review_manifest.v1":
        raise ValueError("deep_review_manifest_schema_invalid")
    baseline = validate_manifest({k: v for k, v in d.items() if k in core_keys})
    d.update(baseline)
    if not re.fullmatch(r"sha256:[0-9a-f]{64}", str(d["expected_image_digest"])):
        raise ValueError("image_digest_invalid")
    for key in ("fixture_metadata_sha256", "expected_machine_id_sha256"):
        if not re.fullmatch(r"[0-9a-f]{64}", str(d[key])):
            raise ValueError("fixture_or_host_digest_invalid")
    for key in ("test_resource_version", "qualification_ref"):
        if not isinstance(d[key], str) or not d[key].strip() or len(d[key]) > 256:
            raise ValueError("qualification_identity_missing")
    if not re.fullmatch(r"[A-Za-z0-9_-]{1,128}", str(d["local_instance_id"])):
        raise ValueError("synthetic_local_clone_identity_invalid")
    for key in ("fixture_metadata_path", "native_channel_lock_path"):
        if not isinstance(d[key], str) or not Path(d[key]).is_absolute():
            raise ValueError("native_fixture_path_invalid")
    if type(d["native_channel_lock_pid"]) is not int or d["native_channel_lock_pid"] <= 0:
        raise ValueError("native_lock_owner_invalid")
    if d["effect_budget"] != EFFECT_BUDGET or any(type(n) is not int for n in d["effect_budget"].values()):
        raise ValueError("effect_budget_invalid")
    candidates = d["memory_candidates"]
    if (
        not isinstance(candidates, dict) or set(candidates) != {"accept", "reject", "revise", "defer"}
        or any(not re.fullmatch(r"[A-Za-z0-9_-]{1,100}", str(x)) for x in candidates.values())
        or len(set(candidates.values())) != 4
    ):
        raise ValueError("memory_fixture_invalid")
    d["allow_capture"] = True
    return d


# This runs passively inside the selected API. No application manager, queue
# constructor or persistence writer is called merely to admit the browser.
_DEEP_PROBE = _BINDING_PROBE + _NAVIGATION_PROBE + r'''
import sqlite3
marker=pathlib.Path(p['fixture_metadata_path'])
assert marker.is_file() and not marker.is_symlink() and stat.S_IMODE(marker.stat().st_mode)==0o600 and marker.stat().st_uid==os.geteuid() and marker.stat().st_nlink==1,'fixture_restore_synthetic_marker_missing'
marker_raw=marker.read_bytes();assert len(marker_raw)<=32768
assert hashlib.sha256(marker_raw).hexdigest()==p['fixture_metadata_sha256'],'fixture_restore_synthetic_marker_changed'
f=json.loads(marker_raw)
assert f['schema']=='companion_ui_deep_review_fixture.v1' and f['synthetic'] is True,'fixture_restore_synthetic_marker_invalid'
for key in ('vault_id','vault_path','local_instance_id','test_resource_version','memory_candidates'):
 assert f[key]==p[key],'fixture_restore_resource_mismatch'
assert local_doc.get('localInstanceId')==p['local_instance_id'],'fixture_restore_local_clone_mismatch'
assert f['effect_budget']==p['effect_budget'],'fixture_restore_effect_budget_mismatch'
assert os.environ.get('STORE_SCHEMA_AUTOCREATE','').lower() not in {'1','true','yes'},'fixture_restore_store_autocreate'
# Bind all writable operational producers to the isolated test resource. These
# files/directories must already exist; this probe does not bootstrap them.
runtime=pathlib.Path(f['runtime_root']).resolve(strict=True)
assert runtime!=root and not runtime.is_relative_to(root),'fixture_restore_runtime_root_invalid'
for key,expected in f['runtime_paths'].items():
 actual=os.environ.get(key)
 assert actual and pathlib.Path(actual).resolve(strict=True)==pathlib.Path(expected).resolve(strict=True),'fixture_restore_runtime_path_mismatch'
 assert pathlib.Path(actual).resolve(strict=True).is_relative_to(runtime),'fixture_restore_runtime_path_not_synthetic'
assert set(f['runtime_paths'])=={'LEAVE_POINT_TRACE_DB','PANEL_STAGING_DB_PATH','AGENT_MEMORY_REVIEW_DECISION_DB','INDEX_OUTBOX_PATH','MEMORY_INTENT_TRACE_PATH'},'fixture_restore_runtime_producers_missing'
# The fixture's channel-config file hashes freeze the selected source/model/TTS
# configuration without copying values or secrets into the report.
for filename,digest in f['configuration_hashes'].items():
 target=pathlib.Path(filename)
 assert target.is_file() and not target.is_symlink() and hashlib.sha256(target.read_bytes()).hexdigest()==digest,'fixture_restore_configuration_changed'
from app.rebuildability.product_total_loss import parse_bounded_frontmatter
hashes={};marker_present=False
for name in ('known','capture'):
 spec=f['notes'][name];target=root/spec['path']
 assert spec['path']==p[name+'_note_path'] and spec['uuid']==p[name+'_note_uuid'],'fixture_restore_note_identity_mismatch'
 assert target.is_file() and not target.is_symlink() and target.resolve(strict=True).is_relative_to(root),'fixture_restore_note_path_mismatch'
 raw=target.read_bytes();assert len(raw)<=2*1024*1024
 fm,body,error=parse_bounded_frontmatter(raw.decode());assert error is None
 assert str(fm.get('uuid') or fm.get('id') or '')==spec['uuid'],'fixture_restore_note_identity_mismatch'
 digest=hashlib.sha256(raw).hexdigest();hashes[name]=digest
 if not p['effects'].get('panel_confirm') and name=='known':
  assert digest==spec['raw_sha256'],'fixture_restore_source_changed'
 if not p['effects'].get('capture') and name=='capture':
  assert digest==spec['raw_sha256'],'fixture_restore_capture_changed'
 if name=='capture':marker_present=p['marker'] in body
from app.vault.paths import get_vault_capture_note_rel
assert get_vault_capture_note_rel(root)==p['capture_note_path'],'fixture_restore_capture_producer_mismatch'
receipt=None
if p.get('confirmation'):
 db=pathlib.Path(os.environ['PANEL_STAGING_DB_PATH'])
 assert db.is_file() and not db.is_symlink(),'fixture_restore_receipt_store_missing'
 with sqlite3.connect(db.as_uri()+'?mode=ro',uri=True) as conn:
  row=conn.execute('SELECT response_json FROM panel_confirm_idempotency WHERE key=?',(p['confirmation']['idempotency_key'],)).fetchone()
 if row:receipt=json.loads(row[0])
print(json.dumps({'binding_verified':True,'first_contact_navigation_safe':briefing_safe,'synthetic_fixture_verified':True,'test_resource_version':f['test_resource_version'],'note_hashes':hashes,'source_has_marker':marker_present,'persisted_confirmation':receipt,'configuration_hashes':f['configuration_hashes']}))
'''


def verify_channel_lock(d: dict[str, Any]) -> None:
    """Observe the existing native lock owner; never create or take a deploy lock."""
    if not Path("/proc/locks").is_file():
        raise Blocked("qualified_tars_linux_guest_required")
    target = Path(d["native_channel_lock_path"])
    if target.is_symlink() or not target.is_file():
        raise Blocked("existing_native_channel_lock_required")
    info = target.stat()
    if stat.S_IMODE(info.st_mode) != 0o600 or info.st_uid != os.geteuid():
        raise Blocked("native_channel_lock_identity_mismatch")
    device = f"{os.major(info.st_dev):02x}:{os.minor(info.st_dev):02x}:{info.st_ino}"
    owner = str(d["native_channel_lock_pid"])
    matched = any(
        len(parts := line.split()) >= 8
        and parts[1:4] == ["FLOCK", "ADVISORY", "WRITE"]
        and parts[4] == owner and parts[5] == device
        for line in Path("/proc/locks").read_text().splitlines()
    )
    if not matched:
        raise Blocked("native_channel_lock_not_held_by_declared_owner")


def native_probe(d: dict[str, Any], marker: str) -> dict[str, Any]:
    verify_channel_lock(d)
    if hashlib.sha256(Path("/etc/machine-id").read_bytes()).hexdigest() != d["expected_machine_id_sha256"]:
        raise Blocked("qualified_runtime_host_identity_mismatch")
    api_id, api, ui = native_gateway(d)
    for row in (api, ui):
        images = json.loads(native_command(["docker", "image", "inspect", row["Image"]]))
        if len(images) != 1 or d["expected_image_digest"] not in {
            str(value).rsplit("@", 1)[-1] for value in images[0].get("RepoDigests", [])
        }:
            raise Blocked("running_image_digest_mismatch")
    values = {k: d[k] for k in (
        "channel", "vault_id", "vault_path", "known_note_path", "known_note_uuid",
        "capture_note_path", "capture_note_uuid", "test_resource_version", "memory_candidates",
        "fixture_metadata_path", "fixture_metadata_sha256",
        "effect_budget",
        "local_instance_id",
    )}
    values.update(marker=marker, effects=d.get("effects", {}), confirmation=d.get("confirmation"))
    proof = json.loads(native_command(
        ["docker", "exec", "-i", api_id, "python", "-c", _DEEP_PROBE], input=json.dumps(values)
    ))
    proof.update(gateway_upstream_verified=True, image_digest=d["expected_image_digest"], native_lock_verified=True)
    return proof


def _actual_proof(row: dict[str, Any], report: dict[str, Any]) -> bool:
    proof = row.get("proof")
    if not isinstance(proof, dict) or proof.get("source") != "served_product":
        return False
    name = row["id"]
    if name == "native_admission":
        native = proof.get("native") or {}
        return (
            native.get("gateway_upstream_verified") is True
            and native.get("synthetic_fixture_verified") is True
            and native.get("native_lock_verified") is True
            and native.get("first_contact_navigation_safe") is True
            and native.get("image_digest") == report["expected_image_digest"]
            and native.get("test_resource_version") == report["test_resource_version"]
            and bool(native.get("configuration_hashes"))
            and proof.get("served_sha") == report["expected_sha"]
        )
    if name == "a1_overlay_selection_continuity":
        return proof.get("cycles") == 2 and bool(proof.get("selection"))
    if name == "a1_runtime_resume_position":
        prior = proof.get("prior_view") or {}
        restored = proof.get("restored") or {}
        leave = proof.get("runtime_leave_point") or {}
        return (
            leave.get("status") == "present" and bool(restored)
            and leave.get("artifact_ref", {}).get("artifact_uuid") == prior.get("artifact_id")
            and leave.get("artifact_ref", {}).get("logical_ref") == prior.get("note_path")
            and all(restored.get(key) == prior.get(key) for key in ("start", "end", "editor_scroll", "reading_scroll"))
        )
    if name == "b4_all_overlay_focus_escape_return":
        overlays = proof.get("overlays") or {}
        return set(overlays) == {"cmd", "capture", "receipts", "settings", "memory", "map"} and all(
            outcome == {"focus_trap": True, "escape": True, "focus_return": True} for outcome in overlays.values()
        )
    if name == "populated_vault_list_and_inspector":
        return bool(proof.get("note_uuid")) and proof.get("list_count", 0) > 0 and proof.get("inspector") is True
    if name == "populated_governed_apply_exact_receipt":
        ack = proof.get("confirmation") or {}
        return (
            ack.get("status") == "executed" and ack.get("outcome") == "success"
            and bool(ack.get("receipt", {}).get("receipt_id"))
            and proof.get("exact_persisted_readback") is True
            and proof.get("receipt_history") is True and report["effects"].get("panel_confirm") == 1
        )
    if name.startswith("populated_memory_"):
        action = name.removeprefix("populated_memory_")
        decision = proof.get("decision") or {}
        expected = {"accept": "accepted", "reject": "rejected", "revise": "revised", "defer": "deferred"}[action]
        return (
            decision.get("status") == expected
            and isinstance(proof.get("actual_pending_ids"), list)
            and bool(proof.get("server_authority"))
            and report["effects"].get("memory_" + action) == 1
        )
    if name == "populated_capture_confirmation_and_caret":
        ack = proof.get("capture") or {}
        return ack.get("outcome") == "written" and bool(ack.get("trace_id")) and proof.get("source_readback") is True and proof.get("selection_restored") is True and report["effects"].get("capture") == 1
    if name == "public_copy_populated_and_entry":
        return set(proof.get("surfaces", [])) == {"shell", "entry", "cmd", "memory", "receipts", "settings", "map"} and proof.get("public_copy_clean") is True
    return name == "public_copy_degraded" and row.get("kind") == "browser_fault_injection" and proof.get("kind") == "browser_fault_injection" and proof.get("calm_unavailable") is True


def acceptance_passed(report: dict[str, Any]) -> bool:
    rows = report.get("scenarios", [])
    end = report.get("actual_proof", {}).get("end") or {}
    admission = report.get("actual_proof", {}).get("native") or {}
    return (
        report.get("execution_kind") == "live"
        and report.get("channel") == "test"
        and report.get("identity_verified") is True
        and report.get("end_identity_verified") is True and report.get("end_identity_error") is None
        and end.get("verified") is True and bool(admission.get("api_identity"))
        and end.get("api") == admission["api_identity"]
        and end["api"].get("source_sha") == report.get("expected_sha")
        and end["api"].get("image_digest") == report.get("expected_image_digest")
        and end["api"].get("resource_tree") == report.get("test_resource_version")
        and end["api"].get("resource_generation") == report.get("run_id")
        and end["api"].get("fixture", {}).get("local_clone_id") == report.get("local_instance_id")
        and type(end["api"].get("api_pid")) is int and end["api"]["api_pid"] > 0
        and end["api"].get("api_module") == "/app/app/main.py"
        and end.get("effects") == report.get("effects")
        and not report.get("refused_requests")
        and report.get("required_scenarios") == list(SCENARIOS)
        and [row.get("id") for row in rows] == list(SCENARIOS)
        and all(row.get("status") == "passed" and _actual_proof(row, report) for row in rows)
        and set(report.get("effects", {})) == set(EFFECT_BUDGET)
        and all(type(report["effects"][k]) is int and 0 <= report["effects"][k] <= n for k, n in EFFECT_BUDGET.items())
        and report.get("artifacts", {}).get("trace") == "trace.zip"
        and report.get("artifacts", {}).get("junit") == "junit.xml"
    )


class DeepReview(CoreFlow):
    def __init__(
        self, d: dict[str, Any], browser: Any,
        probe: Callable[[dict[str, Any], str], dict[str, Any]] = native_probe,
        *, execution_kind: str = "contract_test",
        output_created: Callable[[Path], None] | None = None,
    ) -> None:
        self.effects = {name: 0 for name in EFFECT_BUDGET}
        self.armed: str | None = None
        self.proposal_id: str | None = None
        self.prior_view: dict[str, Any] | None = None
        self.confirmation: dict[str, Any] | None = None
        self.refused_requests: list[str] = []
        self.actual_proof: dict[str, Any] = {}
        self.artifacts: dict[str, str] = {}
        self.execution_kind = execution_kind
        self.native_binding = NativeDeepBinding(d["native_envelope"]) if "native_envelope" in d else None
        self.end_identity_verified = False
        self.end_identity_error: str | None = None
        self.harness_files = (Path(__file__), Path(live_core_flow.__file__))
        self.harness_hashes = {p.name: hashlib.sha256(p.read_bytes()).hexdigest() for p in self.harness_files}
        self.adapter_sha256 = hashlib.sha256(Path(__file__).with_name("native_deep_review.py").read_bytes()).hexdigest()
        self.manifest_sha256 = self.native_binding.manifest_sha256 if self.native_binding else hashlib.sha256(json.dumps(d, sort_keys=True).encode()).hexdigest()
        super().__init__(d, browser, probe, output_created=output_created)
        self._write_report()

    def _binding(self) -> dict[str, Any]:
        if any(hashlib.sha256(p.read_bytes()).hexdigest() != self.harness_hashes[p.name] for p in self.harness_files):
            raise Blocked("frozen_runner_changed_during_invocation")
        if hashlib.sha256(Path(__file__).with_name("native_deep_review.py").read_bytes()).hexdigest() != self.adapter_sha256:
            raise Blocked("frozen_native_adapter_changed_during_invocation")
        if self.native_binding is not None and self.harness_hashes != self.native_binding.binding["harness_hashes"]:
            raise Blocked("native_admitted_harness_hash_mismatch")
        self.d["effects"] = dict(self.effects)
        self.d["confirmation"] = self.confirmation
        self.d["capture_acknowledgement"] = self.ack
        if self.execution_kind == "live" and self.native_binding is None:
            raise Blocked("fixed_native_web_invocation_required")
        proof = self.native_binding.proof(self.d, self.marker) if self.native_binding else self.probe(self.d, self.marker)
        if (
            proof.get("gateway_upstream_verified") is not True
            or proof.get("binding_verified") is not True
            or proof.get("synthetic_fixture_verified") is not True
            or proof.get("native_lock_verified") is not True
            or proof.get("image_digest") != self.d["expected_image_digest"]
            or proof.get("test_resource_version") != self.d["test_resource_version"]
        ):
            raise Blocked("frozen_synthetic_test_resource_not_admitted")
        if proof.get("first_contact_navigation_safe") is not True:
            raise Blocked("first_contact_would_generate_unbudgeted_briefing")
        context = self._get(urljoin(self.d["api_url"], "/api/companion/vault/context"))
        if (
            context.get("status") != "selected"
            or context.get("active_vault_id") != self.d["vault_id"]
            or context.get("active_vault_path") != self.d["vault_path"]
            or context.get("local_instance_id") != self.d["local_instance_id"]
        ):
            raise Blocked("active_fixture_binding_mismatch")
        # The outer native consumer binds admission to this exact first proof.
        # Later mutable acknowledgements belong to their own scenario/end proof.
        self.actual_proof.setdefault("native", proof)
        return proof

    def _guard_request(self, route: Any) -> None:
        req = route.request
        if _origin(req.url) != _origin(self.d["ui_url"]):
            self._refuse(route, "browser_request_to_other_origin")
            return
        path = urlparse(req.url).path
        if req.method in {"GET", "HEAD", "OPTIONS"}:
            if path in {"/", "/workspace"}:
                try:
                    self._admit_navigation()
                except Exception:
                    self._refuse(route, "document_get_without_native_admission")
                    return
            route.continue_()
            return
        if not self.identity_ok or self.armed is None:
            self._refuse(route, "unarmed_mutation")
            return
        try:
            payload = req.post_data_json or {}
            name = self.armed
            valid = self._effect_target_matches(name, req.method, path, payload)
            if not valid or self.effects[name] >= self.d["effect_budget"][name]:
                self._refuse(route, "wrong_target_or_effect_budget_exhausted")
                return
            self._binding()
        except Exception:
            self._refuse(route, "effect_target_not_admitted")
            return
        self.effects[name] += 1
        self.armed = None
        # Reserve before transport: even an unknown result cannot silently
        # authorize another mutation. Persist acknowledgements separately.
        self._write_report()
        if self.native_binding is not None:
            try:
                self.native_binding.before_effect(name, dict(self.effects))
            except Exception:
                self._refuse(route, "native_before_effect_refused")
                return
        route.continue_()

    def _refuse(self, route: Any, reason: str) -> None:
        self.refused_requests.append(reason)
        self._write_report()
        route.abort("blockedbyclient")

    def _effect_target_matches(self, name: str, method: str, path: str, payload: dict[str, Any]) -> bool:
        if name == "capture":
            return method == "POST" and path == "/api/companion/capture" and set(payload) == {"text"} and payload.get("text") == self.text
        if name == "queue_review":
            return (
                method == "POST" and path == "/api/companion/vault-browser/actions/queue-review"
                and payload.get("note_path") == self.d.get("review_note_path", self.d["known_note_path"])
                and payload.get("artifact_uuid") in {None, self.d.get("review_note_uuid", self.d["known_note_uuid"])}
                and set(payload) <= {"note_path", "artifact_uuid"}
            )
        if name == "panel_confirm":
            return (
                method == "POST" and path == "/api/panel/confirm" and bool(self.proposal_id)
                and payload.get("proposal_id") == self.proposal_id
                and payload.get("artifact_id") == self.d.get("review_note_uuid", self.d["known_note_uuid"])
                and payload.get("action") == "confirm" and isinstance(payload.get("idempotency_key"), str)
                and bool(payload["idempotency_key"])
                and set(payload) == {"proposal_id", "artifact_id", "action", "idempotency_key"}
            )
        if name.startswith("memory_"):
            action = name.removeprefix("memory_")
            return (
                method == "POST"
                and path == "/api/companion/memory/review-queue/" + self.d["memory_candidates"][action] + "/decision"
                and payload.get("action") == action
                and set(payload) == {"action", "reviewed_by"}
                and payload.get("reviewed_by") == "companion-ui:reviewer"
            )
        return False

    def _proof(self, **values: Any) -> None:
        self.actual_proof["current"] = {"source": "served_product", **values}

    def _note(self) -> None:
        self._need_identity()
        self._open_note(self.page, self.d["known_note_path"])

    def native_admission(self) -> None:
        self.channel_gateway_and_health()
        self._proof(native=self.actual_proof["native"], served_sha=self.d["expected_sha"])

    def a1_overlay_selection_continuity(self) -> None:
        self._note()
        self.page.locator('[data-testid="workspace-note-utility-edit"]:visible').first.click()
        editor = self.page.locator('[data-testid="workspace-note-source-editor"]:visible').first
        editor.wait_for(state="visible")
        editor.focus()
        expected = editor.evaluate("e => {e.setSelectionRange(5, 12); e.scrollTop=12; return {start:e.selectionStart,end:e.selectionEnd,scroll:e.scrollTop,text:e.value};}")
        self.prior_view = self.page.evaluate("window.noteViewPosition ? window.noteViewPosition.snapshot() : null")
        for _ in range(2):
            self.page.keyboard.press("Control+k")
            self.page.get_by_test_id("panel-palette").wait_for(state="visible")
            self.page.keyboard.press("Escape")
            self.page.get_by_test_id("panel-palette").wait_for(state="hidden")
            actual = editor.evaluate("e => ({start:e.selectionStart,end:e.selectionEnd,scroll:e.scrollTop,text:e.value})")
            assert actual == expected, "overlay_dismiss_lost_editor_selection_or_draft"
        self._proof(selection=expected, overlay="cmd", cycles=2)

    def a1_runtime_resume_position(self) -> None:
        # The runtime admits the current artifact pointer; geometry remains
        # the real prior same-browser interaction, never runtime trace state.
        self._need_identity()
        orientation = self._get(urljoin(self.d["api_url"], "/api/companion/orientation"))
        leave = orientation.get("leave_point") or {}
        if leave.get("status") != "present" or not self.prior_view:
            raise Blocked("current_artifact_and_prior_ephemeral_browser_view_required")
        assert leave.get("artifact_ref", {}).get("artifact_uuid") == self.d["known_note_uuid"], "resume_source_identity_mismatch"
        assert self.prior_view.get("vault_id") == self.d["vault_id"] and self.prior_view.get("local_instance_id") == self.d["local_instance_id"] and self.prior_view.get("artifact_id") == self.d["known_note_uuid"], "ephemeral_view_source_scope_mismatch"
        self._admit_navigation()
        self.page.goto(self.d["ui_url"], wait_until="domcontentloaded")
        resume = self.page.get_by_test_id("reentry-resume")
        resume.wait_for(state="visible")
        assert self.page.get_by_test_id("reentry-card").get_attribute("data-reentry-treatment") in {"full_mist", "long_mist"}, "qualified_reentry_rung_required"
        self._admit_navigation()
        resume.click()
        self.page.get_by_test_id("workspace-note-rendered").wait_for(state="visible")
        self.page.wait_for_function("document.body.dataset.resumePosition === 'restored'")
        actual = self.page.locator('[data-testid="workspace-note-source-editor"]:visible').first.evaluate("e => ({start:e.selectionStart,end:e.selectionEnd,editor_scroll:e.scrollTop,reading_scroll:e.closest('.note-body').scrollTop})")
        assert actual == {key: self.prior_view[key] for key in actual}, "runtime_admitted_ephemeral_position_not_restored"
        self._proof(runtime_leave_point=leave, prior_view=self.prior_view, restored=actual)

    def _open_overlay(self, overlay: str) -> None:
        self.page.locator('[data-intent="map.open"]:visible').first.click()
        if overlay != "map":
            surface = "palette" if overlay == "cmd" else overlay
            self.page.locator('[data-testid="system-map-node"][data-surface-id="' + surface + '"]').click()
        self.page.locator('[data-overlay-id="' + overlay + '"][data-overlay-focus-trap="true"]').wait_for(state="visible")

    def b4_all_overlay_focus_escape_return(self) -> None:
        self._note()
        controls: dict[str, Any] = {}
        for overlay in ("cmd", "capture", "receipts", "settings", "memory", "map"):
            anchor = self.page.locator('[data-intent="map.open"]:visible').first
            anchor.focus()
            self._open_overlay(overlay)
            root = self.page.locator('[data-overlay-id="' + overlay + '"][data-overlay-focus-trap="true"]')
            items = root.locator('a[href]:visible, button:not([disabled]):visible, textarea:not([disabled]):visible, input:not([disabled]):visible, select:not([disabled]):visible, [tabindex]:not([tabindex="-1"]):visible')
            assert items.count() > 0, "overlay_has_no_focusable_controls:" + overlay
            items.last.focus()
            self.page.keyboard.press("Tab")
            assert items.first.evaluate("e => e === document.activeElement"), "forward_focus_trap_failed:" + overlay
            self.page.keyboard.press("Shift+Tab")
            assert items.last.evaluate("e => e === document.activeElement"), "reverse_focus_trap_failed:" + overlay
            self.page.keyboard.press("Escape")
            root.wait_for(state="hidden")
            assert anchor.evaluate("e => e === document.activeElement"), "overlay_focus_return_failed:" + overlay
            controls[overlay] = {"focus_trap": True, "escape": True, "focus_return": True}
        self._proof(overlays=controls)

    def populated_vault_list_and_inspector(self) -> None:
        self._note()
        runtime = self._get(urljoin(self.d["api_url"], "/api/companion/vault/notes"))
        assert any(x.get("path") == self.d["known_note_path"] for x in runtime.get("notes", [])), "synthetic_note_absent_from_actual_vault_list"
        inspector = self.page.get_by_test_id("vault-browser-note-inspector")
        if not inspector.count():
            inspector = self.page.get_by_test_id("workspace-vault-browser-inspector")
        inspector.wait_for(state="visible")
        assert self.d["known_note_path"] in inspector.inner_text(), "actual_vault_inspector_missing_selected_note"
        self._proof(note_uuid=self.d["known_note_uuid"], list_count=len(runtime["notes"]), inspector=True)

    def _acknowledged_rail_receipt(self, receipt_id: str) -> Any:
        # The served Apply consumer also updates a hidden palette clone. Bind
        # proof to the originating rail/proposal and exact acknowledgement.
        assert self.proposal_id, "proposal_producer_identity_missing"
        rail = self.page.get_by_test_id("workspace-agent-rail")
        confirmed = rail.locator('[data-testid="workspace-panel-confirm-response"][data-proposal-id="' + self.proposal_id + '"]')
        applied = confirmed.get_by_test_id("workspace-panel-receipt-card")
        applied.wait_for(state="visible")
        assert "Applied · receipt recorded" in applied.inner_text(), "post_apply_confirmation_not_rendered"
        link = applied.get_by_test_id("workspace-panel-receipt-link-to-history")
        assert link.get_attribute("data-receipt-id") == receipt_id, "receipt_link_identity_mismatch"
        return applied

    def populated_governed_apply_exact_receipt(self) -> None:
        note_path = self.d.get("review_note_path", self.d["known_note_path"])
        note_uuid = self.d.get("review_note_uuid", self.d["known_note_uuid"])
        self._need_identity()
        self._open_note(self.page, note_path)
        self.armed = "queue_review"
        with self.page.expect_response(lambda r: urlparse(r.url).path == "/api/companion/vault-browser/actions/queue-review" and r.request.method == "POST", timeout=self.d["request_ms"]) as received:
            self.page.get_by_test_id("vault-action-queue-review").first.click()
        result = received.value
        assert result.ok, "synthetic_proposal_producer_failed"
        payload = result.json()
        assert payload.get("artifact_uuid") == note_uuid and payload.get("note_path") == note_path, "proposal_producer_target_mismatch"
        self.proposal_id = payload.get("proposal_id")
        assert isinstance(self.proposal_id, str) and self.proposal_id, "proposal_producer_identity_missing"
        self._write_report()
        # Ordinary confirmation still honors the existing five-second
        # same-turn gate (panel.confirmation.SAME_TURN_TTL_SECONDS). A frozen
        # candidate with a different gate must truthfully fail, never bypass it.
        self.page.wait_for_timeout(6000)
        self._open_note(self.page, note_path)
        runtime = self._get(urljoin(self.d["api_url"], "/api/companion/workspace") + "?note_path=" + quote(note_path))
        assert any(x.get("proposal_id") == self.proposal_id for x in runtime.get("panel", {}).get("proposals", [])), "actual_runtime_proposal_not_projected"
        rail = self.page.get_by_test_id("workspace-agent-rail")
        card = rail.locator('[data-testid="workspace-panel-proposal-row"][data-proposal-id="' + self.proposal_id + '"]')
        card.wait_for(state="visible")
        before_scroll = rail.evaluate("e => e.scrollTop")
        self.armed = "panel_confirm"
        with self.page.expect_response(lambda r: urlparse(r.url).path == "/api/panel/confirm" and r.request.method == "POST", timeout=self.d["request_ms"]) as received:
            card.locator('[data-testid="workspace-panel-action"][data-panel-action="confirm"]').click()
        response = received.value
        self.confirmation = response.json()
        self._write_report()  # A later UI/readback failure cannot erase the acknowledgement.
        assert response.ok and self.confirmation.get("status") == "executed", "apply_not_runtime_confirmed"
        assert self.confirmation.get("proposal_id") == self.proposal_id and self.confirmation.get("artifact_id") == note_uuid, "apply_acknowledgement_target_mismatch"
        receipt = self.confirmation.get("receipt") or {}
        assert receipt.get("receipt_id") and receipt.get("timestamp") and receipt.get("outcome") == "success", "actual_apply_receipt_missing"
        proof = self._binding()
        assert proof.get("persisted_confirmation") == self.confirmation, "exact_apply_ack_not_persisted"
        applied = self._acknowledged_rail_receipt(receipt["receipt_id"])
        assert not card.locator('[data-testid="workspace-panel-action"]:visible').count(), "proposal_actions_survive_apply"
        assert rail.evaluate("e => e.scrollTop") == before_scroll, "post_apply_confirmation_requires_rail_scroll"
        link = applied.get_by_test_id("workspace-panel-receipt-link-to-history")
        link.click()
        row = self.page.locator('[data-testid="receipts-history-row"][data-receipt-id="' + receipt["receipt_id"] + '"]')
        row.wait_for(state="visible")
        assert row.get_attribute("data-receipt-status") in {"executed", "success"}, "exact_receipt_history_outcome_missing"
        self.page.keyboard.press("Escape")
        self._proof(confirmation=self.confirmation, exact_persisted_readback=True, receipt_history=True)

    def _memory_decision(self, action: str) -> None:
        self._note()
        self._open_overlay("memory")
        candidate_id = self.d["memory_candidates"][action]
        queue = self._get(urljoin(self.d["api_url"], "/api/companion/memory/review-queue"))
        candidate = next((x for x in queue.get("candidates", []) if x.get("candidate_id") == candidate_id), None)
        if candidate is None:
            raise Blocked("normal_produced_synthetic_memory_candidate_missing:" + action)
        row = self.page.locator('[data-testid="memory-review-candidate"][data-candidate-id="' + candidate_id + '"]')
        row.wait_for(state="visible")
        posture = candidate["authority_posture"]
        assert row.get_attribute("data-authority") == posture["authority"] and row.get_attribute("data-authority-role") == posture["authority_role"], "memory_authority_not_server_projected"
        self.armed = "memory_" + action
        endpoint = "/api/companion/memory/review-queue/" + candidate_id + "/decision"
        with self.page.expect_response(lambda r: urlparse(r.url).path == endpoint and r.request.method == "POST", timeout=self.d["request_ms"]) as received:
            row.get_by_test_id("memory-action-" + action).click()
        response = received.value
        payload = response.json()
        self.actual_proof["memory_" + action] = payload
        self._write_report()
        assert response.ok and payload.get("status") == {"accept": "accepted", "reject": "rejected", "revise": "revised", "defer": "deferred"}[action], "memory_decision_not_confirmed:" + action
        row.get_by_test_id("memory-decision-outcome").wait_for(state="visible")
        pending = self._get(urljoin(self.d["api_url"], "/api/companion/memory/review-queue"))
        ids = {x.get("candidate_id") for x in pending.get("candidates", [])}
        if action == "defer":
            assert payload.get("candidate_pending") is True and payload.get("receipt") is None and candidate_id in ids, "defer_invented_terminal_receipt"
        else:
            assert payload.get("receipt", {}).get("candidate_id") == candidate_id and candidate_id not in ids, "memory_receipt_or_actual_queue_readback_mismatch"
        if action == "revise":
            assert payload.get("revision_candidate_id") in ids, "revised_candidate_not_pending"
        if action == "accept":
            assert payload.get("materialization", {}).get("terminal") is True, "accepted_memory_not_durably_materialized"
        self.page.keyboard.press("Escape")
        self._proof(decision=payload, actual_pending_ids=sorted(ids), server_authority=posture)

    def populated_memory_accept(self) -> None:
        self._memory_decision("accept")

    def populated_memory_reject(self) -> None:
        self._memory_decision("reject")

    def populated_memory_revise(self) -> None:
        self._memory_decision("revise")

    def populated_memory_defer(self) -> None:
        self._memory_decision("defer")

    def populated_capture_confirmation_and_caret(self) -> None:
        self._note()
        self.page.locator('[data-testid="workspace-note-utility-edit"]:visible').first.click()
        editor = self.page.locator('[data-testid="workspace-note-source-editor"]:visible').first
        editor.focus()
        selection = editor.evaluate("e => {e.setSelectionRange(3, 8); return [e.selectionStart,e.selectionEnd,e.value];}")
        self.page.keyboard.press("Control+n")
        self.page.get_by_test_id("capture-input").fill(self.text)
        self.armed = "capture"
        with self.page.expect_response(lambda r: urlparse(r.url).path == "/api/companion/capture" and r.request.method == "POST", timeout=self.d["request_ms"]) as received:
            self.page.get_by_test_id("capture-save").click()
        response = received.value
        self.ack = response.json()
        self._write_report()
        assert response.ok, "actual_capture_failed"
        validate_capture_ack(self.ack, self.d["capture_note_path"], self.effects["capture"])
        item = self.page.locator('[data-capture-state="written"]').filter(has_text=self.marker)
        item.wait_for(state="visible")
        assert item.get_attribute("data-ack-trace-id") == self.ack["trace_id"], "capture_confirmation_identity_mismatch"
        assert self._binding().get("source_has_marker") is True, "actual_capture_missing_in_synthetic_source"
        self.page.keyboard.press("Escape")
        assert editor.evaluate("e => [e.selectionStart,e.selectionEnd,e.value]") == selection, "capture_dismiss_lost_selection"
        assert editor.evaluate("e => e === document.activeElement"), "capture_dismiss_did_not_return_caret"
        self._proof(capture=self.ack, source_readback=True, selection_restored=True)

    def _copy_scan(self) -> None:
        visible = self.page.locator("body").inner_text()
        assert FORBIDDEN_COPY.search(visible) is None, "raw_transport_enum_or_identifier_in_public_copy"
        for token in (self.proposal_id, self.d["known_note_uuid"], *self.d["memory_candidates"].values()):
            if token:
                assert token not in visible, "fixture_internal_identity_in_public_copy"

    def public_copy_populated_and_entry(self) -> None:
        self._note()
        self._copy_scan()
        for overlay in ("cmd", "memory", "receipts", "settings", "map"):
            self._open_overlay(overlay)
            self._copy_scan()
            self.page.keyboard.press("Escape")
        self._admit_navigation()
        self.page.goto(self.d["ui_url"], wait_until="domcontentloaded")
        self._copy_scan()
        self._proof(surfaces=["shell", "entry", "cmd", "memory", "receipts", "settings", "map"], public_copy_clean=True)

    def public_copy_degraded(self) -> None:
        self._note()
        endpoint = "**/receipts-history"
        # Fault injection exercises the actual served catch path. It proves
        # error presentation only, never a real backend success or outage.
        self.context.route(endpoint, lambda route: route.abort("failed"))
        try:
            self._open_overlay("receipts")
            self.page.get_by_test_id("receipts-history-unavailable").wait_for(state="visible")
            self._copy_scan()
            self._proof(kind="browser_fault_injection", surface="receipts", calm_unavailable=True)
        finally:
            self.context.unroute(endpoint)
            self.page.keyboard.press("Escape")

    def run(self) -> dict[str, Any]:
        try:
            for name in SCENARIOS:
                started = time.monotonic()
                self.actual_proof.pop("current", None)
                result: dict[str, Any] = {"id": name, "kind": "browser_fault_injection" if name == "public_copy_degraded" else "live"}
                try:
                    getattr(self, name)()
                    proof = self.actual_proof.get("current")
                    assert proof, "scenario_completed_without_actual_proof"
                    result.update(status="passed", proof=proof, reason=None)
                except Blocked as exc:
                    result.update(status="blocked", proof=None, reason=str(exc))
                except AssertionError as exc:
                    result.update(status="failed", proof=None, reason=str(exc)[:240])
                except Exception as exc:
                    result.update(status="failed", proof=None, reason=type(exc).__name__)
                finally:
                    self.armed = None
                result["seconds"] = round(time.monotonic() - started, 3)
                self.results.append(result)
                self._write_report()
                if result["status"] != "passed":
                    try:
                        path = self.output / (name + ".png")
                        self.page.screenshot(path=str(path))
                        os.chmod(path, 0o600)
                        result["screenshot"] = path.name
                    except Exception:
                        pass
        finally:
            try:
                if self.native_binding is None:
                    raise Blocked("final_fixed_native_identity_unavailable")
                self.actual_proof["end"] = self.native_binding.end(dict(self.effects), self.confirmation, self.ack)
                self.end_identity_verified = True
            except Exception as exc:
                self.end_identity_error = str(exc) if isinstance(exc, Blocked) else type(exc).__name__
                self.end_identity_verified = False
            try:
                path = self.output / "trace.zip"
                self.context.tracing.stop(path=str(path))
                os.chmod(path, 0o600)
                self.artifacts["trace"] = path.name
            finally:
                self.context.close()
                self._write_junit()
                self._write_report()
        return self._write_report()

    def _write_junit(self) -> None:
        suite = ET.Element("testsuite", name="companion-ui-deep-review", tests=str(len(SCENARIOS)))
        by_id = {row["id"]: row for row in self.results}
        for name in SCENARIOS:
            row = by_id.get(name, {"status": "missing", "reason": "required_scenario_missing"})
            case = ET.SubElement(suite, "testcase", name=name, classname="actual-test-deep-review", time=str(row.get("seconds", 0)))
            if row["status"] != "passed":
                ET.SubElement(case, "failure", type=row["status"]).text = row.get("reason") or "required_proof_missing"
            elif name == "native_admission" and not self.end_identity_verified:
                ET.SubElement(case, "failure", type="end_identity").text = self.end_identity_error or "required_end_identity_missing"
        path = self.output / "junit.xml"
        fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600)
        with os.fdopen(fd, "wb") as stream:
            ET.ElementTree(suite).write(stream, encoding="utf-8", xml_declaration=True)
        self.artifacts["junit"] = path.name

    def _write_report(self) -> dict[str, Any]:
        report = {
            "schema": "companion_ui_deep_review_execution.v1",
            "execution_kind": self.execution_kind, "channel": self.d["channel"],
            "expected_sha": self.d["expected_sha"], "expected_image_digest": self.d["expected_image_digest"],
            "harness_hashes": dict(self.harness_hashes), "manifest_sha256": self.manifest_sha256,
            "run_id": self.d["run_id"], "test_resource_version": self.d["test_resource_version"],
            "qualification_ref": self.d["qualification_ref"],
            "fixture_metadata_sha256": self.d["fixture_metadata_sha256"],
            "local_instance_id": self.d["local_instance_id"],
            "required_scenarios": list(SCENARIOS), "scenarios": self.results,
            "identity_verified": self.identity_ok, "effects": dict(self.effects),
            "effect_budget": dict(self.d["effect_budget"]), "refused_requests": list(self.refused_requests),
            "backend_acknowledgements": {"proposal_id": self.proposal_id, "panel_confirm": self.confirmation, "capture": self.ack},
            "actual_proof": self.actual_proof, "artifacts": dict(self.artifacts),
            "end_identity_verified": self.end_identity_verified, "end_identity_error": self.end_identity_error,
        }
        report["passed"] = acceptance_passed(report)
        temporary = self.output / "report.json.next"
        fd = os.open(temporary, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600)
        with os.fdopen(fd, "w") as stream:
            json.dump(report, stream, ensure_ascii=False, indent=2)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, self.output / "report.json")
        directory = os.open(self.output, os.O_RDONLY | os.O_DIRECTORY)
        try:
            os.fsync(directory)
        finally:
            os.close(directory)
        return report


def execute_manifest(path: Path | None) -> dict[str, Any]:
    # An explicitly invoked runner can refuse before native prepares its input
    # (e.g. the delivered Daily helper is missing). Retain that actual attempt
    # in Builder scratch with unknown expectations, never fabricate a context.
    d: dict[str, Any] = {
        "output_dir": str(Path.cwd() / ".codex-tmp" / ("deep-review-refusal-" + str(uuid4()))),
        "channel": "test", "run_id": None, "effect_budget": dict(EFFECT_BUDGET),
    }
    owned_output: tuple[int, int] | None = None
    input_sha256: str | None = None

    def output_created(output: Path) -> None:
        nonlocal owned_output
        info = output.lstat()
        assert stat.S_ISDIR(info.st_mode), "invocation_output_not_directory"
        owned_output = (info.st_dev, info.st_ino)

    try:
        if path is None:
            raise Blocked("qualified_native_manifest_unavailable")
        raw = read_private_json(path)
        input_sha256 = hashlib.sha256(json.dumps(raw, sort_keys=True).encode()).hexdigest()
        if raw.get("schema") == "native-web-pilot-manifest.v1":
            d = NativeDeepBinding.expected_data(raw)
        d = load_manifest(path)
        from playwright.sync_api import sync_playwright

        with sync_playwright() as playwright:
            browser = playwright.chromium.launch()
            try:
                return DeepReview(d, browser, execution_kind="live", output_created=output_created).run()
            finally:
                browser.close()
    except Exception as exc:
        output = Path(d["output_dir"])
        if (not output.is_absolute() or output.is_symlink() or any(p.is_symlink() for p in output.parents)
            or output.resolve() != output):
            raise
        # The constructor may create this invocation's directory before context
        # or tracing startup fails. Only that exact, still-empty directory may
        # receive a startup report; never replace prior evidence/reservations.
        if output.exists():
            info = output.lstat()
            if not stat.S_ISDIR(info.st_mode) or (info.st_dev, info.st_ino) != owned_output or any(output.iterdir()):
                raise
        elif owned_output is not None:
            raise  # Our directory was removed; do not silently create a new run.
        else:
            output.mkdir(mode=0o700, parents=True, exist_ok=False)
            output_created(output)
        report = {
            "schema": "companion_ui_deep_review_execution.v1", "execution_kind": "live",
            "channel": d.get("channel"), "expected_sha": d.get("expected_sha"),
            "expected_image_digest": d.get("expected_image_digest"), "run_id": d.get("run_id"),
            "test_resource_version": d.get("test_resource_version"), "qualification_ref": d.get("qualification_ref"),
            "fixture_metadata_sha256": d.get("fixture_metadata_sha256"),
            "local_instance_id": d.get("local_instance_id"),
            "harness_hashes": {p.name: hashlib.sha256(p.read_bytes()).hexdigest() for p in (Path(__file__), Path(live_core_flow.__file__))},
            "manifest_sha256": d.get("native_manifest_sha256") or input_sha256,
            "required_scenarios": list(SCENARIOS), "identity_verified": False,
            "effects": {name: 0 for name in EFFECT_BUDGET}, "effect_budget": dict(EFFECT_BUDGET),
            "scenarios": [{"id": name, "status": "blocked", "proof": None, "reason": "runner_startup_failed:" + (str(exc) if isinstance(exc, Blocked) else type(exc).__name__)} for name in SCENARIOS],
            "artifacts": {}, "refused_requests": [], "passed": False,
            "backend_acknowledgements": {"proposal_id": None, "panel_confirm": None, "capture": None},
            "actual_proof": {},
            "end_identity_verified": False, "end_identity_error": "runner_startup_failed",
            "identity_gaps": [key for key in ("expected_sha", "expected_image_digest", "run_id", "test_resource_version", "qualification_ref", "fixture_metadata_sha256", "local_instance_id") if not d.get(key)],
            "observed_native_identity": None,
        }
        directory = os.open(output, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
        try:
            info = os.fstat(directory)
            if (info.st_dev, info.st_ino) != owned_output or os.listdir(directory):
                raise
            os.fchmod(directory, 0o700)
            descriptor = os.open("report.json", os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600, dir_fd=directory)
            with os.fdopen(descriptor, "w") as stream:
                json.dump(report, stream, indent=2)
                stream.flush()
                os.fsync(stream.fileno())
            os.fsync(directory)
        finally:
            os.close(directory)
        return report
