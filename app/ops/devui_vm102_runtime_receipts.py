"""Pure VM102 DevUI receipt producers over redacted caller-supplied evidence.

No host inspection, network access, deployment, service startup or receipt
persistence occurs here. Validation proves consistency of the supplied evidence;
the governed operator remains responsible for its authentic live collection.
"""

from __future__ import annotations

import argparse
from collections.abc import Mapping
from datetime import datetime, timedelta, timezone
import hashlib
import hmac
import json
from pathlib import Path
from typing import Any

from jsonschema import Draft202012Validator, FormatChecker

from app.ops.builderops_vm_rebuild_activation import _contains_secret, validate_activation_receipt
from app.ops.devsystem_vm102_component_inventory import validate_component_inventory_receipt


TYPES = {
    "qualification": "devui_vm102_runtime_qualification.v1",
    "deploy": "devsystem_vm102_deploy.v1",
    "health": "devsystem_vm102_health.v1",
}
VERDICTS = {"qualification": "qualified", "deploy": "deployed", "health": "healthy"}
ROOT = Path(__file__).resolve().parents[2]
ANCHOR = "repo:docs/BUILDEROPS_CONTROL_PLANE/README.md#vm-102-evidence-and-receipt-contract"
TARGET = {"vmid": 102, "name": "builder-system"}
_COMMON_EVIDENCE = {
    "observed_at",
    "candidate_identity",
    "topology",
    "runtime",
    "checks",
}


class ReceiptValidationError(ValueError):
    """Evidence cannot support a successful receipt; never echo caller data."""


def canonical_digest(value: Any) -> str:
    return hashlib.sha256(
        json.dumps(
            value, sort_keys=True, separators=(",", ":"), ensure_ascii=False, allow_nan=False
        ).encode()
    ).hexdigest()


def _time(value: Any, now: datetime) -> datetime:
    try:
        stamp = datetime.fromisoformat(value.replace("Z", "+00:00"))
        if stamp.tzinfo is None or not timedelta(0) <= now - stamp <= timedelta(hours=24):
            raise ValueError
        return stamp
    except (AttributeError, TypeError, ValueError) as exc:
        raise ReceiptValidationError(
            "evidence timestamp is invalid, stale or future-dated"
        ) from exc


def _ref(receipt: Mapping[str, Any]) -> str:
    return f"receipt:{receipt['receipt_type']}:{canonical_digest(receipt)}"


def _dependencies(
    kind: str, prerequisites: Mapping[str, Any], now: datetime
) -> tuple[Mapping[str, Any], list[str]]:
    try:
        inventory = prerequisites["inventory"]
        validate_component_inventory_receipt(inventory)
        _time(inventory["observed_at"], now)
        refs = [f"receipt:{inventory['receipt_type']}:{inventory['component_inventory_digest']}"]
        if kind in {"deploy", "health"}:
            activation = prerequisites["activation"]
            validate_activation_receipt(activation)
            _time(activation["observed_at"], now)
            if activation["component_inventory_digest"] != inventory["component_inventory_digest"]:
                raise ReceiptValidationError("activation inventory does not match")
            qualification = prerequisites["qualification"]
            validate_receipt(qualification, prerequisites, now=now)
            refs.extend((_ref(activation), _ref(qualification)))
        if kind == "health":
            deploy = prerequisites["deploy"]
            validate_receipt(deploy, prerequisites, now=now)
            refs.append(_ref(deploy))
        return inventory, refs
    except ReceiptValidationError:
        raise
    except Exception as exc:
        raise ReceiptValidationError("receipt prerequisite is absent or invalid") from exc


def _candidate(value: Mapping[str, Any]) -> None:
    for digest in value.values():
        raw = digest.removeprefix("sha256:")
        if set(raw) == {"0"}:
            raise ReceiptValidationError("placeholder identity is forbidden")
    if value["devui_image_digest"] != value["control_plane_image_digest"]:
        raise ReceiptValidationError("DevUI must use the attested Builder image")


