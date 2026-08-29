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

RECEIPTS = (
    "devsystem_vm102_component_inventory.v1",
    "builderops_vm_rebuild_activation.v1",
    "devui_vm102_runtime_qualification.v1",
    "devsystem_vm102_deploy.v1",
    "devsystem_vm102_health.v1",
    "devui-stage-a-read-only-owner-pilot.v1",
    "devsystem_vm102_rollback.v1",
)


def _read(relative: str) -> str:
    return (ROOT / relative).read_text(encoding="utf-8")


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
    assert "dedicated BuilderOps engine is empty" in normalized_topology
    assert "strict host ownership inventory was not freshly verified" in normalized_topology


def test_vm102_receipt_contract_names_exact_identity_and_no_secret_gate() -> None:
    contract = _read("docs/BUILDEROPS_CONTROL_PLANE/README.md")
    deployment = _read("docs/deployment/DEPLOYMENT_AND_ENVIRONMENTS.md")
    receipt_contract = contract.split("## VM-102 evidence and receipt contract", 1)[1]

    for receipt in RECEIPTS:
        assert f"`{receipt}`" in receipt_contract
        assert f"`{receipt}`" in deployment
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
    assert "No screen observation, Project view, unbound guest readback" in deployment


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
