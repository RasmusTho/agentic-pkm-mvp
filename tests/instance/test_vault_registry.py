from __future__ import annotations

import hashlib

import pytest

import app.instance.vault_registry as registry_module
from app.instance.filesystem_identity import FilesystemRootIdentity
from app.instance.vault_registry import RegistryError, VaultRegistration, VaultRegistryStore


def test_registry_round_trip_preserves_multiple_vaults(tmp_path) -> None:
    path = tmp_path / "instance-state" / "vault-registry.md"
    store = VaultRegistryStore(path)

    store.register(
        VaultRegistration(
            vault_binding_id="binding-a",
            ref="path:/vault/a",
            path="/vault/a",
            vault_id="logical-shared",
            local_instance_id="clone-a",
        )
    )
    store.register(
        VaultRegistration(
            vault_binding_id="binding-b",
            ref="path:/vault/b",
            path="/vault/b",
            vault_id="logical-shared",
            local_instance_id="clone-b",
        )
    )

    assert [item.vault_binding_id for item in store.list_registrations()] == ["binding-a", "binding-b"]
    assert store.lookup("binding-a") is not None
    updated = store.update_registration(
        VaultRegistration(
            vault_binding_id="binding-a",
            ref="path:/moved/a",
            path="/moved/a",
            vault_id="logical-shared",
            local_instance_id="clone-a",
        ),
        expected_revision=2,
    )
    assert updated.revision == 3

    with pytest.raises(RegistryError, match="stable registration identity cannot change"):
        store.update_registration(
            VaultRegistration(
                vault_binding_id="binding-a",
                ref="path:/moved/a",
                path="/moved/a",
                vault_id="logical-shared",
                local_instance_id="different-clone",
            ),
            expected_revision=3,
        )
    assert store.load().revision == 3

    with pytest.raises(RegistryError, match="registration ref and path are required"):
        store.update_registration(
            VaultRegistration(
                vault_binding_id="binding-a",
                ref="",
                path="",
                vault_id="logical-shared",
                local_instance_id="clone-a",
            ),
            expected_revision=3,
        )
    assert store.load().revision == 3

    store.register(VaultRegistration("binding-temporary", "path:/temporary", "/temporary"))
    store.remove_registration("binding-temporary", expected_revision=4)

    reloaded = VaultRegistryStore(path).load()
    assert reloaded.authority == "dormant"
    assert reloaded.revision == 5
    assert set(reloaded.registrations) == {"binding-a", "binding-b"}
    assert reloaded.registrations["binding-a"].vault_id == "logical-shared"
    assert reloaded.registrations["binding-a"].path == "/moved/a"
    assert reloaded.registrations["binding-a"].local_instance_id == "clone-a"
    assert reloaded.registrations["binding-b"].local_instance_id == "clone-b"


def test_persisted_registry_rejects_canonical_and_physical_identity_collisions(tmp_path, monkeypatch) -> None:
    canonical_path = tmp_path / "canonical.md"
    canonical_store = VaultRegistryStore(canonical_path)
    canonical_store.register(VaultRegistration("binding-a", "path:/vault/a", "/vault/a"))
    document = registry_module._read_document(canonical_path)
    document.frontmatter["registrations"]["binding-alias"] = {
        "ref": "alias:/vault/a",
        "path": "/vault/../vault/a",
    }
    payload = registry_module._render_markdown_settings(document.frontmatter, document.body).encode()
    canonical_path.write_bytes(payload)
    canonical_store.snapshot_path.write_bytes(payload)
    canonical_store.snapshot_checksum_path.write_text(hashlib.sha256(payload).hexdigest() + "\n")

    with pytest.raises(RegistryError, match="no unambiguous last-good snapshot"):
        canonical_store.load()

    physical_path = tmp_path / "physical.md"
    physical_store = VaultRegistryStore(physical_path)
    physical_store.register(VaultRegistration("binding-a", "path:/mount/a", "/mount/a"))
    physical_store.register(VaultRegistration("binding-b", "path:/mount/b", "/mount/b"))
    real_resolver = registry_module.resolve_filesystem_root_identity

    def same_inode(value):
        identity = real_resolver(value)
        if str(value) in {"/mount/a", "/mount/b"}:
            return FilesystemRootIdentity(identity.canonical_path, 41, 73)
        return identity

    monkeypatch.setattr(registry_module, "resolve_filesystem_root_identity", same_inode)
    with pytest.raises(RegistryError, match="no unambiguous last-good snapshot"):
        physical_store.load()
