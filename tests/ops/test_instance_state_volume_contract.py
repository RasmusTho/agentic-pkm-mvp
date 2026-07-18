from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

from app.instance.instance_state import (
    InstanceStateBackup,
    InstanceStateLayout,
    InstanceStatePreflightError,
    LegacyRegistryFinalExport,
    preflight_instance_state,
    validate_registry_disjoint_from_content,
)
from app.instance.runtime import InstanceRegistryRuntime
from app.instance.vault_registry import (
    AppLocalSettingsStore,
    CapabilityNotReadyError,
    KnownVaultRef,
    RegistryActivationProof,
    VaultRegistration,
    VaultRegistryStore,
)
from app.release_channels.channel_isolation_preflight import _load_compose
from app.vault.manager import VaultManager


def test_mvr01a_schema_activation_requires_rollback_capability(tmp_path) -> None:
    registry_path = tmp_path / "vault-registry.md"
    store = VaultRegistryStore(registry_path)
    store.register(VaultRegistration("binding-a", "path:/a", "/a"))

    with pytest.raises(CapabilityNotReadyError, match="MVR-01B rollback exporter/transformer"):
        store.require_authoritative_activation(RegistryActivationProof())

    with pytest.raises(CapabilityNotReadyError, match="MVR-01C authority cutover"):
        store.require_authoritative_activation(
            RegistryActivationProof(
                rollback_exporter=True,
                rollback_transformer=True,
                previous_image_preflight=True,
            )
        )

    assert store.load().authority == "dormant"

    legacy_path = tmp_path / "app-local.md"
    vault_path = tmp_path / "vault"
    manager = VaultManager(app_local_store=AppLocalSettingsStore(legacy_path))
    manager.initialize_vault(vault_path, remember=True)
    assert AppLocalSettingsStore(legacy_path).load().known_vaults
    assert VaultRegistryStore(registry_path).load().revision == 1


def test_legacy_registry_export_happens_after_writer_quiescence(tmp_path) -> None:
    layout = InstanceStateLayout.for_channel(tmp_path / "instance-state", "test")
    legacy = AppLocalSettingsStore(tmp_path / "legacy" / "app-local.md")
    manager = VaultManager(app_local_store=legacy)
    manager.initialize_vault(tmp_path / "vault-one", remember=True)
    exporter = LegacyRegistryFinalExport(layout)
    diagnostic = exporter.capture_diagnostic_snapshot(legacy.path)
    manager.initialize_vault(tmp_path / "vault-two", remember=True)

    with pytest.raises(InstanceStatePreflightError, match="drained and stopped"):
        exporter.export_final_after_stop(
            legacy.path,
            writers_drained=False,
            old_api_stopped=True,
            restart_fence_active=True,
        )
    final = exporter.export_final_after_stop(
        legacy.path,
        writers_drained=True,
        old_api_stopped=True,
        restart_fence_active=True,
    )
    assert final.fingerprint != diagnostic.fingerprint

    legacy.upsert_known_vault(KnownVaultRef("racing", str(tmp_path / "racing")))
    with pytest.raises(InstanceStatePreflightError, match="changed after final export"):
        exporter.import_final_export(final)


def test_registry_volume_and_preflight_cover_all_consumers(tmp_path) -> None:
    layout = InstanceStateLayout.for_channel(tmp_path / "instance-state", "dev")
    layout.ensure()
    receipt = preflight_instance_state(
        layout,
        consumer_paths={
            "api": layout.registry_path,
            "worker": layout.registry_path,
            "watcher": layout.registry_path,
            "heimdal-capture-watch": layout.registry_path,
        },
    )
    assert set(receipt.consumers) == {"api", "worker", "watcher", "heimdal-capture-watch"}
    with pytest.raises(InstanceStatePreflightError):
        preflight_instance_state(layout, consumer_paths={"api": layout.registry_path})
    with pytest.raises(InstanceStatePreflightError, match="resolve identically"):
        preflight_instance_state(
            layout,
            consumer_paths={name: layout.registry_path for name in receipt.consumers} | {"worker": tmp_path / "elsewhere"},
        )

    compose = _load_compose(Path(__file__).resolve().parents[2] / "docker-compose.yaml")
    assert "instance-state" in compose["volumes"]
    init = compose["services"]["instance-state-init"]
    assert "instance-state:/app/instance-state" in init["volumes"]
    assert any("/app/instance-ownership" in mount for mount in init["volumes"])
    for consumer in receipt.consumers:
        service = compose["services"][consumer]
        assert "instance-state:/app/instance-state" in service["volumes"]
        assert any("/app/instance-ownership" in mount for mount in service["volumes"])
        assert "app.instance.runtime preflight" in service["command"][2]
        assert f"--consumer {consumer}" in service["command"][2]
        assert service["depends_on"]["instance-state-init"]["condition"] == "service_completed_successfully"


