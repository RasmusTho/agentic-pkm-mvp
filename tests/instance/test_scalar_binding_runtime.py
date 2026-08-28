from __future__ import annotations

from pathlib import Path

from app.instance.scalar_binding_runtime import resolve_scalar_binding_runtime
from app.instance.vault_registry import VaultRegistration, VaultRegistryStore
from tests.helpers.instance_storage_capability import STORAGE_MUTATION_CAPABILITY


def test_dormant_registry_preserves_legacy_compatibility(
    tmp_path: Path, monkeypatch
) -> None:
    """MVR-01B keeps legacy scalar authority until explicit MVR-01C cutover."""

    root = tmp_path / "vault"
    root.mkdir()
    registry = VaultRegistryStore(tmp_path / "instance" / "vault-registry.md")
    registry.register(
        VaultRegistration("binding-a", f"path:{root}", str(root)),
        _capability=STORAGE_MUTATION_CAPABILITY,
    )
    monkeypatch.setenv("INSTANCE_VAULT_REGISTRY_PATH", str(registry.path))
    monkeypatch.setenv("INSTANCE_OWNERSHIP_ROOT", str(tmp_path / "ownership"))
    monkeypatch.setenv("VAULT_ROOT", str(root))

    assert resolve_scalar_binding_runtime(vault_root=root) is None
