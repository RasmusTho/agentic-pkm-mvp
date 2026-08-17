from __future__ import annotations

from app.instance._storage_boundary import _STORAGE_MUTATION_CAPABILITY
from app.instance.instance_state import InstanceStateLayout
from app.instance.runtime import InstanceRegistryRuntime
from app.instance.settings_rebind import SettingsRebindRecord
from app.instance.vault_registry import VaultRegistration
import pytest
import yaml


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


def test_delayed_writer_cannot_regress_durable_desired_or_applied_revision(tmp_path) -> None:
    """The registry lock, not a caller-supplied revision, owns monotonicity."""
    layout = InstanceStateLayout.for_channel(tmp_path / "state", "test")
    runtime = InstanceRegistryRuntime.for_paths(layout, tmp_path / "host")
    store = runtime.open_settings_rebind_store()
    for binding_id in ("binding-a", "binding-b"):
        runtime.registry.register(
            VaultRegistration(binding_id, f"path:/{binding_id}", f"/{binding_id}"),
            _capability=_STORAGE_MUTATION_CAPABILITY,
        )
    before = runtime.registry.load().revision
    store.install_dormant()
    installed = runtime.registry.load()
    assert installed.revision == before + 1
    assert installed.settings_rebind is not None
    assert installed.extensions["runtimeFloors"]["minimum_settings_rebind_runtime"] == "1"
    advanced = SettingsRebindRecord(1, 1, "committed", "watcher", "binding-a", "binding-b")
    runtime.registry.set_settings_rebind_state(
        advanced.as_payload(), _capability=_STORAGE_MUTATION_CAPABILITY
    )

    with pytest.raises(Exception, match="monotonic"):
        runtime.registry.set_settings_rebind_state(
            SettingsRebindRecord.dormant().as_payload(),
            _capability=_STORAGE_MUTATION_CAPABILITY,
        )

    assert store.read() == advanced


def test_record_cannot_mint_a_binding_outside_registry_authority(tmp_path) -> None:
    runtime = InstanceRegistryRuntime.for_paths(
        InstanceStateLayout.for_channel(tmp_path / "state", "test"), tmp_path / "host"
    )
    runtime.open_settings_rebind_store().install_dormant()
    forged = SettingsRebindRecord(1, 1, "committed", "watcher", "forged", "forged")

    with pytest.raises(Exception, match="outside registry authority"):
        runtime.registry.set_settings_rebind_state(
            forged.as_payload(), _capability=_STORAGE_MUTATION_CAPABILITY
        )


def test_current_schema_provisional_record_upgrades_atomically_on_first_read(tmp_path) -> None:
    layout = InstanceStateLayout.for_channel(tmp_path / "state", "test")
    runtime = InstanceRegistryRuntime.for_paths(layout, tmp_path / "host")
    registry = runtime.registry
    registered = registry.register(
        VaultRegistration("binding-a", "path:/vault-a", "/vault-a"),
        _capability=_STORAGE_MUTATION_CAPABILITY,
    )
    frontmatter = registry._frontmatter_from_snapshot(registered)
    frontmatter["settingsRebind"] = {
        "schema": "settings_rebind.v1",
        "prior": {"vaultBindingId": "binding-a"},
    }
    registry.path.write_text(
        "---\n" + yaml.safe_dump(frontmatter, sort_keys=False) + "---\n",
        encoding="utf-8",
    )

    upgraded = registry.load()

    assert upgraded.revision == registered.revision + 1
    assert upgraded.settings_rebind == SettingsRebindRecord.dormant(
        binding_id="binding-a"
    ).as_payload()
    assert upgraded.extensions["runtimeFloors"]["minimum_settings_rebind_runtime"] == "1"
