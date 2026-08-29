from __future__ import annotations

from pathlib import Path


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
