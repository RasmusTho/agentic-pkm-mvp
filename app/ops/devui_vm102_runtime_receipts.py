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
from pathlib import Path, PurePosixPath
import re
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


FIRST_READ_TYPE = "devui_first_read_observation.v1"
FIRST_READ_COMPONENTS = sorted([
    "devui_projection", "builderops_control_plane", "builderops_cockpit",
    "github_git_ci_delivery", "tars_proxmox_control",
])
_FIRST_FIELDS = {
    "selection": {"repository", "candidate_identity", "merged_main_sha", "eligible", "required_checks", "relevant_change", "replacement_sha", "withdrawn", "attestation_sha256", "attestation_verified_at"},
    "operator": {"activation_sha256", "private_ingress", "promotion_acknowledged", "linux_probe", "rollback"},
    "source": {"repository", "authority_epoch", "grants", "custody_ref", "reachable", "quota_complete"},
    "github": {"payload"}, "task": {"payload"},
    "exchange": {"authority_epoch", "request", "request_body", "response", "request_sha256"},
    "installed": {"candidate_identity", "origin", "assets", "documents", "runtime"},
    "browser": {"candidate_sha", "origin", "applicability_observed_at", "artifacts", "artifact_sha256", "passed"},
    "journey": {"started_at", "candidate_sha", "origin", "task_id", "issue_version", "body_sha256", "subject", "routes", "inspected_documents", "artifacts", "artifact_sha256", "effects"},
    "owner": {"journey_sha256", "acknowledged", "meaning"},
}


def _first_require(condition: bool, reason: str) -> None:
    if not condition:
        raise ReceiptValidationError(reason)


def _first_manifest(value: Any) -> None:
    _first_require(isinstance(value, dict) and bool(value), "artifact inventory is missing")
    for name, digest in value.items():
        _first_require(
            isinstance(name, str) and not name.startswith("/") and ".." not in Path(name).parts
            and bool(name) and isinstance(digest, str) and re.fullmatch(r"[a-f0-9]{64}", digest) is not None,
            "artifact inventory is invalid",
        )


def _first_source_documents(section: str) -> set[str]:
    documents = set()
    for raw in section.splitlines():
        if not raw.strip():
            continue
        entry = re.sub(r"^[-*+]\s+", "", raw.strip())
        wrapped = re.fullmatch(r"`([^`]+)`|\[[^\]\n]+\]\(([^()\n]+)\)", entry)
        target = (wrapped.group(1) or wrapped.group(2)) if wrapped else entry
        path = target.partition("#")[0]
        _first_require(
            bool(path) and not any(char in target for char in "`[]()\\:")
            and not PurePosixPath(path).is_absolute()
            and ".." not in PurePosixPath(path).parts
            and PurePosixPath(path).as_posix() == path and path != ".",
            "selected Issue document reference is invalid",
        )
        documents.add(path)
    _first_require(bool(documents), "selected Issue documents are missing")
    return documents