def _shape_and_fingerprint(receipt: Mapping[str, Any], kind: str) -> None:
    if _contains_secret(receipt):
        raise ReceiptValidationError("secret-bearing receipt is forbidden")
    schema = json.loads((ROOT / "config/platform" / f"{TYPES[kind]}.schema.json").read_text())
    Draft202012Validator(schema, format_checker=FormatChecker()).validate(receipt)
    unsigned = {key: value for key, value in receipt.items() if key != "evidence_fingerprint"}
    if not hmac.compare_digest(receipt["evidence_fingerprint"], canonical_digest(unsigned)):
        raise ReceiptValidationError("receipt fingerprint does not match")


def _local_evidence(receipt: Mapping[str, Any], kind: str, captured: datetime) -> datetime:
    """Apply identical self-contained invariants to current and retained receipts."""
    _shape_and_fingerprint(receipt, kind)
    observed = _time(receipt["observed_at"], captured)
    rows = receipt["topology"]
    if len({row["component_id"] for row in rows}) != len(rows):
        raise ReceiptValidationError("duplicate component identity is forbidden")
    evidence_fields = _COMMON_EVIDENCE | (
        {"rollback_baseline_state", "previous_identity"} if kind == "deploy" else set()
    )
    if receipt["operator_evidence_digest"] != canonical_digest(
        {key: receipt[key] for key in evidence_fields}
    ):
        raise ReceiptValidationError("operator evidence digest does not match")
    if rows != sorted(rows, key=lambda row: row["component_id"]):
        raise ReceiptValidationError("component topology must be canonical")
    for row in rows:
        expected_proof = {
            key: value
            for key, value in row.items()
            if key not in {"evidence_digest", "source_identity_digest"}
        }
        proof = expected_proof
        if row["evidence_digest"] != canonical_digest(proof):
            raise ReceiptValidationError("component evidence digest or contents do not match")
        if row["source_identity_digest"] != canonical_digest(proof["source_identity"]):
            raise ReceiptValidationError("component source identity digest does not match")
        if _time(row["observed_at"], captured) > observed:
            raise ReceiptValidationError("receipt predates component evidence")
        expected = row
        placement = expected["placement_class"]
        if row["state"] != (
            "excluded"
            if placement == "intentionally_non_runtime"
            else "external"
            if placement == "external_dependency"
            else {"qualification": "prepared", "deploy": "deployed", "health": "healthy"}[kind]
        ):
            raise ReceiptValidationError("component evidence is incomplete")
        if row["deployment_owner"] != expected["owner"]:
            raise ReceiptValidationError("component deployment ownership does not match")
        placement = expected["placement_class"]
        if (
            row["ingress_auth"]
            != {
                "vm102_resident_target": "internal_authenticated",
                "external_dependency": "external_source_owned",
                "intentionally_non_runtime": "excluded",
            }[placement]
        ):
            raise ReceiptValidationError("component ingress does not match its boundary")
        if row["health_version"] != (
            "excluded"
            if placement == "intentionally_non_runtime"
            else "verified"
            if kind == "health"
            else "not_observed"
        ):
            raise ReceiptValidationError("component health/version evidence is missing")
        expected_migration = (
            "excluded"
            if placement == "intentionally_non_runtime"
            else "external_source_owned"
            if placement == "external_dependency"
            else "no_migration_restore_image_config"
            if row["component_id"] == "devui_projection"
            else "builderops_governed_no_data_rewind"
        )
        if row["migration_rollback"] != expected_migration:
            raise ReceiptValidationError("component migration/rollback boundary is invalid")
        if (
            row["component_id"] == "devui_projection"
            and row["service_or_project"] != "builderops-devui"
        ):
            raise ReceiptValidationError("DevUI project identity is unsupported")
        identity = row["source_identity"]
        if placement == "intentionally_non_runtime":
            if identity is not None:
                raise ReceiptValidationError("excluded runtime cannot claim source identity")
        elif not isinstance(identity, Mapping) or set(identity) != (
            {"source_sha", "image_digest", "config_fingerprint"}
            if placement == "vm102_resident_target"
            else {"source_ref", "version_digest"}
        ):
            raise ReceiptValidationError("component source identity is incomplete")
    candidate = receipt["candidate_identity"]
    _candidate(candidate)
    devui_row = next(row for row in rows if row["component_id"] == "devui_projection")
    if devui_row["source_identity"] != {
        "source_sha": candidate["source_sha"],
        "image_digest": candidate["devui_image_digest"],
        "config_fingerprint": candidate["devui_config_fingerprint"],
    }:
        raise ReceiptValidationError("DevUI topology must bind the exact immutable candidate")
    control_row = next(row for row in rows if row["component_id"] == "builderops_control_plane")
    if control_row["service_or_project"] != "builderops-control-plane":
        raise ReceiptValidationError("control-plane project identity is unsupported")
    if control_row["source_identity"] != {
        "source_sha": candidate["source_sha"],
        "image_digest": candidate["control_plane_image_digest"],
        "config_fingerprint": candidate["config_fingerprint"],
    }:
        raise ReceiptValidationError("control-plane topology must bind the activation candidate")

    if receipt["source_refs"] != sorted(receipt["source_refs"]) or (
        "operator:sha256:" + receipt["operator_evidence_digest"] not in receipt["source_refs"]
    ):
        raise ReceiptValidationError("operator source linkage is invalid")
    if kind == "deploy":
        previous = receipt["previous_identity"]
        if receipt["rollback_baseline_state"] == "no_baseline":
            if (
                previous is not None
                or receipt["rollback_baseline_refs"]
                or receipt["refusals"] != ["no_compatible_baseline"]
            ):
                raise ReceiptValidationError("first deployment cannot claim a rollback baseline")
        else:
            if (
                previous is None
                or len(receipt["rollback_baseline_refs"]) != 2
                or receipt["refusals"]
            ):
                raise ReceiptValidationError(
                    "available rollback identity or evidence is incomplete"
                )
            _candidate(previous)
            if not set(receipt["rollback_baseline_refs"]).issubset(receipt["source_refs"]):
                raise ReceiptValidationError("rollback baseline source linkage is incomplete")
    return observed


