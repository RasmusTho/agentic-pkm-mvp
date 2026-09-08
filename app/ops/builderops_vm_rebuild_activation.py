"""Build and validate the normative VM-102 BuilderOps activation receipt.

The producer consumes only a redacted, caller-supplied live-operations bundle.
It never connects to Proxmox, Docker, SSH, the Builder Vault, or a health
endpoint.  A successful receipt proves the bounded activation gates named by
the contract; it is not a deployment, DevUI, owner-pilot, or merge receipt.
"""

from __future__ import annotations

import argparse
from collections.abc import Mapping
from datetime import datetime
import hashlib
import json
from pathlib import Path
import re
import sys
from typing import Any, Final

from jsonschema import Draft202012Validator, FormatChecker


__all__ = [
    "ActivationValidationError",
    "build_activation_receipt",
    "validate_activation_receipt",
]

RECEIPT_TYPE: Final = "builderops_vm_rebuild_activation.v1"
RECEIPT_VERSION: Final = 1
_ROOT = Path(__file__).resolve().parents[2]
_SCHEMA_PATH = (
    _ROOT / "config" / "platform" / "builderops_vm_rebuild_activation.v1.schema.json"
)
_TARGET_VM: Final[dict[str, Any]] = {"vmid": 102, "name": "builder-system"}
_REQUIRED_SOURCE_REFS: Final[frozenset[str]] = frozenset(
    {
        "repo:docs/BUILDEROPS_CONTROL_PLANE/README.md#vm-102-evidence-and-receipt-contract",
        "github:issue:5428",
    }
)
_SOURCE_REF = re.compile(
    r"^(?:"
    r"repo:docs/BUILDEROPS_CONTROL_PLANE/README\.md#vm-102-evidence-and-receipt-contract|"
    r"repo:scripts/deploy_builderops\.sh#builderops_assert_failure_domain|"
    r"github:issue:[1-9][0-9]*|"
    r"github:pr:[1-9][0-9]*|"
    r"github:commit:[a-f0-9]{40,64}|"
    r"operator:sha256:[a-f0-9]{64}|"
    r"receipt:[a-z0-9_.-]+:[a-f0-9]{64}"
    r")$"
)
_SHA256_DIGEST = re.compile(r"^sha256:[a-f0-9]{64}$")
_SOURCE_SHA = re.compile(r"^[a-f0-9]{40}$")
_ENGINE_ID = re.compile(r"^[a-f0-9-]{36}$")
_SSH_FINGERPRINT = re.compile(r"^ssh-ed25519:SHA256:[A-Za-z0-9+/=]+$")
_RFC3339 = re.compile(
    r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?:\.\d+)?(?:Z|[+-]\d{2}:\d{2})$"
)
_SECRET_KEY = re.compile(
    r"(?:api[_-]?key|authorization|credential|password|private[_-]?key|secret|token)",
    re.IGNORECASE,
)
_SECRET_VALUE = re.compile(
    r"(?:"
    r"bearer\s+|"
    r"gh[pousr]_[A-Za-z0-9_]+|"
    r"github_pat_[A-Za-z0-9_]+|"
    r"-----BEGIN [A-Z ]+PRIVATE KEY-----|"
    r"[A-Za-z][A-Za-z0-9+.-]*://[^\s@]+@|"
    r"(?:password|passwd|pwd|secret|token|api[_-]?key)\s*=\s*(?!\[REDACTED\])\S+"
    r")",
    re.IGNORECASE,
)
_EVIDENCE_KEYS: Final[frozenset[str]] = frozenset(
    {
        "receipt_type",
        "receipt_version",
        "target_vm",
        "observed_at",
        "source_refs",
        "activation_mode",
        "candidate_identity",
        "host_identity",
        "dedicated_engine",
        "product_engine",
        "migration",
        "fencing",
        "no_dual_writer",
        "readiness",
        "secret_material",
        "gaps",
        "refusals",
        "claims",
    }
)
_CLAIMS: Final[dict[str, bool]] = {
    "activation_proven": True,
    "dedicated_engine_proven": True,
    "migration_proven": True,
    "fencing_proven": True,
    "no_dual_writer_proven": True,
    "readiness_proven": True,
}


