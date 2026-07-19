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
from app.instance.vault_registry import AppLocalSettingsStore, KnownVaultRef


def _durable_test_quiescence_proof(tmp_path: Path) -> DeploymentQuiescenceProof:
    root = tmp_path / "proof"
    root.mkdir(mode=0o700)
    lease_path = root / "deployment-host-global-lease.json"
    inventory_digest = hashlib.sha256(b"test").hexdigest()
    lease_path.write_text(
        json.dumps(
            {
                "schema": "agentic-pkm.host-deployment-lease.v2",
                "channel_id": "test",
                "nonce": "test-nonce",
                "phase": "proved",
                "inventory_digest": inventory_digest,
                "all_consumers_stopped": True,
            }
        ),
        encoding="utf-8",
    )
    os.chmod(lease_path, 0o600)
    return DeploymentQuiescenceProof(
        channel_id="test",
        nonce="test-nonce",
        inventory_digest=inventory_digest,
        lease_path=lease_path,
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
    final_export = exporter.export_final_after_stop(
        legacy.path,
        quiescence_proof=_durable_test_quiescence_proof(tmp_path),
    )
    imported = exporter.import_final_export(final_export)

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
