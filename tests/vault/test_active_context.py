from __future__ import annotations

from pathlib import Path

from app.vault.active_context import ActiveContextResolver
from app.vault.manager import VaultContext, no_vault_context


def test_selected_vault_context_maps_path_to_source_binding(tmp_path: Path) -> None:
    context = VaultContext(
        status="selected",
        active_vault_id="vault-1",
        active_vault_name="Research Vault",
        active_vault_path=str(tmp_path / "research"),
        settings_path=str(tmp_path / "research" / "settings"),
        local_instance_id="local-1",
        machine_role="testNode",
    )

    active_context = ActiveContextResolver().resolve(context)

    assert active_context.version == "active_context_set.v0"
    assert active_context.workspace.status == "unknown"
    assert active_context.scope.status == "unknown"
    assert active_context.sphere.status == "unknown"
    assert active_context.situated_identity.value == "local-1"
    assert active_context.principal_context.value == "testNode"
    assert active_context.topology_posture.value == "single-node"
    assert active_context.generation.status == "unknown"
    assert active_context.context_id.status == "unknown"
    assert active_context.context_id.value is None
    assert active_context.source_bindings[0].kind == "vault"
    assert active_context.source_bindings[0].binding_ref == str(tmp_path / "research")
    assert active_context.source_bindings[0].implementation_detail is True


def test_no_vault_context_explicitly_projects_zero_bindings() -> None:
    active_context = ActiveContextResolver().resolve(no_vault_context())

    assert active_context.version == "active_context_set.v0"
    assert active_context.degraded_mode is True
    assert active_context.source_bindings == ()
    assert active_context.workspace.status == "unknown"
    assert active_context.topology_posture.value == "single-node"