def _first_read_record(evidence: Mapping[str, Any], prerequisites: Mapping[str, Any], captured: datetime) -> dict[str, Any]:
    # Imports stay on this bounded path: starting the independent listener does
    # not load the dispatcher/normalizer, nor create any local dispatcher store.
    from app.builderops.control_plane.client_cli import issue_source_task, same_json_value, validate_import_readback, validate_import_response
    from app.builderops.devui_assets import ASSET_SHA256
    from scripts.validate_issue_readiness import extract_sections

    _first_require(set(prerequisites) == {"inventory", "activation"}, "first-read prerequisites are incomplete")
    _first_require(set(evidence) == set(_FIRST_FIELDS) and not _contains_secret([evidence, prerequisites]), "first-read packets are incomplete or secret-bearing")
    inventory, activation = prerequisites["inventory"], prerequisites["activation"]
    validate_component_inventory_receipt(inventory)
    validate_activation_receipt(activation)
    inventory_time = _time(inventory["observed_at"], captured)
    activation_time = _time(activation["observed_at"], captured)
    _first_require(activation_time >= inventory_time and activation["component_inventory_digest"] == inventory["component_inventory_digest"], "activation inventory binding is invalid")
    times = {}
    for name, fields in _FIRST_FIELDS.items():
        packet = evidence[name]
        _first_require(isinstance(packet, dict) and set(packet) == fields | {"observer", "observed_at", "source_ref"}, "first-read packet fields are invalid")
        _first_require(all(isinstance(packet[key], str) and packet[key].strip() for key in ("observer", "source_ref")), "observation identity is missing")
        if name == "browser":
            stamp = datetime.fromisoformat(packet["observed_at"].replace("Z", "+00:00"))
            _first_require(stamp.tzinfo is not None and stamp <= captured, "browser artifact time is invalid")
            times[name] = _time(packet["applicability_observed_at"], captured)
            _first_require(times[name] >= stamp, "browser applicability predates its artifact")
        else:
            times[name] = _time(packet["observed_at"], captured)
    selection, operator, source = (evidence[key] for key in ("selection", "operator", "source"))
    installed, browser, journey, owner = (evidence[key] for key in ("installed", "browser", "journey", "owner"))
    candidate = selection["candidate_identity"]
    full_schema = json.loads((ROOT / "config/platform/devui_vm102_runtime_qualification.v1.schema.json").read_text())
    candidate_validator = Draft202012Validator(full_schema["properties"]["candidate_identity"])
    candidate_validator.validate(candidate)
    _candidate(candidate)
    _first_require(
        selection["eligible"] is True and selection["required_checks"] == "passed"
        and selection["withdrawn"] is False and selection["relevant_change"] is False
        and selection["replacement_sha"] is None and selection["merged_main_sha"] == candidate["source_sha"]
        and re.fullmatch(r"[a-f0-9]{64}", selection["attestation_sha256"]) is not None,
        "selected merged candidate is ineligible",
    )
    _first_require(all(candidate[key] == value for key, value in activation["candidate_identity"].items()), "activation candidate mismatch")
    _first_require(
        operator["activation_sha256"] == canonical_digest(activation)
        and operator["private_ingress"] is True and operator["promotion_acknowledged"] is True,
        "operator prerequisites are invalid",
    )
    probe = operator["linux_probe"]
    _first_require(set(probe) == {"applicability", "source_ref", "result"} and bool(probe["source_ref"])
                   and (probe["applicability"], probe["result"]) in {("required", "passed"), ("not_applicable", "not_applicable")}, "applicable Linux probe is unproven")
    rollback = operator["rollback"]
    _first_require(set(rollback) == {"state", "previous_identity", "compatibility", "observed_at", "source_ref"} and bool(rollback["source_ref"]), "rollback evidence is invalid")
    _first_require(activation_time <= _time(rollback["observed_at"], captured) <= times["operator"], "rollback compatibility time is invalid")
    if rollback["state"] == "no_baseline":
        _first_require(rollback["previous_identity"] is None and rollback["compatibility"] == "rollback_refused", "absent rollback baseline cannot authorize rollback")
    else:
        _first_require(rollback["state"] == "available" and rollback["compatibility"] == "verified_no_data_rewind"
                       and set(rollback["previous_identity"]) == set(candidate), "compatible exact rollback pins are required")
        _candidate(rollback["previous_identity"])
        candidate_validator.validate(rollback["previous_identity"])
    _first_require(source["repository"] == selection["repository"] and source["grants"] == ["receipts:read", "status:read"]
                   and source["reachable"] is True and source["quota_complete"] is True and bool(source["custody_ref"])
                   and type(source["authority_epoch"]) is int
                   and source["authority_epoch"] == activation["migration"]["authority_epoch"], "source admission or epoch is invalid")
    exchange = evidence["exchange"]
    request = exchange["request"]
    _first_require(set(request) == {"envelope", "task_id", "to_state", "idempotency_key", "request", "outbox", "lease", "expected_states", "expected_version"}, "initial transition request is invalid")
    _first_require(request["to_state"] == "ready" and all(request[key] is None for key in ("outbox", "lease", "expected_states", "expected_version"))
                   and isinstance(request["idempotency_key"], str) and bool(request["idempotency_key"])
                   and exchange["authority_epoch"] == source["authority_epoch"], "initial transition authority is invalid")
    body = exchange["request_body"]
    _first_require(isinstance(body, str) and same_json_value(json.loads(body), request), "observed request bytes differ from decoded request")
    _first_require(exchange["request_sha256"] == hashlib.sha256(body.encode("utf-8")).hexdigest(), "observed request digest differs")
    issue = evidence["github"]["payload"]
    original_time = request["request"]["sync_state"]["last_pull_at"]
    expected_task = issue_source_task(issue, repository=source["repository"], number=issue["number"], observed_at=original_time, authority_epoch=source["authority_epoch"])
    _first_require(_time(original_time, captured) <= times["exchange"] and same_json_value(request["request"], expected_task)
                   and request["task_id"] == expected_task["task_id"],
                   "independent Issue bytes do not match the retained native task")
    _first_require(set(request["envelope"]) == {"repository", "scope", "stack", "source_refs"}
                   and request["envelope"]["scope"] == f"issue:{issue['number']}" and request["envelope"]["source_refs"] == expected_task["source_anchor_refs"]
                   and request["envelope"]["repository"] == source["repository"] and bool(request["envelope"]["stack"]), "initial source envelope is invalid")
    validate_import_response(exchange["response"], request)
    validate_import_readback(evidence["task"]["payload"], request)
    _first_require(evidence["github"]["source_ref"] != exchange["source_ref"] and evidence["task"]["source_ref"] != exchange["source_ref"], "independent observation references are required")
    _first_require(installed["candidate_identity"] == candidate and installed["assets"] == ASSET_SHA256,
                   "installed candidate or managed assets differ")
    _first_manifest(installed["documents"])
    required_docs = _first_source_documents(extract_sections(issue["body"])["source docs"])
    _first_require(required_docs.issubset(installed["documents"])
                   and required_docs.issubset(journey["inspected_documents"]), "selected Issue documents are unavailable or uninspected")
    _first_require(installed["origin"] in {"http://127.0.0.1:8113", "http://localhost:8113"}
                   and browser["origin"] == journey["origin"] == installed["origin"]
                   and browser["candidate_sha"] == journey["candidate_sha"] == candidate["source_sha"], "journey origin or candidate differs")
    runtime = installed["runtime"]
    Draft202012Validator(full_schema["properties"]["runtime"]).validate(runtime)
    _first_require(runtime["engine_id"] == activation["dedicated_engine"]["engine_id"], "runtime engine differs from activation")
    for packet in (browser, journey):
        _first_manifest(packet["artifacts"])
        _first_require(packet["artifact_sha256"] == canonical_digest(packet["artifacts"]), "journey artifact digest differs")
    _first_require(browser["passed"] is True and journey["subject"] == f"github:{source['repository']}#{issue['number']}"
                   and journey["task_id"] == expected_task["task_id"] and journey["issue_version"] == issue["updated_at"]
                   and journey["body_sha256"] == expected_task["sync_state"]["body_sha256"]
                   and journey["routes"] == ["/devui/overview", "/devui/focus", "/devui/overview"], "one-Issue read journey is unproven")
    _first_require(set(journey["effects"]) == {"github_writes", "task_mutations", "leases", "provider_sessions", "outbox", "browser_storage", "refused_requests"}
                   and all(type(value) is int and value == 0 for value in journey["effects"].values()), "read journey observed an effect or refused boundary")
    started = _time(journey["started_at"], captured)
    attested = _time(selection["attestation_verified_at"], captured)
    _first_require(
        activation_time <= times["operator"] and times["selection"] <= attested <= times["operator"]
        and times["operator"] <= times["source"] <= times["exchange"]
        and times["exchange"] <= min(times["github"], times["task"])
        and max(times["operator"], times["selection"]) <= times["installed"]
        and times["selection"] <= times["browser"]
        and max(times["source"], times["github"], times["task"], times["installed"], times["browser"]) <= started <= times["journey"] <= times["owner"],
        "read observation predates a prerequisite",
    )
    _first_require(owner["acknowledged"] is True and owner["meaning"] == "read_observed"
                   and owner["journey_sha256"] == canonical_digest(journey), "owner acknowledgement does not bind the completed read")
    return {
        "receipt_type": FIRST_READ_TYPE, "receipt_version": 1, "observed_at": captured.isoformat(),
        "verdict": "pass", "refusals": [], "secret_material": "absent",
        "claim": "source_backed_zero_effect_read_only", "repository": source["repository"],
        "candidate_identity": candidate, "origin": installed["origin"], "runtime": runtime,
        "issue_binding": {"number": issue["number"], "version": issue["updated_at"], "body_sha256": expected_task["sync_state"]["body_sha256"], "task_id": expected_task["task_id"]},
        "source": {key: source[key] for key in ("repository", "authority_epoch", "grants")},
        "assets": installed["assets"], "documents": installed["documents"],
        "consumed_components": FIRST_READ_COMPONENTS, "components": inventory["components"], "gaps": inventory["gaps"],
        "input_sha256": canonical_digest({"evidence": evidence, "prerequisites": prerequisites}),
        "observations": {name: {"observer": packet["observer"], "observed_at": packet["observed_at"], "source_ref": packet["source_ref"], "sha256": canonical_digest(packet)} for name, packet in evidence.items()},
    }


