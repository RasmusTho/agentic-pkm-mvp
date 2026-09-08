from __future__ import annotations

import copy
from datetime import datetime, timedelta, timezone
import json
from pathlib import Path
import subprocess
import sys

import pytest
from jsonschema import Draft202012Validator

from app.ops.builderops_vm_rebuild_activation import (
    ActivationValidationError,
    build_activation_receipt,
    validate_activation_receipt,
)


ROOT = Path(__file__).resolve().parents[2]


def _now_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace(
        "+00:00", "Z"
    )


def _evidence() -> dict[str, object]:
    return {
        "receipt_type": "builderops_vm_rebuild_activation.v1",
        "receipt_version": 1,
        "target_vm": {"vmid": 102, "name": "builder-system"},
        "observed_at": _now_iso(),
        "source_refs": sorted(
            [
                "repo:docs/BUILDEROPS_CONTROL_PLANE/README.md#vm-102-evidence-and-receipt-contract",
                "repo:scripts/deploy_builderops.sh#builderops_assert_failure_domain",
                "github:issue:5428",
                "github:pr:5457",
                "github:commit:6e8e62f36ea64c2ad0691028c99be39d2fce74d4",
                "operator:sha256:" + "a" * 64,
                "receipt:devsystem_vm102_component_inventory.v1:" + "b" * 64,
            ]
        ),
        "component_inventory_digest": "b" * 64,
        "activation_mode": "existing_runtime_reconciled",
        "candidate_identity": {
            "source_sha": "6e8e62f36ea64c2ad0691028c99be39d2fce74d4",
            "control_plane_image_digest": "sha256:" + "e" * 64,
            "postgres_image_digest": "sha256:" + "f" * 64,
            "config_fingerprint": "sha256:" + "4" * 64,
        },
        "host_identity": {
            "proxmox_node": "tars",
            "proxmox_vm_name": "bob-1",
            "guest_hostname": "builder-system",
            "guest_ip": "10.42.42.121",
            "host_key_fingerprint": "ssh-ed25519:SHA256:1Hjf4duEUo9aNPEcQxDEGJIGg1pUzD2lluE2sd9QVDE",
            "vm_running": True,
            "qemu_agent_ready": True,
        },
        "dedicated_engine": {
            "context": "builderops",
            "socket": "unix:///run/docker-builderops.sock",
            "engine_id": "799a3d86-54f6-4208-b71a-36ae3eee61b6",
            "project": "builderops-control-plane",
            "compose_config_fingerprint": "sha256:" + "4" * 64,
            "services": ["api", "db", "migrate", "worker"],
            "healthy_services": ["api", "db", "worker"],
        },
        "product_engine": {
            "context": "default",
            "socket": "unix:///var/run/docker.sock",
            "engine_id": "2cae4764-d613-484d-b63d-0d353d5eab7c",
            "projects": [],
            "duplicate_observed_before_quarantine": True,
        },
        "migration": {
            "completed": True,
            "schema_version": 4,
            "authority_epoch": 1,
            "classification": "forward_only_no_data_rewind",
            "rollback_data_rewind": "forbidden",
        },
        "fencing": {
            "proven": True,
            "engine_service": "docker-builderops.service",
            "engine_service_enabled": True,
            "engine_service_restart": "always",
            "control_plane_service": "builderops-control-plane.service",
            "control_plane_service_enabled": True,
            "forwarder_service": "builderops-loopback-forwarder.service",
            "forwarder_service_enabled": True,
            "post_reboot_verified": True,
        },
        "no_dual_writer": {
            "proven": True,
            "pre_quarantine_duplicate_project": True,
            "quarantine_action": "default_engine_project_down_without_volume_removal",
            "post_quarantine_product_projects": [],
            "volume_removal": False,
        },
        "readiness": {
            "ready": True,
            "unauthenticated_status": 401,
            "loopback_endpoint": "127.0.0.1:18100",
            "authentication": "scoped-bearer-over-loopback",
            "private_ingress": "tailscale-serve-https-loopback-no-funnel",
            "no_funnel": True,
        },
        "secret_material": "absent",
        "gaps": [],
        "refusals": [],
        "claims": {
            "activation_proven": True,
            "dedicated_engine_proven": True,
            "migration_proven": True,
            "fencing_proven": True,
            "no_dual_writer_proven": True,
            "readiness_proven": True,
        },
    }


