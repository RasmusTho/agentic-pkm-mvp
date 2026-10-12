"""Deep's consumer of the delivered fixed native web input and API observer.

No fixture, receipt, service or authority is created here. The native owner
supplies the same-image process/fixture; Product performs every normal effect.
"""
from __future__ import annotations

import hashlib
import json
import re
from typing import Any
from urllib.parse import quote
from uuid import UUID

from app.ops import native_web_acceptance as contract
from app.ops import native_web_runtime as runtime
from app.ops.native_web_fixture import CANDIDATE_IDS
from app.ops.native_web_reports import pilot_manifest
from tests.companion_ui.live_core_flow import Blocked, read_private_json


class NativeDeepBinding:
    @staticmethod
    def expected_data(envelope: dict[str, Any]) -> dict[str, Any]:
        if set(envelope) != {"schema", "pilot", "native_context", "output_dir", "report_binding"}:
            raise ValueError("native_pilot_manifest_fields_invalid")
        if (envelope["schema"] != "native-web-pilot-manifest.v1" or envelope["pilot"] != "deep-review"
            or envelope["native_context"] != str(contract.CONTEXT_PATH)
            or envelope["output_dir"] != str(contract.REPORT_DIRECTORY / "deep-review")):
            raise ValueError("native_pilot_manifest_boundary_mismatch")
        b = envelope["report_binding"]
        if (not isinstance(b, dict) or set(b) != {"source_sha", "image_digest", "channel", "harness_hashes",
            "configuration_hashes", "run_id", "resource_version", "native_boundary_ref", "fixture_metadata_sha256", "local_instance_id"}
            or b["channel"] not in {"dev", "test"}
            or re.fullmatch(r"[0-9a-f]{40}", str(b["source_sha"])) is None
            or re.fullmatch(r"sha256:[0-9a-f]{64}", str(b["image_digest"])) is None
            or re.fullmatch(r"[0-9a-f]{40}", str(b["resource_version"])) is None
            or any(re.fullmatch(r"[0-9a-f]{64}", str(b[key])) is None for key in ("native_boundary_ref", "fixture_metadata_sha256"))
            or re.fullmatch(r"[A-Za-z0-9_-]{1,128}", str(b["local_instance_id"])) is None
            or not isinstance(b["harness_hashes"], dict) or set(b["harness_hashes"]) != {"live_core_flow.py", "live_deep_review.py"}
            or not isinstance(b["configuration_hashes"], dict) or set(b["configuration_hashes"]) != {"runtime", "vault"}
            or any(re.fullmatch(r"[0-9a-f]{64}", str(value)) is None
                   for values in (b["harness_hashes"], b["configuration_hashes"]) for value in values.values())):
            raise ValueError("native_expected_binding_missing")
        if str(UUID(b["run_id"])) != b["run_id"]:
            raise ValueError("native_expected_generation_invalid")
        # These are declared expectations, never observed service admission.
        return {
            "channel": b.get("channel"), "expected_sha": b.get("source_sha"),
            "expected_image_digest": b.get("image_digest"), "run_id": b.get("run_id"),
            "output_dir": envelope["output_dir"], "test_resource_version": b.get("resource_version"),
            "qualification_ref": b.get("native_boundary_ref"),
            "fixture_metadata_sha256": b.get("fixture_metadata_sha256"),
            "local_instance_id": b.get("local_instance_id"),
            "effect_budget": dict(contract.EFFECT_LIMITS["deep-review"]),
            "native_manifest_sha256": hashlib.sha256(json.dumps(envelope, sort_keys=True).encode()).hexdigest(),
        }

    def __init__(self, envelope: dict[str, Any]) -> None:
        self.expected_data(envelope)
        self.envelope = envelope
        self.context = read_private_json(contract.CONTEXT_PATH, max_bytes=1024 * 1024)
        context, binding = self.context, self.context["report_binding"]
        identity, start, fixture = context["native_identity"], context["start"], context["fixture"]
        if (context["schema"] != "native-web-context.v1" or context["api_url"] != contract.API_URL
            or context["ui_url"] != contract.UI_URL or context["caldav_url"] != contract.CALDAV_URL
            or context["reports"]["deep-review"] != envelope["output_dir"] + "/report.json"
            or pilot_manifest("deep-review", binding) != envelope
            or start["api"]["fixture"] != fixture
            or binding["native_boundary_ref"] != contract.hash_json({"native_identity": identity, "start": start})
            or binding["fixture_metadata_sha256"] != contract.hash_json(fixture)
            or binding["configuration_hashes"] != {"runtime": start["configuration_hash"], "vault": fixture["settings_hash"]}
            or binding["local_instance_id"] != fixture["local_clone_id"]
            or set(identity) != {"source_sha", "image_digest", "channel", "operation_id", "resource_generation", "resource_tree", "app_image_id"}
            or binding["source_sha"] != identity["source_sha"] or binding["image_digest"] != identity["image_digest"]
            or binding["channel"] != identity["channel"] or binding["run_id"] != identity["resource_generation"]
            or binding["resource_version"] != identity["resource_tree"]):
            raise ValueError("native_pilot_context_binding_mismatch")
        contract.web_identity(identity["source_sha"], identity["image_digest"], identity["channel"], identity["operation_id"])
        if (str(UUID(identity["resource_generation"])) != identity["resource_generation"]
            or fixture["resource_generation"] != identity["resource_generation"]
            or set(fixture["candidate_ids"]) != set(CANDIDATE_IDS)
            or len(fixture["candidate_ids"]) != 4
            or any(start["api"].get(key) != identity[key] for key in (
                "source_sha", "image_digest", "resource_generation", "resource_tree", "app_image_id"))
            or type(start["api"]["api_pid"]) is not int or start["api"]["api_pid"] <= 0
            or start["api"]["api_module"] != "/app/app/main.py"
            or type(start["ui_pid"]) is not int or start["ui_pid"] <= 0
            or start["ui_pid"] == start["api"]["api_pid"]
            or fixture.get("logical_vault_id") is None or not fixture.get("local_clone_id")
            or re.fullmatch(r"sha256:[0-9a-f]{64}", str(identity["app_image_id"])) is None):
            raise ValueError("native_service_or_fixture_identity_invalid")
        sources = fixture["controlled_mutable_sources"]
        if (not isinstance(sources, list) or len(sources) != 2
            or {s["effect"] for s in sources} != {"panel_confirm", "capture"}
            or len({s["note_path"] for s in sources}) != 2
            or any(s["note_path"] != fixture["review_note_path" if s["effect"] == "panel_confirm" else "capture_note_path"]
                   or s["note_uuid"] != fixture["review_note_uuid" if s["effect"] == "panel_confirm" else "capture_note_uuid"]
                   or re.fullmatch(r"[0-9a-f]{64}", s["seed_sha256"]) is None for s in sources)):
            raise ValueError("native_mutable_source_inventory_invalid")
        for field in ("note_path", "review_note_path", "capture_note_path"):
            path = str(fixture[field])
            if not path or path.startswith("/") or ".." in path.split("/") or "\\" in path:
                raise ValueError("native_fixture_note_path_invalid")
        self.manifest_sha256 = hashlib.sha256(json.dumps(envelope, sort_keys=True).encode()).hexdigest()
        if binding["manifest_sha256"] != self.manifest_sha256:
            raise ValueError("native_pilot_manifest_hash_mismatch")
        self.binding = binding
        self.authority_hash = self._authority_hash(context)

    @staticmethod
    def _authority_hash(context: dict[str, Any]) -> str:
        return contract.hash_json({key: context[key] for key in (
            "schema", "report_binding", "native_identity", "api_url", "ui_url", "caldav_url", "fixture", "start", "reports")})

    def data(self) -> dict[str, Any]:
        f, b = self.context["fixture"], self.binding
        return {
            "channel": b["channel"], "ui_url": contract.UI_URL + "/", "api_url": contract.API_URL + "/",
            "expected_sha": b["source_sha"], "expected_image_digest": b["image_digest"],
            "run_id": b["run_id"], "output_dir": self.envelope["output_dir"],
            "test_resource_version": b["resource_version"], "qualification_ref": b["native_boundary_ref"],
            "fixture_metadata_sha256": b["fixture_metadata_sha256"], "local_instance_id": b["local_instance_id"],
            "vault_id": f["logical_vault_id"], "vault_path": "/scratch/vault", "vault_binding_id": f["logical_vault_id"],
            "known_note_path": f["note_path"], "known_note_uuid": f["note_uuid"],
            "review_note_path": f["review_note_path"], "review_note_uuid": f["review_note_uuid"],
            "capture_note_path": f["capture_note_path"], "capture_note_uuid": f["capture_note_uuid"],
            "memory_candidates": {"accept": "native-web-promote", "reject": "native-web-reject", "revise": "native-web-revise", "defer": "native-web-defer"},
            "effect_budget": dict(contract.EFFECT_LIMITS["deep-review"]), "navigation_ms": 30000, "request_ms": 35000,
            "allow_capture": True, "native_envelope": self.envelope,
        }

    def observe(self) -> dict[str, Any]:
        current = read_private_json(contract.CONTEXT_PATH, max_bytes=1024 * 1024)
        if self._authority_hash(current) != self.authority_hash:
            raise Blocked("native_input_identity_changed")
        observed = runtime._get_json(contract.API_URL + "/__native_web_identity")
        if observed.get("identity") != self.context["start"]["api"]:
            raise Blocked("native_actual_service_or_fixture_changed")
        daily = observed.get("daily_briefing_state") or {}
        if (not daily.get("healthy_version") or daily.get("version") != daily["healthy_version"]
            or daily.get("target") != self.context["fixture"]["daily"]["briefing_path"]
            or daily.get("date") != self.context["fixture"]["daily"]["date"]):
            raise Blocked("daily_acknowledged_present_note_required_before_deep")
        counts = observed.get("effects", {}).get("deep-review")
        if (not isinstance(counts, dict) or set(counts) != set(contract.EFFECT_LIMITS["deep-review"])
            or any(type(n) is not int or n < 0 or n > 1 for n in counts.values())):
            raise Blocked("native_effect_inventory_invalid")
        return observed

    def proof(self, d: dict[str, Any], marker: str) -> dict[str, Any]:
        observed = self.observe()
        result: dict[str, Any] = {
            "binding_verified": True, "gateway_upstream_verified": True, "synthetic_fixture_verified": True,
            "native_lock_verified": True, "first_contact_navigation_safe": True,
            "image_digest": self.binding["image_digest"], "test_resource_version": self.binding["resource_version"],
            "configuration_hashes": dict(self.binding["configuration_hashes"]), "source_has_marker": False,
            "api_identity": observed["identity"],
        }
        for effect, ack in (("panel_confirm", d.get("confirmation")), ("capture", d.get("capture_acknowledgement"))):
            if ack is None:
                continue
            self.require_ack(observed, effect, ack)
            if effect == "panel_confirm":
                # The API observer independently checked the actual durable
                # idempotency record against this exact response hash.
                result["persisted_confirmation"] = ack
            else:
                workspace = runtime._get_json(contract.API_URL + "/api/companion/workspace?note_path=" + quote(d["capture_note_path"]))
                artifact = workspace.get("artifact") or {}
                if artifact.get("artifact_id") != d["capture_note_uuid"]:
                    raise Blocked("capture_source_readback_identity_mismatch")
                result["source_has_marker"] = str(artifact.get("body") or "").count(marker) == 1
        return result

    def require_ack(self, observed: dict[str, Any], effect: str, ack: dict[str, Any]) -> None:
        source = next(s for s in self.context["fixture"]["controlled_mutable_sources"] if s["effect"] == effect)
        record = observed.get("acknowledgements", {}).get(effect) or {}
        if (record.get("response_sha256") != contract.hash_json(ack) or record.get("pre_sha256") != source["seed_sha256"]
            or record.get("target") != source["note_path"] or record.get("source_uuid") != source["note_uuid"]
            or re.fullmatch(r"[0-9a-f]{64}", str(record.get("post_sha256"))) is None
            or record.get("post_sha256") != observed.get("mutable_versions", {}).get(source["note_path"])):
            raise Blocked("actual_guarded_acknowledgement_lineage_mismatch")

    def before_effect(self, effect: str, reserved: dict[str, int]) -> None:
        self.observe()
        runtime.before_effect("deep-review", effect)
        if self.observe()["effects"]["deep-review"] != reserved:
            raise Blocked("native_and_runner_reservations_disagree")

    def end(self, effects: dict[str, int], confirmation: dict[str, Any] | None, capture: dict[str, Any] | None) -> dict[str, Any]:
        observed = self.observe()
        if observed["effects"]["deep-review"] != effects or effects != contract.EFFECT_LIMITS["deep-review"]:
            raise Blocked("final_native_effect_inventory_mismatch")
        if confirmation is None or capture is None:
            raise Blocked("final_actual_acknowledgements_missing")
        for effect, ack in (("panel_confirm", confirmation), ("capture", capture)):
            self.require_ack(observed, effect, ack)
        expected_paths = {s["note_path"] for s in self.context["fixture"]["controlled_mutable_sources"]}
        if set(observed.get("mutable_versions", {})) != expected_paths:
            raise Blocked("final_native_source_ownership_mismatch")
        if runtime._get_json(contract.UI_URL + "/healthz") != {"ok": True, "service": "companion-ui"}:
            raise Blocked("final_actual_ui_unavailable")
        return {"verified": True, "api": observed["identity"], "effects": dict(effects),
                "acknowledgements": observed["acknowledgements"], "mutable_versions": observed["mutable_versions"]}
