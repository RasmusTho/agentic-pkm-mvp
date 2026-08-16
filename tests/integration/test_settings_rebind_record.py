from __future__ import annotations

from app.instance._storage_boundary import _STORAGE_MUTATION_CAPABILITY
from app.instance.instance_state import InstanceStateLayout
from app.instance.runtime import InstanceRegistryRuntime
from app.instance.settings_rebind import SettingsRebindRecord
import pytest


def test_api_and_watcher_startup_share_one_dormant_rebind_revision(tmp_path) -> None:
    layout = InstanceStateLayout.for_channel(tmp_path / "state", "test")
    runtime = InstanceRegistryRuntime.for_paths(layout, tmp_path / "host")
    api = runtime.open_settings_rebind_store()
    record = api.install_dormant()
    watcher = runtime.open_settings_rebind_store()

    assert watcher.read() == record
    assert watcher.read().phase == "dormant"
    assert watcher.read().desired_revision == watcher.read().applied_revision == 0


def test_production_startup_recovers_every_dormant_record_phase_fail_closed(tmp_path) -> None:
    layout = InstanceStateLayout.for_channel(tmp_path / "state", "test")
    runtime = InstanceRegistryRuntime.for_paths(layout, tmp_path / "host")
    store = runtime.open_settings_rebind_store()
    store.install_dormant()
    payload = runtime.registry.load().settings_rebind
    assert payload is not None
    payload = dict(payload)
    payload["checksum"] = "not-a-checksum"

    try:
        runtime.registry.set_settings_rebind_state(
            payload, _capability=_STORAGE_MUTATION_CAPABILITY
        )
    except Exception as error:
        assert "checksum" in str(error)
    else:  # pragma: no cover - the assertion documents the fail-closed path
        raise AssertionError("invalid rebind state was accepted")

    assert store.read().phase == "dormant"


def test_startup_restores_last_complete_record_after_on_disk_checksum_corruption(tmp_path) -> None:
    layout = InstanceStateLayout.for_channel(tmp_path / "state", "test")
    runtime = InstanceRegistryRuntime.for_paths(layout, tmp_path / "host")
    store = runtime.open_settings_rebind_store()
    expected = store.install_dormant().as_payload()
    rendered = runtime.registry.path.read_text(encoding="utf-8")
    runtime.registry.path.write_text(
        rendered.replace(str(expected["checksum"]), "0" * 64), encoding="utf-8"
    )

    assert runtime.open_settings_rebind_store().read().as_payload() == expected


@pytest.mark.parametrize(
    ("phase", "posture", "desired", "applied"),
    [("dormant", "dormant", 2, 2), ("prepared", "watcher", 3, 2),
     ("committed", "watcher", 3, 3), ("no_lifecycle", "no_lifecycle", 3, 3)],
)
def test_each_persisted_phase_has_a_deterministic_revision_relation(
    phase, posture, desired, applied
) -> None:
    record = SettingsRebindRecord(desired, applied, phase, posture, "binding-a", "binding-b")
    assert SettingsRebindRecord.from_payload(record.as_payload()) == record


def test_invalid_phase_revision_relation_fails_before_record_write() -> None:
    record = SettingsRebindRecord(3, 2, "committed", "watcher", "binding-a", "binding-b")
    with pytest.raises(Exception, match="committed"):
        SettingsRebindRecord.from_payload(record.as_payload())