def _observations_after(
    receipt: Mapping[str, Any], predecessor: Mapping[str, Any], *, resident_only: bool = False
) -> None:
    lower = datetime.fromisoformat(predecessor["observed_at"].replace("Z", "+00:00"))
    for row in receipt["topology"]:
        if row["placement_class"] == "intentionally_non_runtime" or (
            resident_only and row["placement_class"] != "vm102_resident_target"
        ):
            continue
        if datetime.fromisoformat(row["observed_at"].replace("Z", "+00:00")) < lower:
            raise ReceiptValidationError("component observation predates its stage prerequisite")


def _stable_topology(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return [
        {
            key: value
            for key, value in row.items()
            if key not in {"evidence_digest", "observed_at", "state", "health_version"}
        }
        for row in rows
    ]


def _rollback_refs(receipt: Mapping[str, Any], prerequisites: Mapping[str, Any]) -> list[str]:
    baseline = prerequisites.get("rollback_baseline")
    if receipt["rollback_baseline_state"] == "no_baseline":
        if baseline is not None or receipt["previous_identity"] is not None:
            raise ReceiptValidationError("first deployment cannot claim a rollback baseline")
        return []
    if not isinstance(baseline, Mapping) or set(baseline) != {"deploy", "health", "compatibility"}:
        raise ReceiptValidationError("available baseline requires prior deploy and health evidence")
    if baseline["compatibility"] != "verified_no_data_rewind":
        raise ReceiptValidationError("rollback compatibility has not been verified")
    deploy, health = baseline["deploy"], baseline["health"]
    # Historical receipts are custody evidence, not a recursive ledger. Their original
    # dependency bundles remain with the operator; current compatibility is required.
    for kind, prior in (("deploy", deploy), ("health", health)):
        _local_evidence(
            prior, kind, datetime.fromisoformat(prior["observed_at"].replace("Z", "+00:00"))
        )
        if prior["candidate_identity"] != receipt["previous_identity"]:
            raise ReceiptValidationError("rollback baseline candidate does not match")
        _candidate(prior["candidate_identity"])
        if prior["runtime"] != receipt["runtime"]:
            raise ReceiptValidationError("rollback baseline runtime is incompatible")
        if [
            (row["component_id"], row["owner"], row["placement_class"]) for row in prior["topology"]
        ] != [
            (row["component_id"], row["owner"], row["placement_class"])
            for row in receipt["topology"]
        ]:
            raise ReceiptValidationError("rollback baseline topology is incompatible")
    if _ref(deploy) not in health["source_refs"]:
        raise ReceiptValidationError("known-good health must bind the previous deployment")
    if _stable_topology(deploy["topology"]) != _stable_topology(health["topology"]):
        raise ReceiptValidationError("rollback baseline topology identities do not match")
    # Deliberately no age limit for retained known-good history; chronology still holds.
    stamps = [
        datetime.fromisoformat(item["observed_at"].replace("Z", "+00:00"))
        for item in (deploy, health, receipt)
    ]
    if any(stamp.tzinfo is None for stamp in stamps) or not stamps[0] <= stamps[1] <= stamps[2]:
        raise ReceiptValidationError("rollback baseline chronology is invalid")
    _observations_after(health, deploy)
    return sorted([_ref(deploy), _ref(health)])


def validate_receipt(
    receipt: Mapping[str, Any], prerequisites: Mapping[str, Any], *, now: datetime | None = None
) -> None:
    """Verify closed shape, fingerprint, prerequisite lineage and live identities."""
    try:
        captured = now or datetime.now(timezone.utc)
        kind = next(key for key, value in TYPES.items() if value == receipt.get("receipt_type"))
        observed = _local_evidence(receipt, kind, captured)
        inventory, refs = _dependencies(kind, prerequisites, captured)
        if receipt["component_inventory_digest"] != inventory["component_inventory_digest"]:
            raise ReceiptValidationError("receipt inventory does not match")
        if kind == "deploy":
            baseline_refs = _rollback_refs(receipt, prerequisites)
            if receipt["rollback_baseline_refs"] != baseline_refs:
                raise ReceiptValidationError("rollback baseline references do not match")
            refs.extend(baseline_refs)
        expected_refs = sorted(
            [ANCHOR, "operator:sha256:" + receipt["operator_evidence_digest"], *refs]
        )
        if receipt["source_refs"] != expected_refs:
            raise ReceiptValidationError("receipt source linkage does not match")
        if observed < _time(inventory["observed_at"], captured):
            raise ReceiptValidationError("receipt predates its inventory")
        expected_rows = {row["component_id"]: row for row in inventory["components"]}
        rows = receipt["topology"]
        if len(rows) != len(expected_rows) or {row["component_id"] for row in rows} != set(
            expected_rows
        ):
            raise ReceiptValidationError("complete component topology is required")
        proofs = prerequisites["component_evidence"][kind]
        if set(proofs) != set(expected_rows) or _contains_secret(proofs):
            raise ReceiptValidationError("component source evidence is absent or unsupported")
        for row in rows:
            if any(
                row[key] != expected_rows[row["component_id"]][key]
                for key in ("owner", "placement_class")
            ):
                raise ReceiptValidationError(
                    "component ownership or placement does not match inventory"
                )
            if proofs[row["component_id"]] != {
                key: value
                for key, value in row.items()
                if key not in {"evidence_digest", "source_identity_digest"}
            }:
                raise ReceiptValidationError("component source evidence does not match")
        candidate = receipt["candidate_identity"]
        if kind in {"deploy", "health"}:
            activation = prerequisites["activation"]
            if any(
                candidate[key] != value for key, value in activation["candidate_identity"].items()
            ):
                raise ReceiptValidationError("activation candidate does not match")
            if receipt["runtime"]["engine_id"] != activation["dedicated_engine"]["engine_id"]:
                raise ReceiptValidationError("dedicated engine identity does not match activation")
            control_plane = next(row for row in rows if row["component_id"] == "builderops_control_plane")
            if control_plane["service_or_project"] != activation["dedicated_engine"]["project"]:
                raise ReceiptValidationError("control-plane project does not match activation")
            if kind == "deploy":
                _observations_after(receipt, activation, resident_only=True)
            if observed < _time(activation["observed_at"], captured):
                raise ReceiptValidationError("receipt predates activation")
            for dependency in (
                ["qualification"] if kind == "deploy" else ["qualification", "deploy"]
            ):
                prior = prerequisites[dependency]
                if any(receipt[key] != prior[key] for key in ("candidate_identity", "runtime")):
                    raise ReceiptValidationError(
                        "runtime candidate or topology differs across the receipt chain"
                    )
                if _stable_topology(rows) != _stable_topology(prior["topology"]):
                    raise ReceiptValidationError("component identities changed across the chain")
                _observations_after(receipt, prior, resident_only=(kind == "deploy"))
                if observed < _time(prior["observed_at"], captured):
                    raise ReceiptValidationError("receipt dependency order is invalid")
    except ReceiptValidationError:
        raise
    except Exception as exc:
        raise ReceiptValidationError("receipt or prerequisite evidence is invalid") from exc


def build_receipt(
    kind: str,
    evidence: Mapping[str, Any],
    prerequisites: Mapping[str, Any],
    *,
    now: datetime | None = None,
) -> dict[str, Any]:
    """Produce canonical JSON from explicit evidence, without external effects."""
    try:
        captured = now or datetime.now(timezone.utc)
        expected = _COMMON_EVIDENCE | (
            {"rollback_baseline_state", "previous_identity"} if kind == "deploy" else set()
        )
        if (
            kind not in TYPES
            or not isinstance(evidence, Mapping)
            or set(evidence) != expected
            or _contains_secret(evidence)
        ):
            raise ReceiptValidationError("receipt evidence fields are incomplete or unsupported")
        plain = json.loads(json.dumps(evidence, allow_nan=False))
        inventory, refs = _dependencies(kind, prerequisites, captured)
        plain["topology"] = sorted(plain["topology"], key=lambda row: row["component_id"])
        plain["operator_evidence_digest"] = canonical_digest(plain)
        receipt = {
            **plain,
            "receipt_type": TYPES[kind],
            "receipt_version": 1,
            "target_vm": TARGET,
            "component_id": "devui_projection",
            "component_inventory_digest": inventory["component_inventory_digest"],
            "source_refs": sorted(
                [ANCHOR, "operator:sha256:" + plain["operator_evidence_digest"], *refs]
            ),
            "verdict": VERDICTS[kind],
            "secret_material": "absent",
            "gaps": [],
            "refusals": ["no_compatible_baseline"]
            if kind == "deploy" and plain["rollback_baseline_state"] == "no_baseline"
            else [],
        }
        if kind == "deploy":
            receipt["rollback_baseline_refs"] = _rollback_refs(receipt, prerequisites)
            receipt["source_refs"] = sorted(
                [*receipt["source_refs"], *receipt["rollback_baseline_refs"]]
            )
        receipt["evidence_fingerprint"] = canonical_digest(receipt)
        validate_receipt(receipt, prerequisites, now=captured)
        return receipt
    except ReceiptValidationError:
        raise
    except Exception as exc:
        raise ReceiptValidationError("receipt evidence is invalid") from exc


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--kind", choices=TYPES, required=True)
    parser.add_argument("--bundle", type=Path, required=True)
    parser.add_argument(
        "--verify", action="store_true", help="Verify bundle.receipt with bundle.prerequisites"
    )
    args = parser.parse_args(argv)
    try:
        bundle = json.loads(args.bundle.read_text())
        expected = {"receipt" if args.verify else "evidence", "prerequisites"}
        if not isinstance(bundle, dict) or set(bundle) != expected:
            raise ReceiptValidationError("bundle fields are invalid")
        if args.verify:
            receipt = bundle["receipt"]
            if receipt.get("receipt_type") != TYPES[args.kind]:
                raise ReceiptValidationError("receipt type does not match selected operation")
            validate_receipt(receipt, bundle["prerequisites"])
        else:
            receipt = build_receipt(args.kind, bundle["evidence"], bundle["prerequisites"])
        print(
            json.dumps(
                receipt, sort_keys=True, separators=(",", ":"), ensure_ascii=False, allow_nan=False
            )
        )
        return 0
    except Exception:
        print(
            json.dumps(
                {
                    "verdict": "refused",
                    "operation": args.kind,
                    "reason": "runtime_evidence_invalid_or_unavailable",
                    "mutation_performed": False,
                    "secret_material": "absent",
                },
                sort_keys=True,
            )
        )
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
