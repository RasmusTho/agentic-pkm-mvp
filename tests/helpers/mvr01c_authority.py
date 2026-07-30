from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path

from app.instance.instance_state import DeploymentQuiescenceProof
from app.instance.runtime import (
    InstanceRegistryRuntime,
    _begin_instance_state_deployment,
    _bind_legacy_owner_inventory_to_proof,
    _finish_instance_state_deployment,
    _prove_instance_state_quiescence,
)


def establish_authority_window(
    runtime: InstanceRegistryRuntime,
    scratch_root: Path,
) -> tuple[DeploymentQuiescenceProof, Path]:
    """Create the durable stopped-window evidence required by authority tests."""

    controller = {
        "pid": os.getpid(),
        "start_token": "linux:" + "0" * 64,
    }
    _begin_instance_state_deployment(
        channel=runtime.layout.channel_id,
        instance_state_root=runtime.layout.root.parent,
        host_global_root=runtime.ledger.root,
        legacy_path=scratch_root / "missing-legacy.md",
        controller_pid=controller["pid"],
        controller_start_token=controller["start_token"],
    )
    domains = {domain: [] for domain in ("dev", "native", "prod", "test")}
    inventory_digest = hashlib.sha256(
        json.dumps(domains, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()
    quiescence_inventory = (
        runtime.ledger.root / "deployment-quiescence-inventory.json"
    )
    quiescence_inventory.write_text(
        json.dumps(
            {
                "schema": "agentic-pkm.host-deployment-quiescence.v2",
                "inventory_complete": True,
                "all_consumers_stopped": True,
                "probe_count": 2,
                "controller": controller,
                "domains": domains,
                "snapshot_digests": [inventory_digest, inventory_digest],
            }
        ),
        encoding="utf-8",
    )
    quiescence_inventory.chmod(0o600)
    proof = _prove_instance_state_quiescence(
        channel=runtime.layout.channel_id,
        host_global_root=runtime.ledger.root,
        inventory_path=quiescence_inventory,
    )
    registry = runtime.registry.load()
    owners = [
        {
            "channel_id": lease.channel_id,
            "vault_binding_id": binding_id,
            "root": registry.registrations[binding_id].path,
        }
        for binding_id, lease in runtime.ledger.load().leases.items()
    ]
    owner_identities = []
    for owner in owners:
        metadata = os.stat(owner["root"])
        owner_identities.append(
            {
                "channel_id": owner["channel_id"],
                "root": owner["root"],
                "identity": f"inode:{metadata.st_dev}:{metadata.st_ino}",
            }
        )
    source_evidence = {
        "docker": [],
        "config": [],
        "owners": owners,
        "owner_identities": owner_identities,
    }
    owner_inventory = runtime.ledger.root / "legacy-owner-inventory.json"
    owner_inventory.write_text(
        json.dumps(
            {
                "schema": "agentic-pkm.legacy-owner-inventory.v1",
                "inventory_complete": True,
                "writers_drained": True,
                "source_probe_count": 2,
                "validated_after_quiescence": True,
                "source_digest": hashlib.sha256(
                    json.dumps(
                        source_evidence,
                        sort_keys=True,
                        separators=(",", ":"),
                    ).encode()
                ).hexdigest(),
                "source_evidence": source_evidence,
                "owners": owners,
            }
        ),
        encoding="utf-8",
    )
    owner_inventory.chmod(0o600)
    bound = _bind_legacy_owner_inventory_to_proof(
        inventory_path=owner_inventory,
        quiescence_proof=proof,
        channel=runtime.layout.channel_id,
        host_global_root=runtime.ledger.root,
    )
    return bound, owner_inventory


def finish_authority_window(
    runtime: InstanceRegistryRuntime,
    scratch_root: Path,
    proof: DeploymentQuiescenceProof,
    inventory_path: Path,
) -> None:
    _finish_instance_state_deployment(
        channel=runtime.layout.channel_id,
        instance_state_root=runtime.layout.root.parent,
        host_global_root=runtime.ledger.root,
        legacy_path=scratch_root / "missing-legacy.md",
        inventory_path=inventory_path,
        backup_root=scratch_root / "authority-backup",
        restore_root=None,
        quiescence_proof=proof,
    )