class ActivationValidationError(ValueError):
    """Raised when activation evidence or a receipt fails closed."""


def _canonical(value: Any) -> bytes:
    return json.dumps(
        value, ensure_ascii=False, separators=(",", ":"), sort_keys=True
    ).encode("utf-8")


def _digest(value: Any) -> str:
    return hashlib.sha256(_canonical(value)).hexdigest()


def _plain_copy(value: Any) -> Any:
    try:
        return json.loads(json.dumps(value, ensure_ascii=False))
    except (TypeError, ValueError) as exc:
        raise ActivationValidationError("activation evidence must be JSON-compatible") from exc


def _contains_secret(value: Any, *, key: str | None = None) -> bool:
    if key is not None and key != "secret_material" and _SECRET_KEY.search(key):
        return True
    if isinstance(value, str):
        return _SECRET_VALUE.search(value) is not None
    if isinstance(value, Mapping):
        return any(
            _contains_secret(child, key=str(child_key))
            for child_key, child in value.items()
        )
    if isinstance(value, list):
        return any(_contains_secret(child) for child in value)
    return False


def _exact_mapping(value: Any, keys: frozenset[str], label: str) -> Mapping[str, Any]:
    if not isinstance(value, Mapping) or set(value) != keys:
        raise ActivationValidationError(f"{label} fields are incomplete or contain extras")
    return value


def _validate_timestamp(value: Any) -> None:
    if not isinstance(value, str) or _RFC3339.fullmatch(value) is None:
        raise ActivationValidationError("observed_at must be an RFC 3339 timestamp")
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as exc:
        raise ActivationValidationError("observed_at must be an RFC 3339 timestamp") from exc
    if parsed.tzinfo is None:
        raise ActivationValidationError("observed_at must include a timezone")


def _validate_source_refs(value: Any) -> list[str]:
    if (
        not isinstance(value, list)
        or not value
        or any(not isinstance(item, str) or _SOURCE_REF.fullmatch(item) is None for item in value)
        or len(value) != len(set(value))
    ):
        raise ActivationValidationError("source_refs are invalid")
    if not _REQUIRED_SOURCE_REFS.issubset(value):
        raise ActivationValidationError("source_refs must retain the normative anchors")
    canonical = sorted(value)
    if value != canonical:
        raise ActivationValidationError("source_refs are not in canonical order")
    return canonical