def first_read_schema() -> dict[str, Any]:
    return json.loads((ROOT / "config/platform" / f"{FIRST_READ_TYPE}.schema.json").read_text())


def build_first_read_observation(evidence: Mapping[str, Any], prerequisites: Mapping[str, Any], *, now: datetime | None = None) -> dict[str, Any]:
    """One closed, derived observation; cannot feed any full-chain producer."""
    captured = now or datetime.now(timezone.utc)
    try:
        receipt = _first_read_record(evidence, prerequisites, captured)
        receipt["evidence_fingerprint"] = canonical_digest(receipt)
        Draft202012Validator(first_read_schema(), format_checker=FormatChecker()).validate(receipt)
        return receipt
    except Exception:
        return {"receipt_type": FIRST_READ_TYPE, "receipt_version": 1, "observed_at": captured.isoformat(),
                "verdict": "refused", "refusals": ["first_read_evidence_invalid_or_unavailable"], "secret_material": "absent"}


def validate_first_read_observation(receipt: Mapping[str, Any], evidence: Mapping[str, Any], prerequisites: Mapping[str, Any], *, now: datetime | None = None) -> None:
    try:
        captured = now or datetime.now(timezone.utc)
        _time(receipt["observed_at"], captured)
        expected = _first_read_record(evidence, prerequisites, captured)
        expected["observed_at"] = receipt["observed_at"]
        _first_require(_time(receipt["observed_at"], captured) >= _time(evidence["owner"]["observed_at"], captured), "receipt predates owner observation")
        expected["evidence_fingerprint"] = canonical_digest(expected)
        Draft202012Validator(first_read_schema(), format_checker=FormatChecker()).validate(receipt)
        _first_require(receipt == expected, "first-read receipt differs from retained inputs")
    except ReceiptValidationError:
        raise
    except Exception as exc:
        raise ReceiptValidationError("first-read evidence is invalid or unavailable") from exc


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--kind", choices=[*TYPES, "first-read"], required=True)
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
            if args.kind == "first-read":
                raise ReceiptValidationError("first-read verification requires retained evidence; use its bounded reader")
            if receipt.get("receipt_type") != TYPES[args.kind]:
                raise ReceiptValidationError("receipt type does not match selected operation")
            validate_receipt(receipt, bundle["prerequisites"])
        else:
            receipt = (build_first_read_observation(bundle["evidence"], bundle["prerequisites"])
                       if args.kind == "first-read" else build_receipt(args.kind, bundle["evidence"], bundle["prerequisites"]))
        print(
            json.dumps(
                receipt, sort_keys=True, separators=(",", ":"), ensure_ascii=False, allow_nan=False
            )
        )
        return 2 if receipt.get("verdict") == "refused" else 0
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
