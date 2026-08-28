from __future__ import annotations

from dataclasses import replace
from pathlib import Path

import pytest

from app.instance._storage_boundary import CapabilityNotReadyError, RegistryError
from app.instance.instance_state import InstanceStateLayout
from app.instance.runtime import InstanceRegistryRuntime, _require_runtime_floor
from app.instance.settings_rebind import SettingsRebindRecord
from app.instance.vault_registry import VaultRegistration
from tests.helpers.instance_storage_capability import STORAGE_MUTATION_CAPABILITY


REPO_ROOT = Path(__file__).resolve().parents[2]


def _runtime(root: Path) -> InstanceRegistryRuntime:
    return InstanceRegistryRuntime.for_paths(
        InstanceStateLayout.for_channel(root / "state", "test"),
        root / "ownership",
    )


def test_rebind_floor_blocks_incompatible_api_and_watcher_before_start(
    tmp_path: Path,
) -> None:
    runtime = _runtime(tmp_path)
    snapshot = runtime.registry.load()
    snapshot.extensions["runtimeFloors"] = {
        "minimum_settings_rebind_runtime": "2"
    }

    with pytest.raises(CapabilityNotReadyError, match="settings rebind"):
        _require_runtime_floor(snapshot, scalar_runtime=False)

    deploy = (REPO_ROOT / "scripts/deploy_channel.sh").read_text(encoding="utf-8")
    assert "settings-rebind-runtime-floor-${channel}.json" in deploy
    assert "app/instance/settings_rebind_runtime_capability.json" in deploy


def test_rebind_floor_blocks_every_legacy_writer_after_cutover(
    tmp_path: Path,
) -> None:
    runtime = _runtime(tmp_path)
    runtime.registry.register(
        VaultRegistration("binding-a", "path:/binding-a", "/binding-a"),
        _capability=STORAGE_MUTATION_CAPABILITY,
    )
    store = runtime.open_settings_rebind_store()
    record = store.install_dormant(binding_id="binding-a")

    runtime.registry.register(
        VaultRegistration("binding-b", "path:/binding-b", "/binding-b"),
        _capability=STORAGE_MUTATION_CAPABILITY,
    )
    after = runtime.registry.load()
    assert after.settings_rebind == record.as_payload()
    assert after.extensions["runtimeFloors"]["minimum_settings_rebind_runtime"] == "1"

    legacy_extension_write = runtime.registry.set_extension_state(
        principal_state={},
        background_state={},
        runtime_floors={"minimumRuntimeSchema": "scalar"},
        _capability=STORAGE_MUTATION_CAPABILITY,
    )
    assert legacy_extension_write.settings_rebind == record.as_payload()
    assert (
        legacy_extension_write.extensions["runtimeFloors"]
        ["minimum_settings_rebind_runtime"]
        == "1"
    )

    dropped = replace(after, revision=after.revision + 1, settings_rebind=None)
    with runtime.registry._locked():
        with pytest.raises(RegistryError, match="requires its dormant record"):
            runtime.registry._write_locked(dropped)

    incompatible = replace(
        after,
        extensions={
            **after.extensions,
            "runtimeFloors": {"minimum_settings_rebind_runtime": "2"},
        },
    )
    with pytest.raises(CapabilityNotReadyError, match="settings rebind"):
        _require_runtime_floor(incompatible, scalar_runtime=False)
    with pytest.raises(CapabilityNotReadyError, match="legacy scalar"):
        _require_runtime_floor(after, scalar_runtime=True)

    malformed = record.as_payload()
    malformed["checksum"] = "0" * 64
    with pytest.raises(RegistryError, match="checksum"):
        runtime.registry.set_settings_rebind_state(
            malformed,
            _capability=STORAGE_MUTATION_CAPABILITY,
        )
    assert runtime.registry.load().settings_rebind == record.as_payload()


def test_complete_record_and_floor_are_an_indivisible_registry_generation(
    tmp_path: Path,
) -> None:
    runtime = _runtime(tmp_path)
    snapshot = runtime.registry.load()
    record = SettingsRebindRecord.dormant().as_payload()
    without_floor = runtime.registry._frontmatter_from_snapshot(snapshot)
    without_floor["settingsRebind"] = record
    with pytest.raises(RegistryError, match="requires its runtime floor"):
        runtime.registry._snapshot_from_frontmatter(without_floor)

    floor_only = runtime.registry._frontmatter_from_snapshot(snapshot)
    floor_only["runtimeFloors"] = {"minimum_settings_rebind_runtime": "1"}
    with pytest.raises(RegistryError, match="requires its dormant record"):
        runtime.registry._snapshot_from_frontmatter(floor_only)
