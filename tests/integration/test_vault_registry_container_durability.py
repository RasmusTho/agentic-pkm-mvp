from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

from app.instance.instance_state import (
    DeploymentQuiescenceProof,
    InstanceStateLayout,
    LegacyRegistryFinalExport,
)
from app.instance.vault_registry import AppLocalSettingsStore, KnownVaultRef


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
        quiescence_proof=DeploymentQuiescenceProof.for_test("test"),
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
