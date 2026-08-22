"""Fail-closed, repo-side TARS qualification evidence validation.

This module deliberately has no SSH, Proxmox API, token, or subprocess integration.
It produces a candidate-policy receipt only; a governed live-operations receipt is
required before TARS can ever be described as qualified.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Mapping

from jsonschema import Draft202012Validator, FormatChecker


QUALIFICATION_SCHEMA_VERSION = "tars_host_qualification.v1"
EVIDENCE_BUNDLE_SCHEMA_VERSION = "tars_operator_evidence_bundle.v1"
POLICY_VERSION = "tars-builder-system-baseline.v1"
MAX_EVIDENCE_AGE = timedelta(hours=24)
_ROOT = Path(__file__).resolve().parents[2]
_SECRET_KEY = re.compile(r"(?:api[_-]?key|authorization|credential|password|private[_-]?key|secret|token)", re.I)
_SECRET_VALUE = re.compile(r"(?:bearer\s+|gh[pousr]_[A-Za-z0-9_]|pve[ta]=|-----BEGIN [A-Z ]+PRIVATE KEY-----)", re.I)
_OPAQUE_CREDENTIAL_KEYS = frozenset({"database_url", "dsn", "passwd", "session_cookie"})
_FINGERPRINT = re.compile(r"^[a-f0-9]{64}$")

# The baseline is intentionally limited to builder-system.  It has no GPU or
# test-tailnet vector; neither is a prerequisite for this qualification slice.
DEFAULT_POLICY: dict[str, Any] = {
    "policy_version": POLICY_VERSION,
    "max_evidence_age_hours": 24,
    "host": {"management_vlan": 11, "guest_vlan": 42, "bridge": "vmbr0", "minimum_free_gib": 16},
    "vm_102": {
        "vmid": 102,
        "name": "builder-system",
        "cores": 2,
        "memory_mib": 4096,
        "disk_gib": 60,
        "bridge": "vmbr0",
        "vlan_tag": 42,
        "network_scope": "guest-vlan-42",
    },
}


def _canonical(value: Any) -> bytes:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode("utf-8")


def _sha256(value: Any) -> str:
    return hashlib.sha256(_canonical(value)).hexdigest()


def _parse_time(value: object) -> datetime:
    if not isinstance(value, str):
        raise ValueError("evidence timestamp is missing or invalid")
    parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if parsed.tzinfo is None:
        raise ValueError("evidence timestamp must be timezone-aware")
    return parsed.astimezone(timezone.utc)


def _loads_schema(name: str) -> Mapping[str, Any]:
    return json.loads((_ROOT / "config" / "platform" / name).read_text(encoding="utf-8"))


def _key_is_secret(key: str) -> bool:
    normalized = key.lower().replace("-", "_")
    return (
        not normalized.endswith("_ref")
        and not normalized.endswith("_refs")
        and (normalized in _OPAQUE_CREDENTIAL_KEYS or _SECRET_KEY.search(normalized) is not None)
    )


def _contains_secret(value: Any, *, key: str | None = None) -> bool:
    if key is not None and _key_is_secret(key):
        if key.lower().replace("-", "_") in _OPAQUE_CREDENTIAL_KEYS:
            return True
        return value != "[REDACTED]"
    if isinstance(value, str):
        return value != "[REDACTED]" and _SECRET_VALUE.search(value) is not None
    if isinstance(value, Mapping):
        return any(_contains_secret(item, key=str(child_key)) for child_key, item in value.items())
    if isinstance(value, list):
        return any(_contains_secret(item) for item in value)
    return False


def _redact(value: Any, *, key: str | None = None) -> Any:
    if key is not None and _key_is_secret(key):
        return "[REDACTED]"
    if isinstance(value, str):
        return "[REDACTED]" if _SECRET_VALUE.search(value) else value
    if isinstance(value, Mapping):
        return {str(child_key): _redact(item, key=str(child_key)) for child_key, item in value.items()}
    if isinstance(value, list):
        return [_redact(item) for item in value]
    return value


def emit_redacted_evidence_bundle(raw_evidence: Mapping[str, Any]) -> dict[str, Any]:
    """Return a credential-free operator bundle with per-vector fingerprints.

    The caller may collect input through any approved read-only operator method.
    This function does not inspect a host and does not treat its output as live
    qualification evidence.
    """
    if not isinstance(raw_evidence, Mapping):
        raise ValueError("operator evidence must be an object")
    collected_at = raw_evidence.get("collected_at")
    _parse_time(collected_at)
    evidence = {key: _redact(raw_evidence.get(key)) for key in ("host", "vm_102", "builderops")}
    if any(not isinstance(value, Mapping) for value in evidence.values()):
        raise ValueError("operator evidence must include host, vm_102, and builderops objects")
    return {
        "schema_version": EVIDENCE_BUNDLE_SCHEMA_VERSION,
        "policy_version": POLICY_VERSION,
        "collected_at": collected_at,
        "evidence": evidence,
        "evidence_fingerprints": {key: _sha256(value) for key, value in evidence.items()},
    }


def _baseline_refusals(evidence: Mapping[str, Any]) -> list[str]:
    refusals: list[str] = []
    host = evidence.get("host")
    vm = evidence.get("vm_102")
    builderops = evidence.get("builderops")
    if not isinstance(host, Mapping) or not isinstance(vm, Mapping) or not isinstance(builderops, Mapping):
        return ["evidence must contain host, vm_102, and builderops objects"]

    for key in ("cpu_virtualization", "thermals_ok", "unattended_boot", "recovery_proven"):
        if host.get(key) is not True:
            refusals.append(f"host evidence requires {key}=true")
    nic_vlan = host.get("nic_vlan")
    if not isinstance(nic_vlan, Mapping) or any(nic_vlan.get(key) != expected for key, expected in {
        "management_vlan": DEFAULT_POLICY["host"]["management_vlan"],
        "guest_vlan": DEFAULT_POLICY["host"]["guest_vlan"],
        "bridge": DEFAULT_POLICY["host"]["bridge"],
    }.items()):
        refusals.append("host NIC/VLAN evidence does not match the approved private baseline")
    storage = host.get("storage")
    if not isinstance(storage, Mapping) or not isinstance(storage.get("free_gib"), (int, float)) or storage["free_gib"] < DEFAULT_POLICY["host"]["minimum_free_gib"]:
        refusals.append("host storage free space is below the approved threshold")
    listeners = host.get("listeners")
    if not isinstance(listeners, list) or not listeners or any(not isinstance(item, Mapping) or item.get("exposure") != "private" for item in listeners):
        refusals.append("host listener exposure is missing or not private")

    for key, expected in DEFAULT_POLICY["vm_102"].items():
        if vm.get(key) != expected:
            refusals.append(f"VM 102 baseline mismatch for {key}")
    for key in ("firewall_enabled", "onboot", "qemu_agent_enabled"):
        if vm.get(key) is not True:
            refusals.append(f"VM 102 requires {key}=true")

    builder_engine = builderops.get("builder_engine_id")
    product_engine = builderops.get("product_engine_id")
    if (
        not isinstance(builder_engine, str)
        or not builder_engine.strip()
        or not isinstance(product_engine, str)
        or not product_engine.strip()
        or builder_engine.strip() == product_engine.strip()
    ):
        refusals.append("VM 102 must not share the Product Docker engine")
    projects = builderops.get("compose_projects")
    if not isinstance(projects, list) or any(not isinstance(item, str) or item.startswith("pkm-") for item in projects):
        refusals.append("VM 102 must not run a Product Compose project")
    for key, description in {
        "prod_credential_refs": "prod credentials",
        "prod_vault_refs": "prod vault",
        "prod_network_identities": "prod network identity",
    }.items():
        if builderops.get(key) != []:
            refusals.append(f"VM 102 must not carry {description}")
    secret_refs = builderops.get("secret_refs")
    if not isinstance(secret_refs, list) or any(not isinstance(item, str) or not item or item == "[REDACTED]" for item in secret_refs):
        refusals.append("BuilderOps secret references must be non-secret references")
    return refusals


def evaluate_qualification(bundle: Mapping[str, Any], *, evaluated_at: datetime | None = None) -> dict[str, Any]:
    """Evaluate a redacted evidence bundle and always retain the live receipt gate."""
    now = (evaluated_at or datetime.now(timezone.utc)).astimezone(timezone.utc)
    refusals: list[str] = []
    fingerprints = {key: "0" * 64 for key in ("host", "vm_102", "builderops")}
    evidence: Mapping[str, Any] = {}
    try:
        Draft202012Validator(_loads_schema("tars_operator_evidence_bundle.v1.schema.json"), format_checker=FormatChecker()).validate(bundle)
        evidence = bundle["evidence"]
        fingerprints = bundle["evidence_fingerprints"]
        if _contains_secret(evidence):
            refusals.append("secret-bearing evidence is refused")
        collected_at = _parse_time(bundle["collected_at"])
        if collected_at > now + timedelta(minutes=5) or now - collected_at > MAX_EVIDENCE_AGE:
            refusals.append("evidence is stale or has an invalid future timestamp")
        for key in fingerprints:
            if not isinstance(fingerprints[key], str) or _FINGERPRINT.fullmatch(fingerprints[key]) is None or fingerprints[key] != _sha256(evidence[key]):
                refusals.append(f"evidence fingerprint is unverifiable for {key}")
        refusals.extend(_baseline_refusals(evidence))
    except Exception as exc:  # schema and parsing failures are a safe refusal, never a crash-to-pass.
        refusals.append(f"evidence bundle is invalid: {exc}")

    receipt = {
        "schema_version": QUALIFICATION_SCHEMA_VERSION,
        "policy_version": POLICY_VERSION,
        "evaluated_at": now.isoformat().replace("+00:00", "Z"),
        "evidence_fingerprints": fingerprints,
        "candidate_verdict": "fail" if refusals else "pass",
        "live_qualified": False,
        "live_qualification_reason": "requires a governed live operations receipt",
        "refusals": sorted(set(refusals)),
    }
    Draft202012Validator(_loads_schema("tars_host_qualification.v1.schema.json"), format_checker=FormatChecker()).validate(receipt)
    return receipt


def _read_json(path: Path) -> Mapping[str, Any]:
    loaded = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(loaded, Mapping):
        raise ValueError("JSON input must be an object")
    return loaded


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Create or evaluate a redacted TARS qualification bundle; no host access is performed.")
    parser.add_argument("--evidence", type=Path, required=True, help="operator-supplied JSON evidence")
    parser.add_argument("--receipt", type=Path, help="write the fail-closed candidate receipt to this path")
    parser.add_argument("--bundle", type=Path, help="write the redacted evidence bundle to this path")
    args = parser.parse_args(argv)
    bundle = emit_redacted_evidence_bundle(_read_json(args.evidence))
    receipt = evaluate_qualification(bundle)
    if args.bundle:
        args.bundle.write_text(json.dumps(bundle, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    rendered = json.dumps(receipt, indent=2, sort_keys=True)
    if args.receipt:
        args.receipt.write_text(rendered + "\n", encoding="utf-8")
    print(rendered)
    return 0 if receipt["candidate_verdict"] == "pass" else 2


if __name__ == "__main__":
    raise SystemExit(main())
