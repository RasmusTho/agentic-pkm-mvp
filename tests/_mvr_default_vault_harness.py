"""Shared MVR-02 harness: build a real, authoritative instance registry.

The MVR-02 acceptance criteria require tests to drive *production* commands
rather than seeding the store, so these helpers build the same authoritative
registry the runtime builds at deployment time (env bootstrap, ownership ledger,
quiescence proof, MVR-01C authority cutover) and hand back the live runtime.
"""

from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path

from app.instance.instance_state import InstanceStateLayout
from app.instance.runtime import (
    InstanceRegistryRuntime,
    _begin_instance_state_deployment,
    _bind_legacy_owner_inventory_to_proof,
    _finish_instance_state_deployment,
    _prove_instance_state_quiescence,
)
from app.instance.scalar_rollback_guard import preflight_scalar_rollback_guard

REPO_ROOT = Path(__file__).resolve().parents[1]


def instance_state_root(tmp_path: Path) -> Path:
    """The durable MVR-01 instance-state volume root for this fixture."""

    return tmp_path / "instance-state"


def new_runtime(tmp_path: Path, *, channel: str = "prod") -> InstanceRegistryRuntime:
    return InstanceRegistryRuntime.for_paths(
        InstanceStateLayout.for_channel(instance_state_root(tmp_path), channel),
        tmp_path / "host-global",
    )


def reopen_runtime(
    runtime: InstanceRegistryRuntime, tmp_path: Path, *, channel: str = "prod"
) -> InstanceRegistryRuntime:
    """Re-attach a fresh process to the same durable instance-state volume.

    Nothing in-memory carries over: this is the restart / force-recreate shape.
    """

    return InstanceRegistryRuntime(
        InstanceStateLayout.for_channel(instance_state_root(tmp_path), channel),
        type(runtime.ledger)(runtime.ledger.root),
        initialize_layout=False,
    )


def guard_receipt(binding_id: str, root: Path):
    return preflight_scalar_rollback_guard(
        compose_overlay=REPO_ROOT / "docker-compose.scalar-rollback.yml",
        gateway_config=REPO_ROOT / "ops/scalar-rollback/nginx.conf",
        native_launcher=REPO_ROOT / "scripts/scalar_rollback_native.sh",
        rollback_vault_binding_id=binding_id,
        selected_root=root,
    )


def deployment_authority(runtime: InstanceRegistryRuntime, legacy_path: Path):
    controller = {"pid": os.getpid(), "start_token": "linux:" + "0" * 64}
    _begin_instance_state_deployment(
        channel=runtime.layout.channel_id,
        instance_state_root=runtime.layout.root.parent,
        host_global_root=runtime.ledger.root,
        legacy_path=legacy_path,
        controller_pid=controller["pid"],
        controller_start_token=controller["start_token"],
    )
    empty_domains = {domain: [] for domain in ("dev", "native", "prod", "test")}
    empty_digest = hashlib.sha256(
        json.dumps(empty_domains, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()
    quiescence_inventory = runtime.ledger.root / "deployment-quiescence-inventory.json"
    quiescence_inventory.write_text(
        json.dumps(
            {
                "schema": "agentic-pkm.host-deployment-quiescence.v2",
                "inventory_complete": True,
                "all_consumers_stopped": True,
                "probe_count": 2,
                "controller": controller,
                "domains": empty_domains,
                "snapshot_digests": [empty_digest, empty_digest],
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
    owners = [
        {
            "channel_id": lease.channel_id,
            "vault_binding_id": binding_id,
            "root": runtime.registry.load().registrations[binding_id].path,
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
                        source_evidence, sort_keys=True, separators=(",", ":")
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


def activate(runtime: InstanceRegistryRuntime, first, tmp_path: Path) -> None:
    """Run the MVR-01C authority cutover for an already-registered binding."""

    proof, inventory = deployment_authority(runtime, tmp_path / "missing-legacy.md")
    runtime.activate_authority(
        guard_receipt=guard_receipt(first.vault_binding_id, Path(first.path)),
        inventory_path=inventory,
        quiescence_proof=proof,
    )
    _finish_instance_state_deployment(
        channel=runtime.layout.channel_id,
        instance_state_root=runtime.layout.root.parent,
        host_global_root=runtime.ledger.root,
        legacy_path=tmp_path / "missing-legacy.md",
        inventory_path=inventory,
        backup_root=tmp_path / "authority-backup",
        restore_root=None,
        quiescence_proof=proof,
    )


def active_runtime(tmp_path: Path, *, extra_roots: tuple[str, ...] = ()):
    """An authoritative registry bootstrapped from env plus optional extra bindings."""

    runtime = new_runtime(tmp_path)
    root = tmp_path / "one"
    root.mkdir()
    first = runtime.bootstrap_env_binding(vault_root=root, watcher_vault_path=root)
    activate(runtime, first, tmp_path)
    extra = []
    for name in extra_roots:
        extra_root = tmp_path / name
        extra_root.mkdir()
        extra.append(runtime.production_register(extra_root, producer="api"))
    return runtime, first, tuple(extra)


__all__ = [
    "activate",
    "active_runtime",
    "deployment_authority",
    "guard_receipt",
    "instance_state_root",
    "new_runtime",
    "reopen_runtime",
]
