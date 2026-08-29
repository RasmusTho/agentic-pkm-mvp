"""Build and validate a VM-102 inventory receipt from caller-supplied evidence.

This pure boundary performs no host access, discovery, qualification, activation,
deployment, or network operation. It emits only an inventory-completeness receipt;
all live/runtime claims remain explicitly false.
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
    "COMPONENT_IDS",
    "InventoryValidationError",
    "build_component_inventory_receipt",
    "validate_component_inventory_receipt",
]

RECEIPT_TYPE: Final = "devsystem_vm102_component_inventory.v1"
RECEIPT_VERSION: Final = 1
_ROOT = Path(__file__).resolve().parents[2]
_SCHEMA_PATH = (
    _ROOT
    / "config"
    / "platform"
    / "devsystem_vm102_component_inventory.v1.schema.json"
)

COMPONENT_IDS: Final[tuple[str, ...]] = (
    "devui_projection",
    "builderops_control_plane",
    "builderops_cockpit",
    "dispatcher_signboard",
    "ddo",
    "ckm_kvasir",
    "focus_conversation_port",
    "soi_evidence",
    "github_git_ci_delivery",
    "model_service",
    "tars_proxmox_control",
    "product_runtime",
)

_PLACEMENT_BY_COMPONENT: Final[dict[str, str]] = {
    "devui_projection": "vm102_resident_target",
    "builderops_control_plane": "vm102_resident_target",
    "builderops_cockpit": "vm102_resident_target",
    "dispatcher_signboard": "vm102_resident_target",
    "ddo": "vm102_resident_target",
    "ckm_kvasir": "vm102_resident_target",
    "focus_conversation_port": "vm102_resident_target",
    "soi_evidence": "external_dependency",
    "github_git_ci_delivery": "external_dependency",
    "model_service": "external_dependency",
    "tars_proxmox_control": "external_dependency",
    "product_runtime": "intentionally_non_runtime",
}
_ALLOWED_STATES_BY_COMPONENT: Final[dict[str, frozenset[str]]] = {
    component_id: frozenset({"gap", "unknown"}) for component_id in COMPONENT_IDS
}
_ALLOWED_STATES_BY_COMPONENT.update(
    {
        "github_git_ci_delivery": frozenset({"external"}),
        "product_runtime": frozenset({"excluded"}),
    }
)
_EVIDENCE_FIELDS: Final[tuple[str, ...]] = (
    "service_or_project",
    "source_identity",
    "ingress_auth",
    "health_version",
    "deployment_lifecycle",
    "migration_rollback",
)
_EVIDENCE_KEYS: Final[frozenset[str]] = frozenset(
    {
        "receipt_type",
        "receipt_version",
        "target_vm",
        "observed_at",
        "source_refs",
        "components",
        "secret_material",
        "gaps",
        "refusals",
        "claims",
    }
)
_REQUIRED_REFUSALS: Final[frozenset[str]] = frozenset(
    {
        "activation_not_proven",
        "deployment_not_proven",
        "health_not_proven",
        "qualification_not_proven",
        "residency_not_proven",
        "rollback_not_proven",
    }
)
_CLAIMS: Final[dict[str, bool]] = {
    "inventory_complete": True,
    "residency_proven": False,
    "qualification_proven": False,
    "activation_proven": False,
    "deployment_proven": False,
    "health_proven": False,
    "rollback_proven": False,
}
_SOURCE_REF = re.compile(
    r"^(?:repo|github|receipt|operator):[A-Za-z0-9][A-Za-z0-9._/#:-]*$"
)
_OBSERVED_AT = re.compile(
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
    r"pve[ta]=|"
    r"-----BEGIN [A-Z ]+PRIVATE KEY-----|"
    r"[A-Za-z][A-Za-z0-9+.-]*://[^\s@]+@|"
    r"(?:password|passwd|pwd|secret|token|api[_-]?key)\s*=\s*\S+"
    r")",
    re.IGNORECASE,
)


class InventoryValidationError(ValueError):
    """Raised when inventory evidence or a receipt fails closed."""


def _canonical_bytes(value: Any) -> bytes:
    return json.dumps(
        value,
        ensure_ascii=False,
        separators=(",", ":"),
        sort_keys=True,
    ).encode("utf-8")


def _digest(value: Any) -> str:
    return hashlib.sha256(_canonical_bytes(value)).hexdigest()


def _plain_copy(value: Any) -> Any:
    try:
        return json.loads(json.dumps(value, ensure_ascii=False))
    except (TypeError, ValueError) as exc:
        raise InventoryValidationError("inventory evidence must be JSON-compatible") from exc


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


def _validate_observed_at(value: Any) -> None:
    if not isinstance(value, str) or _OBSERVED_AT.fullmatch(value) is None:
        raise InventoryValidationError("observed_at must be an RFC 3339 timestamp")
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as exc:
        raise InventoryValidationError("observed_at must be an RFC 3339 timestamp") from exc
    if parsed.tzinfo is None:
        raise InventoryValidationError("observed_at must include a timezone")


def _validate_source_refs(source_refs: Any) -> list[str]:
    if not isinstance(source_refs, list) or not source_refs:
        raise InventoryValidationError("source_refs must be a non-empty list")
    if any(
        not isinstance(source_ref, str)
        or _SOURCE_REF.fullmatch(source_ref) is None
        for source_ref in source_refs
    ):
        raise InventoryValidationError("source_refs contain an invalid reference")
    if len(source_refs) != len(set(source_refs)):
        raise InventoryValidationError("source_refs must be unique")
    return sorted(source_refs)


def _canonical_components(components: Any, source_refs: list[str]) -> list[dict[str, Any]]:
    if not isinstance(components, list):
        raise InventoryValidationError("components must be a list")
    rows: dict[str, dict[str, Any]] = {}
    for raw_row in components:
        if not isinstance(raw_row, Mapping):
            raise InventoryValidationError("component rows must be objects")
        row = _plain_copy(raw_row)
        component_id = row.get("component_id")
        if not isinstance(component_id, str) or component_id not in COMPONENT_IDS:
            raise InventoryValidationError("component_id is not normative")
        if component_id in rows:
            raise InventoryValidationError("component_id must be unique")
        rows[component_id] = row
    if set(rows) != set(COMPONENT_IDS):
        raise InventoryValidationError("all normative component rows are required")

    canonical: list[dict[str, Any]] = []
    for component_id in COMPONENT_IDS:
        row = rows[component_id]
        if row.get("placement_class") != _PLACEMENT_BY_COMPONENT[component_id]:
            raise InventoryValidationError("component placement class is invalid")
        state = row.get("reconciliation_state")
        if state not in _ALLOWED_STATES_BY_COMPONENT[component_id]:
            raise InventoryValidationError("component reconciliation state is invalid")
        if not isinstance(row.get("owner"), str) or not row["owner"].strip():
            raise InventoryValidationError("component owner is required")
        for field in _EVIDENCE_FIELDS:
            value = row.get(field)
            if not isinstance(value, str) or not value.startswith(f"{state}:"):
                raise InventoryValidationError(
                    "component evidence must preserve its reconciliation state"
                )
        evidence_refs = row.get("evidence_refs")
        if (
            not isinstance(evidence_refs, list)
            or not evidence_refs
            or any(
                not isinstance(reference, str) or reference not in source_refs
                for reference in evidence_refs
            )
            or len(evidence_refs) != len(set(evidence_refs))
        ):
            raise InventoryValidationError(
                "component evidence_refs must be unique declared source_refs"
            )
        row["evidence_refs"] = sorted(evidence_refs)
        canonical.append(row)
    return canonical


def _canonical_gaps(gaps: Any, components: list[dict[str, Any]]) -> list[dict[str, str]]:
    if not isinstance(gaps, list):
        raise InventoryValidationError("gaps must be a list")
    gap_rows: dict[str, dict[str, str]] = {}
    for raw_gap in gaps:
        if not isinstance(raw_gap, Mapping):
            raise InventoryValidationError("gap rows must be objects")
        component_id = raw_gap.get("component_id")
        code = raw_gap.get("code")
        detail = raw_gap.get("detail")
        if (
            not isinstance(component_id, str)
            or component_id not in COMPONENT_IDS
            or not isinstance(code, str)
            or re.fullmatch(r"[a-z0-9]+(?:_[a-z0-9]+)*", code) is None
            or not isinstance(detail, str)
            or not detail.strip()
        ):
            raise InventoryValidationError("gap row is invalid")
        if component_id in gap_rows:
            raise InventoryValidationError("gap component_id must be unique")
        gap_rows[component_id] = {
            "component_id": component_id,
            "code": code,
            "detail": detail,
        }
    required_gap_ids = {
        row["component_id"]
        for row in components
        if row["reconciliation_state"] in {"gap", "unknown"}
    }
    if set(gap_rows) != required_gap_ids:
        raise InventoryValidationError("gaps must exactly cover gap and unknown components")
    return [gap_rows[component_id] for component_id in COMPONENT_IDS if component_id in gap_rows]


def _canonical_refusals(refusals: Any) -> list[str]:
    if (
        not isinstance(refusals, list)
        or any(
            not isinstance(refusal, str)
            or re.fullmatch(r"[a-z0-9]+(?:_[a-z0-9]+)*", refusal) is None
            for refusal in refusals
        )
        or len(refusals) != len(set(refusals))
        or not _REQUIRED_REFUSALS.issubset(refusals)
    ):
        raise InventoryValidationError("refusals must retain all non-claim gates")
    return sorted(refusals)


def _load_schema() -> Mapping[str, Any]:
    loaded = json.loads(_SCHEMA_PATH.read_text(encoding="utf-8"))
    if not isinstance(loaded, Mapping):
        raise InventoryValidationError("inventory schema is invalid")
    return loaded


def _validate_semantics(receipt: Mapping[str, Any]) -> None:
    source_refs = _validate_source_refs(receipt.get("source_refs"))
    _validate_observed_at(receipt.get("observed_at"))
    components = _canonical_components(receipt.get("components"), source_refs)
    gaps = _canonical_gaps(receipt.get("gaps"), components)
    refusals = _canonical_refusals(receipt.get("refusals"))
    if receipt.get("claims") != _CLAIMS:
        raise InventoryValidationError("inventory receipt contains a prohibited claim")
    if components != receipt.get("components"):
        raise InventoryValidationError("components are not in canonical order")
    if gaps != receipt.get("gaps"):
        raise InventoryValidationError("gaps are not in canonical order")
    if refusals != receipt.get("refusals"):
        raise InventoryValidationError("refusals are not in canonical order")
    if source_refs != receipt.get("source_refs"):
        raise InventoryValidationError("source_refs are not in canonical order")
    if receipt.get("component_inventory_digest") != _digest(components):
        raise InventoryValidationError("component inventory digest mismatch")
    expected_fingerprints = {
        row["component_id"]: _digest(row) for row in components
    }
    if receipt.get("evidence_fingerprints") != expected_fingerprints:
        raise InventoryValidationError("component evidence fingerprint mismatch")
    unsigned = {
        key: value for key, value in receipt.items() if key != "evidence_fingerprint"
    }
    if receipt.get("evidence_fingerprint") != _digest(unsigned):
        raise InventoryValidationError("receipt evidence fingerprint mismatch")


def validate_component_inventory_receipt(receipt: Mapping[str, Any]) -> None:
    """Fail closed unless *receipt* satisfies schema and semantic bindings."""

    if not isinstance(receipt, Mapping) or _contains_secret(receipt):
        raise InventoryValidationError("inventory receipt is invalid")
    try:
        Draft202012Validator(
            _load_schema(),
            format_checker=FormatChecker(),
        ).validate(receipt)
        _validate_semantics(receipt)
    except InventoryValidationError:
        raise
    except Exception as exc:
        raise InventoryValidationError("inventory receipt is invalid") from exc


def build_component_inventory_receipt(evidence: Mapping[str, Any]) -> dict[str, Any]:
    """Build a deterministic receipt solely from explicit caller evidence."""

    if not isinstance(evidence, Mapping) or _contains_secret(evidence):
        raise InventoryValidationError("inventory evidence is invalid")
    plain = _plain_copy(evidence)
    if not isinstance(plain, dict) or set(plain) != _EVIDENCE_KEYS:
        raise InventoryValidationError("inventory evidence fields are incomplete")
    if plain.get("receipt_type") != RECEIPT_TYPE or plain.get("receipt_version") != RECEIPT_VERSION:
        raise InventoryValidationError("inventory receipt identity is invalid")
    if plain.get("target_vm") != {"vmid": 102, "name": "builder-system"}:
        raise InventoryValidationError("inventory target VM identity is invalid")
    if plain.get("secret_material") != "absent":
        raise InventoryValidationError("secret-bearing inventory evidence is refused")
    _validate_observed_at(plain.get("observed_at"))
    source_refs = _validate_source_refs(plain.get("source_refs"))
    components = _canonical_components(plain.get("components"), source_refs)
    gaps = _canonical_gaps(plain.get("gaps"), components)
    refusals = _canonical_refusals(plain.get("refusals"))
    if plain.get("claims") != _CLAIMS:
        raise InventoryValidationError("inventory evidence contains a prohibited claim")

    receipt = {
        **plain,
        "source_refs": source_refs,
        "components": components,
        "gaps": gaps,
        "refusals": refusals,
        "component_inventory_digest": _digest(components),
        "evidence_fingerprints": {
            row["component_id"]: _digest(row) for row in components
        },
    }
    receipt["evidence_fingerprint"] = _digest(receipt)
    validate_component_inventory_receipt(receipt)
    return receipt


def _read_evidence(path: Path) -> Mapping[str, Any]:
    loaded = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(loaded, Mapping):
        raise InventoryValidationError("inventory evidence must be an object")
    return loaded


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description=(
            "Build a fail-closed Dev System VM-102 component inventory receipt "
            "from operator-supplied JSON only; no host access is performed."
        )
    )
    parser.add_argument(
        "--evidence",
        type=Path,
        required=True,
        help="caller-supplied JSON evidence bundle",
    )
    args = parser.parse_args(argv)
    try:
        receipt = build_component_inventory_receipt(_read_evidence(args.evidence))
    except (InventoryValidationError, OSError, json.JSONDecodeError, TypeError, ValueError):
        print("inventory evidence refused", file=sys.stderr)
        return 2
    rendered = json.dumps(receipt, ensure_ascii=False, indent=2, sort_keys=True)
    print(rendered)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
