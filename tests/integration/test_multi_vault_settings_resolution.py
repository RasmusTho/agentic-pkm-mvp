from pathlib import Path

import pytest

from app.instance.active_context_service import binding_revision_for
from app.instance.context_settings import (
    IncompatibleBindingSettingsError,
    resolve_context_settings,
)
from app.vault.active_context_v1 import (
    ActiveContextBinding,
    ActiveContextSetV1,
    PrincipalContext,
    WorkspaceState,
)
from app.vault.manager import VaultManager
from tests._mvr_default_vault_harness import activate, new_runtime


def test_many_binding_request_fails_before_effect_when_request_wide_settings_conflict(
    tmp_path: Path,
) -> None:
    """The production resolver rejects incompatible initialized binding settings."""

    runtime = new_runtime(tmp_path)
    first_root = tmp_path / "vault-a"
    second_root = tmp_path / "vault-b"
    VaultManager().initialize_vault(first_root, machine_role="testNode", remember=False)
    first = runtime.bootstrap_env_binding(vault_root=first_root, watcher_vault_path=first_root)
    activate(runtime, first, tmp_path)
    VaultManager().initialize_vault(
        second_root,
        machine_role="readOnlySatellite",
        remember=False,
    )
    runtime.production_register(second_root, producer="api")

    snapshot = runtime.registry.load()
    context = ActiveContextSetV1(
        context_id="settings-conflict",
        generation=1,
        workspace=WorkspaceState.none(),
        scope="default",
        sphere_memberships=(),
        situated_identity=None,
        principal_context=PrincipalContext(
            "operator",
            "human",
            "trusted_loopback",
        ),
        instance_identity=snapshot.app_install_id,
        source_bindings=tuple(
            ActiveContextBinding(
                registration.vault_binding_id,
                binding_revision_for(snapshot, registration.vault_binding_id),
                "settings-test",
            )
            for registration in snapshot.registrations.values()
        ),
        registry_revision=snapshot.revision,
        authorization_epoch="settings-test",
        selection_provenance="integration-test",
    )

    with pytest.raises(IncompatibleBindingSettingsError, match="incompatible_binding_settings"):
        resolve_context_settings(context, registry_store=runtime.registry)