def _validate_semantics(receipt: Mapping[str, Any]) -> None:
    if not isinstance(receipt, Mapping) or _contains_secret(receipt):
        raise ActivationValidationError("activation receipt is invalid")
    if set(receipt) != _EVIDENCE_KEYS | {"evidence_fingerprint"}:
        raise ActivationValidationError("activation receipt fields are incomplete or contain extras")
    if receipt.get("receipt_type") != RECEIPT_TYPE or receipt.get("receipt_version") != RECEIPT_VERSION:
        raise ActivationValidationError("activation receipt identity is invalid")
    if receipt.get("target_vm") != _TARGET_VM:
        raise ActivationValidationError("activation target VM identity is invalid")
    if receipt.get("activation_mode") not in {"fresh_rebuild", "existing_runtime_reconciled"}:
        raise ActivationValidationError("activation mode is invalid")
    if receipt.get("secret_material") != "absent":
        raise ActivationValidationError("activation receipt must declare secret_material=absent")
    _validate_timestamp(receipt.get("observed_at"))
    _validate_source_refs(receipt.get("source_refs"))

    candidate = _exact_mapping(
        receipt.get("candidate_identity"),
        frozenset({"source_sha", "control_plane_image_digest", "postgres_image_digest", "config_fingerprint"}),
        "candidate_identity",
    )
    if (
        not isinstance(candidate["source_sha"], str)
        or _SOURCE_SHA.fullmatch(candidate["source_sha"]) is None
        or candidate["source_sha"] == "0" * 40
        or not isinstance(candidate["control_plane_image_digest"], str)
        or _SHA256_DIGEST.fullmatch(candidate["control_plane_image_digest"]) is None
        or candidate["control_plane_image_digest"] == "sha256:" + "0" * 64
        or not isinstance(candidate["postgres_image_digest"], str)
        or _SHA256_DIGEST.fullmatch(candidate["postgres_image_digest"]) is None
        or candidate["postgres_image_digest"] == "sha256:" + "0" * 64
        or not isinstance(candidate["config_fingerprint"], str)
        or _SHA256_DIGEST.fullmatch(candidate["config_fingerprint"]) is None
        or candidate["config_fingerprint"] == "sha256:" + "0" * 64
    ):
        raise ActivationValidationError("candidate identity is not immutable")

    host = _exact_mapping(
        receipt.get("host_identity"),
        frozenset({"proxmox_node", "proxmox_vm_name", "guest_hostname", "guest_ip", "host_key_fingerprint", "vm_running", "qemu_agent_ready"}),
        "host_identity",
    )
    if (
        host.get("proxmox_node") != "tars"
        or host.get("proxmox_vm_name") != "bob-1"
        or host.get("guest_hostname") != "builder-system"
        or host.get("guest_ip") != "10.42.42.121"
        or not isinstance(host.get("host_key_fingerprint"), str)
        or _SSH_FINGERPRINT.fullmatch(host["host_key_fingerprint"]) is None
        or host.get("vm_running") is not True
        or host.get("qemu_agent_ready") is not True
    ):
        raise ActivationValidationError("VM-102 host identity or QGA gate is invalid")

    dedicated = _exact_mapping(
        receipt.get("dedicated_engine"),
        frozenset({"context", "socket", "engine_id", "project", "compose_config_fingerprint", "services", "healthy_services"}),
        "dedicated_engine",
    )
    if (
        dedicated.get("context") != "builderops"
        or dedicated.get("socket") != "unix:///run/docker-builderops.sock"
        or not isinstance(dedicated.get("engine_id"), str)
        or _ENGINE_ID.fullmatch(dedicated["engine_id"]) is None
        or dedicated.get("project") != "builderops-control-plane"
        or not isinstance(dedicated.get("compose_config_fingerprint"), str)
        or _SHA256_DIGEST.fullmatch(dedicated["compose_config_fingerprint"]) is None
        or dedicated.get("services") != ["api", "db", "migrate", "worker"]
        or dedicated.get("healthy_services") != ["api", "db", "worker"]
    ):
        raise ActivationValidationError("dedicated BuilderOps engine evidence is invalid")

    product = _exact_mapping(
        receipt.get("product_engine"),
        frozenset({"context", "socket", "engine_id", "projects", "duplicate_observed_before_quarantine"}),
        "product_engine",
    )
    if (
        product.get("context") != "default"
        or product.get("socket") != "unix:///var/run/docker.sock"
        or not isinstance(product.get("engine_id"), str)
        or _ENGINE_ID.fullmatch(product["engine_id"]) is None
        or product["engine_id"] == dedicated["engine_id"]
        or product.get("projects") != []
        or product.get("duplicate_observed_before_quarantine") is not True
    ):
        raise ActivationValidationError("Product engine must be distinct and empty after quarantine")

    migration = _exact_mapping(
        receipt.get("migration"),
        frozenset({"completed", "schema_version", "authority_epoch", "classification", "rollback_data_rewind"}),
        "migration",
    )
    if (
        migration.get("completed") is not True
        or type(migration.get("schema_version")) is not int
        or migration["schema_version"] < 1
        or type(migration.get("authority_epoch")) is not int
        or migration["authority_epoch"] < 1
        or migration.get("classification") != "forward_only_no_data_rewind"
        or migration.get("rollback_data_rewind") != "forbidden"
    ):
        raise ActivationValidationError("migration gate is invalid")

    fencing = _exact_mapping(
        receipt.get("fencing"),
        frozenset({"proven", "engine_service", "engine_service_enabled", "engine_service_restart", "control_plane_service", "control_plane_service_enabled", "forwarder_service", "forwarder_service_enabled", "post_reboot_verified"}),
        "fencing",
    )
    if (
        fencing.get("proven") is not True
        or fencing.get("engine_service") != "docker-builderops.service"
        or fencing.get("engine_service_enabled") is not True
        or fencing.get("engine_service_restart") != "always"
        or fencing.get("control_plane_service") != "builderops-control-plane.service"
        or fencing.get("control_plane_service_enabled") is not True
        or fencing.get("forwarder_service") != "builderops-loopback-forwarder.service"
        or fencing.get("forwarder_service_enabled") is not True
        or fencing.get("post_reboot_verified") is not True
    ):
        raise ActivationValidationError("fencing or reboot qualification is invalid")

    dual_writer = _exact_mapping(
        receipt.get("no_dual_writer"),
        frozenset({"proven", "pre_quarantine_duplicate_project", "quarantine_action", "post_quarantine_product_projects", "volume_removal"}),
        "no_dual_writer",
    )
    if (
        dual_writer.get("proven") is not True
        or dual_writer.get("pre_quarantine_duplicate_project") is not True
        or dual_writer.get("quarantine_action") != "default_engine_project_down_without_volume_removal"
        or dual_writer.get("post_quarantine_product_projects") != []
        or dual_writer.get("volume_removal") is not False
    ):
        raise ActivationValidationError("no-dual-writer evidence is invalid")

    readiness = _exact_mapping(
        receipt.get("readiness"),
        frozenset({"ready", "unauthenticated_status", "loopback_endpoint", "authentication", "private_ingress", "no_funnel"}),
        "readiness",
    )
    if (
        readiness.get("ready") is not True
        or readiness.get("unauthenticated_status") != 401
        or readiness.get("loopback_endpoint") != "127.0.0.1:18100"
        or readiness.get("authentication") != "scoped-bearer-over-loopback"
        or readiness.get("private_ingress") != "tailscale-serve-https-loopback-no-funnel"
        or readiness.get("no_funnel") is not True
    ):
        raise ActivationValidationError("readiness or private-ingress evidence is invalid")

    if receipt.get("gaps") != [] or receipt.get("refusals") != []:
        raise ActivationValidationError("successful activation cannot hide gaps or refusals")
    if receipt.get("claims") != _CLAIMS:
        raise ActivationValidationError("activation receipt claims are invalid")
    unsigned = {key: value for key, value in receipt.items() if key != "evidence_fingerprint"}
    if receipt.get("evidence_fingerprint") != _digest(unsigned):
        raise ActivationValidationError("activation evidence fingerprint mismatch")


