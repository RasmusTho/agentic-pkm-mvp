from __future__ import annotations

import pytest

from app.instance._storage_boundary import CapabilityNotReadyError
from app.instance.instance_state import InstanceStateLayout
from app.instance.runtime import InstanceRegistryRuntime, _require_runtime_floor
from app.instance.settings_rebind import SettingsRebindRecord


def test_rebind_floor_blocks_incompatible_api_and_watcher_before_start(tmp_path) -> None:
    runtime = InstanceRegistryRuntime.for_paths(
        InstanceStateLayout.for_channel(tmp_path / "state", "test"), tmp_path / "host"
    )
    snapshot = runtime.registry.load()
    snapshot.extensions["runtimeFloors"] = {"minimum_settings_rebind_runtime": "2"}

    with pytest.raises(CapabilityNotReadyError, match="settings rebind"):
        _require_runtime_floor(snapshot, scalar_runtime=False)


def test_rebind_floor_blocks_every_legacy_writer_after_cutover(tmp_path) -> None:
    runtime = InstanceRegistryRuntime.for_paths(
        InstanceStateLayout.for_channel(tmp_path / "state", "test"), tmp_path / "host"
    )
    store = runtime.open_settings_rebind_store()
    store.install_dormant()
    assert runtime.registry.load().extensions["runtimeFloors"]["minimum_settings_rebind_runtime"] == "1"


def test_rebind_floor_blocks_legacy_rollback_preflight_before_old_image_starts(tmp_path) -> None:
    runtime = InstanceRegistryRuntime.for_paths(
        InstanceStateLayout.for_channel(tmp_path / "state", "test"), tmp_path / "host"
    )
    runtime.open_settings_rebind_store().install_dormant()

    with pytest.raises(CapabilityNotReadyError, match="legacy scalar"):
        _require_runtime_floor(runtime.registry.load(), scalar_runtime=True)


def test_complete_record_without_floor_fails_closed_on_protected_store_read(tmp_path) -> None:
    runtime = InstanceRegistryRuntime.for_paths(
        InstanceStateLayout.for_channel(tmp_path / "state", "test"), tmp_path / "host"
    )
    snapshot = runtime.registry.load()
    malformed = runtime.registry._frontmatter_from_snapshot(snapshot)
    malformed["settingsRebind"] = SettingsRebindRecord.dormant().as_payload()

    with pytest.raises(Exception, match="requires its runtime floor"):
        runtime.registry._snapshot_from_frontmatter(malformed)


def test_floor_only_state_fails_closed_before_runtime_startup(tmp_path) -> None:
    runtime = InstanceRegistryRuntime.for_paths(
        InstanceStateLayout.for_channel(tmp_path / "state", "test"), tmp_path / "host"
    )
    snapshot = runtime.registry.load()
    malformed = runtime.registry._frontmatter_from_snapshot(snapshot)
    malformed["runtimeFloors"] = {"minimum_settings_rebind_runtime": "1"}

    with pytest.raises(Exception, match="requires its dormant record"):
        runtime.registry._snapshot_from_frontmatter(malformed)
