from __future__ import annotations

import copy
import hashlib
import json
from pathlib import Path
import subprocess
import sys

import pytest

from app.ops.devsystem_vm102_component_inventory import (
    InventoryValidationError,
    build_component_inventory_receipt,
    validate_component_inventory_receipt,
)


ROOT = Path(__file__).resolve().parents[2]

COMPONENT_IDS = (
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

COMPONENT_EXPECTATIONS = {
    "devui_projection": ("VM-102 resident (target)", "`gap`"),
    "builderops_control_plane": ("VM-102 resident (target)", "`gap`"),
    "builderops_cockpit": ("VM-102 resident (target)", "`gap`"),
    "dispatcher_signboard": ("VM-102 resident (target)", "`gap`"),
    "ddo": ("VM-102 resident (target)", "`gap`"),
    "ckm_kvasir": ("VM-102 resident (target)", "`gap`"),
    "focus_conversation_port": ("VM-102 resident (target)", "`gap`"),
    "soi_evidence": ("explicit external dependency", "`gap`"),
    "github_git_ci_delivery": ("explicit external dependency", "`external`"),
    "model_service": ("explicit external dependency", "`gap`"),
    "tars_proxmox_control": ("explicit external dependency", "`gap`"),
    "product_runtime": ("intentionally non-runtime", "`excluded`"),
}

RECEIPTS = (
    "devsystem_vm102_component_inventory.v1",
    "builderops_vm_rebuild_activation.v1",
    "devui_vm102_runtime_qualification.v1",
    "devsystem_vm102_deploy.v1",
    "devsystem_vm102_health.v1",
    "devui-stage-a-read-only-owner-pilot.v1",
    "devsystem_vm102_rollback.v1",
)

RECEIPT_CONSUMERS = {
    "docs/BUILDEROPS_CONTROL_PLANE/INDEPENDENT_AUTHENTICATED_DEPLOYMENT.md": (
        "README.md#vm-102-evidence-and-receipt-contract"
    ),
    "docs/DEVUI.md": (
        "BUILDEROPS_CONTROL_PLANE/README.md#vm-102-evidence-and-receipt-contract"
    ),
    "docs/deployment/DEPLOYMENT_AND_ENVIRONMENTS.md": (
        "../BUILDEROPS_CONTROL_PLANE/README.md#vm-102-evidence-and-receipt-contract"
    ),
    "docs/deployment/profiles/TARS_PROXMOX.md": (
        "../../BUILDEROPS_CONTROL_PLANE/README.md#vm-102-evidence-and-receipt-contract"
    ),
}

INVENTORY_REFUSALS = (
    "activation_not_proven",
    "deployment_not_proven",
    "health_not_proven",
    "qualification_not_proven",
    "residency_not_proven",
    "rollback_not_proven",
)


def _canonical_digest(value: object) -> str:
    encoded = json.dumps(
        value,
        ensure_ascii=False,
        separators=(",", ":"),
        sort_keys=True,
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def _inventory_evidence() -> dict[str, object]:
    source_ref = (
        "repo:docs/BUILDEROPS_CONTROL_PLANE/README.md"
        "#complete-dev-system-vm-102-topology-contract"
    )
    components: list[dict[str, object]] = []
    gaps: list[dict[str, str]] = []
    for component_id in COMPONENT_IDS:
        _, documented_state = COMPONENT_EXPECTATIONS[component_id]
        reconciliation_state = documented_state.strip("`")
        components.append(
            {
                "component_id": component_id,
                "placement_class": {
                    "VM-102 resident (target)": "vm102_resident_target",
                    "explicit external dependency": "external_dependency",
                    "intentionally non-runtime": "intentionally_non_runtime",
                }[COMPONENT_EXPECTATIONS[component_id][0]],
                "owner": f"owner:{component_id}",
                "service_or_project": (
                    f"{reconciliation_state}: operator-supplied service or project evidence"
                ),
                "source_identity": (
                    f"{reconciliation_state}: operator-supplied source or image evidence"
                ),
                "ingress_auth": (
                    f"{reconciliation_state}: operator-supplied ingress and auth posture"
                ),
                "health_version": (
                    f"{reconciliation_state}: operator-supplied health and version evidence"
                ),
                "deployment_lifecycle": (
                    f"{reconciliation_state}: operator-supplied deployment and lifecycle evidence"
                ),
                "migration_rollback": (
                    f"{reconciliation_state}: operator-supplied migration and rollback evidence"
                ),
                "reconciliation_state": reconciliation_state,
                "evidence_refs": [source_ref],
            }
        )
        if reconciliation_state == "gap":
            gaps.append(
                {
                    "component_id": component_id,
                    "code": "runtime_evidence_missing",
                    "detail": "runtime evidence is not supplied by this inventory",
                }
            )
    return {
        "receipt_type": "devsystem_vm102_component_inventory.v1",
        "receipt_version": 1,
        "target_vm": {"vmid": 102, "name": "builder-system"},
        "observed_at": "2026-08-29T18:00:00Z",
        "source_refs": [source_ref, "github:issue:5194"],
        "components": components,
        "secret_material": "absent",
        "gaps": gaps,
        "refusals": list(INVENTORY_REFUSALS),
        "claims": {
            "inventory_complete": True,
            "residency_proven": False,
            "qualification_proven": False,
            "activation_proven": False,
            "deployment_proven": False,
            "health_proven": False,
            "rollback_proven": False,
        },
    }


def _read(relative: str) -> str:
    return (ROOT / relative).read_text(encoding="utf-8")


def test_adr0062_amendment_owns_vm102_placement_and_rebuildable_posture() -> None:
    adr = _read("docs/adr/ADR-0062-builderops-ecosystem-wide-enabling-system.md")
    amendment = adr.split("### A4", 1)[1].split("## Source docs and evidence", 1)[0]
    normalized_amendment = " ".join(amendment.split()).lower()

    assert "complete dev system placement on vm 102" in normalized_amendment
    assert "vm 102 is the intended cohesive runtime home" in normalized_amendment
    assert "external authenticated client and operator dependency" in normalized_amendment
    assert "rebuildable from source, images, configuration, and host-managed secrets" in normalized_amendment
    assert "backup, wal archive, and restore drill are deferred" in normalized_amendment
    assert "a4 supersedes conflicting placement and recovery-gate language in d2 through d6" in normalized_amendment


def test_complete_vm102_topology_keeps_known_components_and_gaps_visible() -> None:
    contract = _read("docs/BUILDEROPS_CONTROL_PLANE/README.md")
    topology = contract.split("## Complete Dev System VM-102 topology contract", 1)[1].split(
        "## VM-102 evidence and receipt contract", 1
    )[0]
    normalized_topology = " ".join(topology.split())

    assert "VM 102 is the intended cohesive runtime home" in normalized_topology
    assert "not a deployment or qualification receipt" in normalized_topology
    assert "VM-102 resident (target)" in normalized_topology
    assert "explicit external dependency" in normalized_topology
    assert "intentionally non-runtime" in normalized_topology
    assert "`gap` is a required state" in normalized_topology
    for component_id in COMPONENT_IDS:
        assert f"`{component_id}`" in normalized_topology
    for component_id, (placement_class, state) in COMPONENT_EXPECTATIONS.items():
        row = next(line for line in topology.splitlines() if f"`{component_id}`" in line)
        assert placement_class in row
        assert state in row
    assert "runtime evidence remains an explicit `gap` until a bound receipt proves it" in normalized_topology.lower()


def test_vm102_receipt_contract_names_exact_identity_and_no_secret_gate() -> None:
    contract = _read("docs/BUILDEROPS_CONTROL_PLANE/README.md")
    receipt_contract = contract.split("## VM-102 evidence and receipt contract", 1)[1]
    normalized_receipt_contract = " ".join(receipt_contract.split()).lower()

    for receipt in RECEIPTS:
        assert f"`{receipt}`" in receipt_contract
    for field in (
        "receipt_type",
        "receipt_version",
        "target_vm",
        "observed_at",
        "source_refs",
        "evidence_fingerprint",
        "secret_material: absent",
        "gaps",
        "refusals",
    ):
        assert field in receipt_contract
    assert "`tars_host_qualification.v1` is only the repository-side candidate" in receipt_contract
    assert "`rollback_baseline_state: available`" in receipt_contract
    assert "`rollback_baseline_state: no_baseline`" in receipt_contract
    assert "`no_compatible_baseline`" in receipt_contract
    assert "all-zero source, image, or configuration placeholders are invalid" in normalized_receipt_contract
    assert "a later successful deployment establishes a runnable baseline" in normalized_receipt_contract


def test_vm102_receipt_owner_enforces_dependency_order_and_conditional_rollback() -> None:
    contract = _read("docs/BUILDEROPS_CONTROL_PLANE/README.md")
    ordering = contract.split("### Normative receipt dependency order", 1)[1].split(
        "| Receipt | Required proof | Does not prove by itself |", 1
    )[0]

    inventory = ordering.index("`devsystem_vm102_component_inventory.v1`")
    activation = ordering.index("`builderops_vm_rebuild_activation.v1`")
    qualification = ordering.index("`devui_vm102_runtime_qualification.v1`")
    deploy = ordering.index("`devsystem_vm102_deploy.v1`")
    health = ordering.index("`devsystem_vm102_health.v1`")
    pilot = ordering.index("`devui-stage-a-read-only-owner-pilot.v1`")
    rollback = ordering.index("`devsystem_vm102_rollback.v1`")

    assert inventory < activation < deploy < health < pilot
    assert inventory < qualification < deploy
    assert rollback > deploy
    assert "conditional side path" in ordering
    assert "rollback_baseline_state: available" in ordering
    assert "no_baseline" in ordering


def test_receipt_consumers_link_to_single_normative_owner() -> None:
    for relative, owner_link in RECEIPT_CONSUMERS.items():
        consumer = _read(relative)
        assert owner_link in consumer
        assert "rollback_baseline_state" not in consumer
        assert "receipt_version" not in consumer


def test_dev_system_docs_preserve_the_product_runtime_boundary() -> None:
    for relative in (
        "docs/DEVUI.md",
        "docs/DEVUI_STAGE_A_READ_ONLY_OVERVIEW/README.md",
        "docs/BUILDEROPS_CONTROL_PLANE/INDEPENDENT_AUTHENTICATED_DEPLOYMENT.md",
        "docs/deployment/profiles/TARS_PROXMOX.md",
    ):
        document = _read(relative)
        assert "VM 102" in document
        assert "Product Runtime" in document
        assert "does not" in document or "no live" in document


def test_component_inventory_schema_and_validator_enforce_identity_rows_and_digest() -> None:
    evidence = _inventory_evidence()
    receipt = build_component_inventory_receipt(evidence)

    validate_component_inventory_receipt(receipt)
    assert receipt["receipt_type"] == "devsystem_vm102_component_inventory.v1"
    assert receipt["receipt_version"] == 1
    assert receipt["target_vm"] == {"vmid": 102, "name": "builder-system"}
    assert [row["component_id"] for row in receipt["components"]] == list(COMPONENT_IDS)
    assert receipt["component_inventory_digest"] == _canonical_digest(receipt["components"])
    assert receipt["claims"] == evidence["claims"]
    assert all(value is False for key, value in receipt["claims"].items() if key != "inventory_complete")


def test_component_inventory_rejects_malformed_and_secret_bearing_evidence() -> None:
    duplicate = _inventory_evidence()
    duplicate["components"] = [*duplicate["components"][:-1], duplicate["components"][0]]
    with pytest.raises(InventoryValidationError):
        build_component_inventory_receipt(duplicate)

    missing = _inventory_evidence()
    missing["components"] = missing["components"][:-1]
    with pytest.raises(InventoryValidationError):
        build_component_inventory_receipt(missing)

    for field, invalid in (
        ("target_vm", {"vmid": 103, "name": "builder-system"}),
        ("observed_at", "2026-08-29 18:00:00"),
        ("source_refs", ["https://user:password@example.invalid/evidence"]),
    ):
        malformed = _inventory_evidence()
        malformed[field] = invalid
        with pytest.raises(InventoryValidationError):
            build_component_inventory_receipt(malformed)

    secret = _inventory_evidence()
    secret["components"][0]["source_identity"] = "gap: bearer ghp_not-a-real-token"
    with pytest.raises(InventoryValidationError):
        build_component_inventory_receipt(secret)

    receipt = build_component_inventory_receipt(_inventory_evidence())
    tampered_digest = copy.deepcopy(receipt)
    tampered_digest["component_inventory_digest"] = "0" * 64
    with pytest.raises(InventoryValidationError):
        validate_component_inventory_receipt(tampered_digest)

    tampered_component_fingerprint = copy.deepcopy(receipt)
    tampered_component_fingerprint["evidence_fingerprints"][COMPONENT_IDS[0]] = "0" * 64
    with pytest.raises(InventoryValidationError):
        validate_component_inventory_receipt(tampered_component_fingerprint)

    tampered_evidence_fingerprint = copy.deepcopy(receipt)
    tampered_evidence_fingerprint["evidence_fingerprint"] = "0" * 64
    with pytest.raises(InventoryValidationError):
        validate_component_inventory_receipt(tampered_evidence_fingerprint)


def test_component_inventory_preserves_gaps_and_refuses_false_claims() -> None:
    evidence = _inventory_evidence()
    receipt = build_component_inventory_receipt(evidence)

    assert receipt["gaps"] == evidence["gaps"]
    assert set(receipt["refusals"]) == set(INVENTORY_REFUSALS)
    for row in receipt["components"]:
        assert row["reconciliation_state"] in {"gap", "external", "excluded"}
        for field in (
            "service_or_project",
            "source_identity",
            "ingress_auth",
            "health_version",
            "deployment_lifecycle",
            "migration_rollback",
        ):
            assert row[field].startswith(f"{row['reconciliation_state']}:")

    escalated_state = _inventory_evidence()
    escalated_state["components"][0]["reconciliation_state"] = "resident"
    with pytest.raises(InventoryValidationError):
        build_component_inventory_receipt(escalated_state)

    hidden_gap = _inventory_evidence()
    hidden_gap["components"][0]["deployment_lifecycle"] = "deployed and active"
    with pytest.raises(InventoryValidationError):
        build_component_inventory_receipt(hidden_gap)

    false_claim = _inventory_evidence()
    false_claim["claims"]["deployment_proven"] = True
    with pytest.raises(InventoryValidationError):
        build_component_inventory_receipt(false_claim)


def test_component_inventory_cli_consumes_only_operator_evidence(tmp_path: Path) -> None:
    import app.ops.devsystem_vm102_component_inventory as inventory_module

    assert "caller-supplied" in (inventory_module.__doc__ or "")
    assert "no host access" in (inventory_module.__doc__ or "").lower()

    evidence_path = tmp_path / "operator-evidence.json"
    evidence_path.write_text(json.dumps(_inventory_evidence()), encoding="utf-8")
    result = subprocess.run(
        [sys.executable, "-m", "app.ops.devsystem_vm102_component_inventory", "--evidence", str(evidence_path)],
        cwd=ROOT,
        check=False,
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0, result.stderr
    receipt = json.loads(result.stdout)
    assert receipt["claims"]["inventory_complete"] is True
    assert receipt["claims"]["residency_proven"] is False
    assert receipt["claims"]["deployment_proven"] is False

    absent_path = tmp_path / "absent-evidence.json"
    absent_path.write_text("{}", encoding="utf-8")
    absent = subprocess.run(
        [sys.executable, "-m", "app.ops.devsystem_vm102_component_inventory", "--evidence", str(absent_path)],
        cwd=ROOT,
        check=False,
        capture_output=True,
        text=True,
    )
    assert absent.returncode == 2
    assert absent.stdout == ""

    raw_secret = "ghp_not-a-real-token"
    secret_path = tmp_path / "secret-evidence.json"
    secret_evidence = _inventory_evidence()
    secret_evidence["components"][0]["source_identity"] = f"gap: {raw_secret}"
    secret_path.write_text(json.dumps(secret_evidence), encoding="utf-8")
    refused = subprocess.run(
        [sys.executable, "-m", "app.ops.devsystem_vm102_component_inventory", "--evidence", str(secret_path)],
        cwd=ROOT,
        check=False,
        capture_output=True,
        text=True,
    )
    assert refused.returncode == 2
    assert raw_secret not in refused.stdout
    assert raw_secret not in refused.stderr
