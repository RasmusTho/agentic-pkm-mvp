from __future__ import annotations

import pytest

from app.instance._storage_boundary import CapabilityNotReadyError
from app.instance.instance_state import InstanceStateLayout
from app.instance.runtime import InstanceRegistryRuntime, _require_runtime_floor


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
