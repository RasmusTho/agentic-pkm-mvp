from __future__ import annotations

from pathlib import Path

import pytest

from app.instance._storage_boundary import CapabilityNotReadyError
from app.instance.instance_state import InstanceStateLayout
from app.instance.runtime import InstanceRegistryRuntime, _preflight_scalar_rollback
from app.instance.scalar_rollback_guard import (
    preflight_scalar_rollback_guard,
    require_native_scalar_launcher,
)
from tests.helpers.instance_storage_capability import STORAGE_MUTATION_CAPABILITY


REPO_ROOT = Path(__file__).resolve().parents[2]


def _runtime(tmp_path):
    runtime = InstanceRegistryRuntime.for_paths(
        InstanceStateLayout.for_channel(tmp_path / "instance-state", "prod"),
        tmp_path / "host-global",
    )
    root = tmp_path / "selected"
    root.mkdir()
    registration = runtime.bootstrap_env_binding(vault_root=root, watcher_vault_path=root)
    receipt = preflight_scalar_rollback_guard(
        compose_overlay=REPO_ROOT / "docker-compose.scalar-rollback.yml",
        gateway_config=REPO_ROOT / "ops/scalar-rollback/nginx.conf",
        native_launcher=REPO_ROOT / "scripts/scalar_rollback_native.sh",
        rollback_vault_binding_id=registration.vault_binding_id,
        selected_root=root,
    )
    runtime.activate_authority(
        guard_receipt=receipt,
    )
    return runtime, registration, root


def test_rollback_gateway_and_mounts_enforce_selected_binding(tmp_path) -> None:
    _, registration, root = _runtime(tmp_path)

    receipt = preflight_scalar_rollback_guard(
        compose_overlay=REPO_ROOT / "docker-compose.scalar-rollback.yml",
        gateway_config=REPO_ROOT / "ops/scalar-rollback/nginx.conf",
        native_launcher=REPO_ROOT / "scripts/scalar_rollback_native.sh",
        rollback_vault_binding_id=registration.vault_binding_id,
        selected_root=root,
    )

    assert receipt.gateway_authenticated
    assert receipt.mutation_filtering
    assert receipt.direct_api_port_absent
    assert receipt.selected_mount_only
    deployment = (REPO_ROOT / "scripts/lib/instance_state_deployment.sh").read_text(
        encoding="utf-8"
    )
    assert "python -m app.instance.runtime authority-cutover" in deployment
    assert "--rollback-vault-binding-id" in deployment


def test_native_scalar_rollback_launcher_enforces_selected_binding_or_fails_closed(
    tmp_path,
) -> None:
    _, _, root = _runtime(tmp_path)

    with pytest.raises(CapabilityNotReadyError, match="root-owned"):
        require_native_scalar_launcher(
            launcher=REPO_ROOT / "scripts/scalar_rollback_native.sh",
            selected_root=root,
            effective_uid=1000,
        )


def test_binding_keyed_database_floor_blocks_scalar_runtime(tmp_path) -> None:
    runtime, registration, _ = _runtime(tmp_path)
    runtime.registry.set_extension_state(
        default_vault_binding_id=None,
        dimensions={},
        principal_state={},
        background_state={},
        runtime_floors={"minimumRuntimeSchema": "mvr-05"},
        _capability=STORAGE_MUTATION_CAPABILITY,
    )
    rollback_path = tmp_path / "rollback" / "app-local.md"

    with pytest.raises(CapabilityNotReadyError, match="before database or queue startup"):
        _preflight_scalar_rollback(
            registry_path=runtime.layout.registry_path,
            host_global_root=runtime.ledger.root,
            rollback_vault_binding_id=registration.vault_binding_id,
            legacy_path=rollback_path,
        )
    assert not rollback_path.exists()