def validate_activation_receipt(receipt: Mapping[str, Any]) -> None:
    """Fail closed unless *receipt* satisfies schema and semantic bindings."""

    try:
        Draft202012Validator(
            json.loads(_SCHEMA_PATH.read_text(encoding="utf-8")),
            format_checker=FormatChecker(),
        ).validate(receipt)
        _validate_semantics(receipt)
    except ActivationValidationError:
        raise
    except Exception as exc:
        raise ActivationValidationError("activation receipt is invalid") from exc


def build_activation_receipt(evidence: Mapping[str, Any]) -> dict[str, Any]:
    """Build a deterministic activation receipt from explicit redacted evidence."""

    if not isinstance(evidence, Mapping) or _contains_secret(evidence):
        raise ActivationValidationError("activation evidence is invalid")
    plain = _plain_copy(evidence)
    if not isinstance(plain, dict) or set(plain) != _EVIDENCE_KEYS:
        raise ActivationValidationError("activation evidence fields are incomplete or contain extras")
    receipt = {**plain, "source_refs": _validate_source_refs(plain.get("source_refs"))}
    receipt["evidence_fingerprint"] = _digest(receipt)
    validate_activation_receipt(receipt)
    return receipt


def _read_evidence(path: Path) -> Mapping[str, Any]:
    loaded = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(loaded, Mapping):
        raise ActivationValidationError("activation evidence must be an object")
    return loaded


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description=(
            "Build a fail-closed BuilderOps VM-102 activation receipt from "
            "operator-supplied JSON only; no host access is performed."
        )
    )
    parser.add_argument("--evidence", type=Path, required=True)
    args = parser.parse_args(argv)
    try:
        receipt = build_activation_receipt(_read_evidence(args.evidence))
    except (ActivationValidationError, OSError, json.JSONDecodeError, TypeError, ValueError):
        print("activation evidence refused", file=sys.stderr)
        return 2
    print(json.dumps(receipt, ensure_ascii=False, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
