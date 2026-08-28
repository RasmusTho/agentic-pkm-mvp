from __future__ import annotations

from pathlib import Path

import pytest

from app.instance._storage_boundary import RegistryError
from app.instance.instance_state import InstanceStateLayout
from app.instance.runtime import InstanceRegistryRuntime
from app.instance.settings_rebind import SettingsRebindRecord
from app.instance.vault_registry import VaultRegistration
from tests.helpers.instance_storage_capability import STORAGE_MUTATION_CAPABILITY


def _runtime(root: Path) -> InstanceRegistryRuntime:
    return InstanceRegistryRuntime.for_paths(
        InstanceStateLayout.for_channel(root / "state", "test"),
        root / "ownership",
    )


def _register(runtime: InstanceRegistryRuntime, binding_id: str) -> None:
    runtime.registry.register(
        VaultRegistration(binding_id, f"path:/{binding_id}", f"/{binding_id}"),
        _capability=STORAGE_MUTATION_CAPABILITY,
    )


def test_api_and_watcher_startup_share_one_dormant_rebind_revision(tmp_path: Path) -> None:
    runtime = _runtime(tmp_path)
    _register(runtime, "binding-a")
    installed = runtime.open_settings_rebind_store().install_dormant(
        binding_id="binding-a"
    )

    api_runtime = _runtime(tmp_path)
    watcher_runtime = _runtime(tmp_path)
    api_record = api_runtime.open_settings_rebind_store().read()
    watcher_record = watcher_runtime.open_settings_rebind_store().read()

    assert api_record == watcher_record == installed
    assert api_runtime.registry.load().revision == watcher_runtime.registry.load().revision
    assert api_record.schema_revision == 1
    assert api_record.prior_binding_id == api_record.candidate_binding_id == "binding-a"


@pytest.mark.parametrize(
    ("phase", "posture", "desired", "applied"),
    [
        ("dormant", "dormant", 0, 0),
        ("prepared", "watcher", 1, 0),
        ("committed", "watcher", 1, 1),
        ("no_lifecycle", "no_lifecycle", 1, 1),
    ],
)
def test_production_startup_recovers_every_dormant_record_phase_fail_closed(
    tmp_path: Path,
    phase: str,
    posture: str,
    desired: int,
    applied: int,
) -> None:
    runtime = _runtime(tmp_path / phase)
    _register(runtime, "binding-a")
    store = runtime.open_settings_rebind_store()
    store.install_dormant(binding_id="binding-a")
    expected = SettingsRebindRecord(
        schema_revision=1,
        desired_revision=desired,
        applied_revision=applied,
        phase=phase,
        lifecycle_posture=posture,
        prior_binding_id="binding-a",
        candidate_binding_id="binding-a",
    )
    runtime.registry.set_settings_rebind_state(
        expected.as_payload(),
        _capability=STORAGE_MUTATION_CAPABILITY,
    )

    rendered = runtime.registry.path.read_text(encoding="utf-8")
    runtime.registry.path.write_text(
        rendered.replace(str(expected.as_payload()["checksum"]), "0" * 64),
        encoding="utf-8",
    )

    restarted = _runtime(tmp_path / phase)
    assert restarted.open_settings_rebind_store().read() == expected

    malformed = expected.as_payload()
    malformed["appliedRevision"] = desired + 1
    malformed["checksum"] = "0" * 64
    with pytest.raises(RegistryError, match="checksum|revision"):
        runtime.registry.set_settings_rebind_state(
            malformed,
            _capability=STORAGE_MUTATION_CAPABILITY,
        )
    assert restarted.open_settings_rebind_store().read() == expected


def test_delayed_writer_cannot_regress_durable_rebind_revision(tmp_path: Path) -> None:
    runtime = _runtime(tmp_path)
    _register(runtime, "binding-a")
    store = runtime.open_settings_rebind_store()
    store.install_dormant(binding_id="binding-a")
    committed = SettingsRebindRecord(
        schema_revision=1,
        desired_revision=1,
        applied_revision=1,
        phase="committed",
        lifecycle_posture="watcher",
        prior_binding_id="binding-a",
        candidate_binding_id="binding-a",
    )
    runtime.registry.set_settings_rebind_state(
        committed.as_payload(),
        _capability=STORAGE_MUTATION_CAPABILITY,
    )

    with pytest.raises(RegistryError, match="monotonic"):
        runtime.registry.set_settings_rebind_state(
            SettingsRebindRecord.dormant(binding_id="binding-a").as_payload(),
            _capability=STORAGE_MUTATION_CAPABILITY,
        )
    assert store.read() == committed
