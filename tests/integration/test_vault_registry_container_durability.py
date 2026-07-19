from __future__ import annotations

import hashlib
import json
import os
import subprocess
import sys
from pathlib import Path

from app.instance.instance_state import (
    DeploymentQuiescenceProof,
    InstanceStateLayout,
    LegacyRegistryFinalExport,
)
from app.instance.runtime import (
    _begin_instance_state_deployment,
    _bind_legacy_owner_inventory_to_proof,
    _prove_instance_state_quiescence,
)
from app.instance.vault_registry import AppLocalSettingsStore, KnownVaultRef


def _canonical_test_quiescence_authority(
    tmp_path: Path,
    layout: InstanceStateLayout,
    legacy_path: Path,
) -> tuple[DeploymentQuiescenceProof, Path, Path]:
    root = tmp_path / "host-global"
    root.mkdir(mode=0o700)
    layout.root.parent.mkdir(parents=True, exist_ok=True)
    controller = {"pid": os.getpid(), "start_token": "linux:" + "0" * 64}
    _begin_instance_state_deployment(
        channel="test",
        instance_state_root=layout.root.parent,
        host_global_root=root,
        legacy_path=legacy_path,
        controller_pid=controller["pid"],
        controller_start_token=controller["start_token"],
    )
    domains = {domain: [] for domain in ("dev", "native", "prod", "test")}
    empty_digest = hashlib.sha256(
        json.dumps(domains, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()
    inventory = root / "deployment-quiescence-inventory.json"
    inventory.write_text(
        json.dumps(
            {
                "schema": "agentic-pkm.host-deployment-quiescence.v2",
                "inventory_complete": True,
                "all_consumers_stopped": True,
                "probe_count": 2,
                "controller": controller,
                "domains": domains,
                "snapshot_digests": [empty_digest, empty_digest],
            }
        ),
        encoding="utf-8",
    )
    os.chmod(inventory, 0o600)
    proof = _prove_instance_state_quiescence(
        channel="test",
        host_global_root=root,
        inventory_path=inventory,
    )
    source_evidence = {"docker": [], "config": [], "owners": [], "owner_identities": []}
    owner_receipt = root / "legacy-owner-inventory.json"
    owner_receipt.write_text(
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
                "owners": [],
            }
        ),
        encoding="utf-8",
    )
    os.chmod(owner_receipt, 0o600)
    return (
        _bind_legacy_owner_inventory_to_proof(
            inventory_path=owner_receipt,
            quiescence_proof=proof,
            channel="test",
            host_global_root=root,
        ),
        root,
        owner_receipt,
    )


def _read_revision(path: Path, consumer: str) -> dict[str, object]:
    result = subprocess.run(
        [
            sys.executable,
            "-m",
            "app.instance.runtime",
            "read-revision",
            "--registry-path",
            str(path),
            "--consumer",
            consumer,
        ],
        check=True,
        capture_output=True,
        text=True,
    )
    return json.loads(result.stdout)


def test_registry_survives_recreate_and_is_shared_cross_process(tmp_path) -> None:
    layout = InstanceStateLayout.for_channel(tmp_path / "instance-state", "test")
    legacy = AppLocalSettingsStore(tmp_path / "legacy" / "app-local.md")
    legacy.upsert_known_vault(KnownVaultRef("path:one", str(tmp_path / "one")))
    exporter = LegacyRegistryFinalExport(layout)

    diagnostic = exporter.capture_diagnostic_snapshot(legacy.path)
    legacy.upsert_known_vault(KnownVaultRef("path:two", str(tmp_path / "two")))
    proof, host_global_root, owner_receipt = _canonical_test_quiescence_authority(
        tmp_path,
        layout,
        legacy.path,
    )
    final_export = exporter.export_final_after_stop(
        legacy.path,
        quiescence_proof=proof,
        host_global_root=host_global_root,
        owner_receipt_path=owner_receipt,
    )
    imported = exporter.import_final_export(
        final_export,
        quiescence_proof=proof,
        host_global_root=host_global_root,
        owner_receipt_path=owner_receipt,
    )

    assert diagnostic.fingerprint != final_export.fingerprint
    assert imported.revision == 1
    assert len(imported.registrations) == 2
    observations = {
        consumer: _read_revision(layout.registry_path, consumer)
        for consumer in ("api", "worker", "watcher", "heimdal-capture-watch")
    }
    assert {item["revision"] for item in observations.values()} == {1}
    assert {item["path_identity"] for item in observations.values()} == {
        str(layout.registry_path.resolve())
    }
