from __future__ import annotations

from app.instance._storage_boundary import _STORAGE_MUTATION_CAPABILITY
from app.instance.instance_state import InstanceStateLayout
from app.instance.runtime import InstanceRegistryRuntime


def test_all_producers_match_production_rebind_schema_and_activation_seal(tmp_path) -> None:
    runtime = InstanceRegistryRuntime.for_paths(
        InstanceStateLayout.for_channel(tmp_path / "state", "test"), tmp_path / "host"
    )
    record = runtime.open_settings_rebind_store().install_dormant()
    snapshot = runtime.registry.load()

    assert snapshot.settings_rebind == record.as_payload()
    assert snapshot.extensions["runtimeFloors"]["minimum_settings_rebind_runtime"] == "1"
    assert not hasattr(runtime, "select_rebind_binding")
    assert not hasattr(runtime, "prepare_rebind")
    assert _STORAGE_MUTATION_CAPABILITY is not None