def test_activation_receipt_binds_all_live_gates_and_digest() -> None:
    receipt = build_activation_receipt(_evidence())

    validate_activation_receipt(receipt)
    assert receipt["receipt_type"] == "builderops_vm_rebuild_activation.v1"
    assert receipt["target_vm"] == {"vmid": 102, "name": "builder-system"}
    assert receipt["no_dual_writer"]["post_quarantine_product_projects"] == []
    assert len(receipt["evidence_fingerprint"]) == 64


def test_activation_receipt_schema_is_closed() -> None:
    schema = json.loads(
        (ROOT / "config/platform/builderops_vm_rebuild_activation.v1.schema.json").read_text()
    )
    receipt = build_activation_receipt(_evidence())
    assert not list(Draft202012Validator(schema).iter_errors(receipt))


@pytest.mark.parametrize(
    "path, value",
    [
        (("product_engine", "projects"), ["builderops-control-plane"]),
        (("claims", "no_dual_writer_proven"), False),
        (("readiness", "unauthenticated_status"), 200),
        (("candidate_identity", "source_sha"), "0" * 40),
        (("host_identity", "proxmox_vm_name"), "builder-system"),
        (("host_identity", "guest_hostname"), "bob-1"),
    ],
)
def test_activation_receipt_refuses_gate_drift(path: tuple[str, str], value: object) -> None:
    evidence = _evidence()
    cursor: dict[str, object] = evidence
    cursor[path[0]] = copy.deepcopy(cursor[path[0]])
    cursor[path[0]][path[1]] = value  # type: ignore[index]

    with pytest.raises(ActivationValidationError):
        build_activation_receipt(evidence)


def test_activation_receipt_refuses_secret_bearing_evidence() -> None:
    evidence = _evidence()
    evidence["readiness"] = {
        **evidence["readiness"],  # type: ignore[dict-item]
        "authentication": "Bearer ghp_not-for-receipt",
    }

    with pytest.raises(ActivationValidationError):
        build_activation_receipt(evidence)


def test_activation_receipt_requires_inventory_digest_and_matching_receipt_ref() -> None:
    missing = _evidence()
    del missing["component_inventory_digest"]
    with pytest.raises(ActivationValidationError):
        build_activation_receipt(missing)

    mismatched = _evidence()
    mismatched["component_inventory_digest"] = "c" * 64
    with pytest.raises(ActivationValidationError):
        build_activation_receipt(mismatched)

    wrong_type = _evidence()
    wrong_type["source_refs"] = sorted(
        ref.replace("devsystem_vm102_component_inventory.v1", "other_receipt")
        if ref.startswith("receipt:devsystem_vm102_component_inventory.v1:")
        else ref
        for ref in wrong_type["source_refs"]  # type: ignore[index]
    )
    with pytest.raises(ActivationValidationError):
        build_activation_receipt(wrong_type)


def test_activation_receipt_rejects_stale_or_future_observed_at() -> None:
    stale = _evidence()
    stale["observed_at"] = (
        datetime.now(timezone.utc) - timedelta(hours=24, seconds=1)
    ).isoformat().replace("+00:00", "Z")
    with pytest.raises(ActivationValidationError, match="stale"):
        build_activation_receipt(stale)

    future = _evidence()
    future["observed_at"] = (
        datetime.now(timezone.utc) + timedelta(minutes=5, seconds=1)
    ).isoformat().replace("+00:00", "Z")
    with pytest.raises(ActivationValidationError, match="future"):
        build_activation_receipt(future)


def test_activation_receipt_cli_is_operator_evidence_only(tmp_path: Path) -> None:
    evidence_path = tmp_path / "activation-evidence.json"
    evidence_path.write_text(json.dumps(_evidence()), encoding="utf-8")
    result = subprocess.run(
        [
            sys.executable,
            "-m",
            "app.ops.builderops_vm_rebuild_activation",
            "--evidence",
            str(evidence_path),
        ],
        cwd=ROOT,
        check=False,
        capture_output=True,
        text=True,
    )

    assert result.returncode == 0, result.stderr
    assert json.loads(result.stdout)["claims"]["activation_proven"] is True
    assert "host access" in (ROOT / "app/ops/builderops_vm_rebuild_activation.py").read_text().lower()