def test_registry_override_cannot_become_content_owned(tmp_path) -> None:
    root = tmp_path / "vault"
    root.mkdir()
    alias = tmp_path / "vault-alias"
    alias.symlink_to(root, target_is_directory=True)
    with pytest.raises(InstanceStatePreflightError, match="content root"):
        validate_registry_disjoint_from_content(root / "private" / "registry.md", [alias])

    safe = tmp_path / "instance-state" / "registry.md"
    validate_registry_disjoint_from_content(safe, [])
    with pytest.raises(InstanceStatePreflightError, match="content root"):
        validate_registry_disjoint_from_content(safe, [tmp_path])

    content_state = root / "private-state"
    result = subprocess.run(
        [
            sys.executable,
            "-m",
            "app.instance.runtime",
            "preflight",
            "--channel",
            "dev",
            "--instance-state-root",
            str(content_state),
            "--host-global-root",
            str(tmp_path / "host-global"),
            "--consumer",
            "api",
        ],
        check=False,
        capture_output=True,
        text=True,
        env={**os.environ, "LLM_PROVIDER": "mock", "VAULT_ROOT": str(alias)},
    )
    assert result.returncode != 0
    assert "content root" in result.stderr
    assert not content_state.joinpath("agentic-pkm").exists()


def test_prod_instance_state_and_ledger_survive_volume_loss_with_verified_restore(tmp_path) -> None:
    repo_root = Path(__file__).resolve().parents[2]
    prod = _load_compose(repo_root / "docker-compose.prod.yml")
    assert prod["volumes"]["instance-state"] == {
        "external": True,
        "name": "pkm-prod_instance-state",
    }
    for producer in ("scripts/deploy_channel.sh", "scripts/start_full_system.sh"):
        text = (repo_root / producer).read_text(encoding="utf-8")
        assert "ensure_prod_instance_state_volume" in text
        assert "docker volume create" in text

    layout = InstanceStateLayout.for_channel(tmp_path / "prod-state", "prod")
    runtime = InstanceRegistryRuntime.for_paths(layout, tmp_path / "host-global")
    root = tmp_path / "vault"
    root.mkdir()
    runtime.bootstrap_env_binding(vault_root=root, watcher_vault_path=root)
    runtime.registry.set_extension_state(
        default_vault_binding_id="binding-default",
        dimensions={"d": ["binding-default"]},
        principal_state={"operator": "local"},
        background_state={"mode": "compatibility"},
        runtime_floors={"registry": "01b"},
    )
    backup = InstanceStateBackup(layout, runtime.ledger).create(tmp_path / "backup")
    expected = json.loads(backup.manifest_path.read_text(encoding="utf-8"))
    assert {
        "vault-registry.md.last-good",
        "vault-registry.md.last-good.sha256",
    } <= expected["checksums"].keys()

    for path in layout.root.iterdir():
        if path.is_file():
            path.unlink()
    for path in runtime.ledger.root.iterdir():
        if path.is_file():
            path.unlink()
    restored = InstanceStateBackup(layout, runtime.ledger).restore(
        tmp_path / "backup",
        live_channels=(),
    )
    assert restored.registry_checksum == expected["registry_checksum"]
    assert runtime.registry.load().extensions["runtimeFloors"] == {"registry": "01b"}
    assert runtime.ledger.load().leases

    layout.registry_path.unlink()
    assert runtime.registry.load().extensions["runtimeFloors"] == {"registry": "01b"}
    layout.registry_path.write_bytes(b"torn registry write")
    os.chmod(layout.registry_path, 0o600)
    assert runtime.registry.load().extensions["runtimeFloors"] == {"registry": "01b"}

    (tmp_path / "backup" / "ownership-key.json").unlink()
    with pytest.raises(InstanceStatePreflightError, match="complete ledger/key"):
        InstanceStateBackup(layout, runtime.ledger).restore(tmp_path / "backup", live_channels=())


def test_prod_restore_rejects_foreign_channel_before_writing_target_state(tmp_path) -> None:
    source_layout = InstanceStateLayout.for_channel(tmp_path / "dev-state", "dev")
    source_runtime = InstanceRegistryRuntime.for_paths(
        source_layout,
        tmp_path / "dev-host-global",
    )
    source_root = tmp_path / "dev-vault"
    source_root.mkdir()
    source_runtime.bootstrap_env_binding(
        vault_root=source_root,
        watcher_vault_path=source_root,
    )
    InstanceStateBackup(source_layout, source_runtime.ledger).create(
        tmp_path / "dev-backup"
    )

    target_layout = InstanceStateLayout.for_channel(tmp_path / "prod-state", "prod")
    target_runtime = InstanceRegistryRuntime.for_paths(
        target_layout,
        tmp_path / "prod-host-global",
    )
    target_root = tmp_path / "prod-vault"
    target_root.mkdir()
    target_runtime.bootstrap_env_binding(
        vault_root=target_root,
        watcher_vault_path=target_root,
    )
    target_runtime.registry.set_extension_state(
        default_vault_binding_id="prod-default",
        dimensions={"prod": ["prod-default"]},
        principal_state={"operator": "prod"},
        background_state={"mode": "prod"},
        runtime_floors={"registry": "prod"},
    )

    target_roots = (target_layout.root, target_runtime.ledger.root)
    before = {
        path.relative_to(tmp_path): path.read_bytes()
        for root in target_roots
        for path in root.iterdir()
        if path.is_file()
    }

    with pytest.raises(InstanceStatePreflightError, match="channel_id"):
        InstanceStateBackup(target_layout, target_runtime.ledger).restore(
            tmp_path / "dev-backup",
            live_channels=(),
        )

    after = {
        path.relative_to(tmp_path): path.read_bytes()
        for root in target_roots
        for path in root.iterdir()
        if path.is_file()
    }
    assert after == before
