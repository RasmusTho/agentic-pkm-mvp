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


ENABLED_REGISTRY_CONSUMERS = ("api", "worker", "watcher", "heimdal-capture-watch")


def _instance_runtime(*args: str) -> dict[str, object]:
    """Run one headless instance-runtime command in its own process."""

    result = subprocess.run(
        [sys.executable, "-m", "app.instance.runtime", *args],
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


def test_default_survives_recreate_after_mvr02(tmp_path) -> None:
    """MVR-02 (#3856): the explicit default is instance-state volume state.

    Contract: docs/MULTI_VAULT_RUNTIME/RESOLVE_INSTANCE_DEFAULT_VAULT.md.
    A pinned-image force-recreate discards every process and every in-memory
    selection. Only the shared instance-state volume survives, and the explicit
    default must come back from it identically in every enabled consumer.
    """

    from app.instance.default_vault import (
        SELECTION_INSTANCE_DEFAULT,
        resolve_vault_selection,
    )
    from app.instance.vault_registry import DEFAULT_PROVENANCE_EXPLICIT
    from tests._mvr_default_vault_harness import active_runtime, reopen_runtime

    runtime, first, extra = active_runtime(tmp_path, extra_roots=("two",))
    registry_path = str(runtime.layout.registry_path)

    # The production headless command sets the default, in its own process.
    receipt = _instance_runtime(
        "default-vault-set",
        "--registry-path",
        registry_path,
        "--vault-binding-id",
        extra[0].vault_binding_id,
    )
    assert receipt["ok"] is True
    assert receipt["vault_binding_id"] == extra[0].vault_binding_id
    expected_revision = receipt["registry_revision"]

    # Force-recreate: every consumer re-runs its startup preflight against the
    # same volume, and nothing in-process carries over.
    for consumer in ENABLED_REGISTRY_CONSUMERS:
        subprocess.run(
            [
                sys.executable,
                "-m",
                "app.instance.runtime",
                "preflight",
                "--channel",
                runtime.layout.channel_id,
                "--instance-state-root",
                str(runtime.layout.root.parent),
                "--host-global-root",
                str(runtime.ledger.root),
                "--consumer",
                consumer,
            ],
            check=True,
            capture_output=True,
            text=True,
        )

    observations = {
        consumer: _instance_runtime(
            "default-vault-get",
            "--registry-path",
            registry_path,
            "--consumer",
            consumer,
        )
        for consumer in ENABLED_REGISTRY_CONSUMERS
    }
    assert {item["consumer"] for item in observations.values()} == set(
        ENABLED_REGISTRY_CONSUMERS
    )
    assert {item["vault_binding_id"] for item in observations.values()} == {
        extra[0].vault_binding_id
    }
    assert {item["registry_revision"] for item in observations.values()} == {
        expected_revision
    }
    assert {item["provenance"] for item in observations.values()} == {
        DEFAULT_PROVENANCE_EXPLICIT
    }
    assert {
        _read_revision(runtime.layout.registry_path, consumer)["revision"]
        for consumer in ENABLED_REGISTRY_CONSUMERS
    } == {expected_revision}

    # A re-attached in-process consumer resolves the identical selection, and the
    # recreate did not turn the default into last-active history.
    restored = reopen_runtime(runtime, tmp_path).registry.load()
    selection = resolve_vault_selection(restored)
    assert selection.vault_binding_id == extra[0].vault_binding_id
    assert selection.provenance == SELECTION_INSTANCE_DEFAULT
    # The recreate did not convert the default into last-active history: the env
    # bootstrap never wrote one, and setting a default must not invent one.
    assert restored.last_active_vault_ref is None
