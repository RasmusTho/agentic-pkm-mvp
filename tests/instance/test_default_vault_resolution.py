"""MVR-02 (#3856): explicit instance default and fail-closed selection precedence.

Contract: docs/MULTI_VAULT_RUNTIME/RESOLVE_INSTANCE_DEFAULT_VAULT.md
"""

from __future__ import annotations

from pathlib import Path

import pytest

from app.instance.default_vault import (
    SELECTION_INSTANCE_DEFAULT,
    SELECTION_LEGACY_BOOTSTRAP,
    SELECTION_NO_VAULT,
    SELECTION_REQUEST_OVERRIDE,
    SELECTION_SESSION,
    InstanceDefaultVaultService,
    VaultSelectionError,
    resolve_vault_selection,
)
from app.instance._storage_boundary import _STORAGE_MUTATION_CAPABILITY
from app.instance.vault_registry import (
    DEFAULT_PROVENANCE_EXPLICIT,
    DEFAULT_PROVENANCE_FIRST_INITIALIZE,
    DEFAULT_PROVENANCE_LEGACY_MIGRATION,
    KnownVaultRef,
    RegistryDefaultConflict,
    VaultRegistryStore,
)
from app.vault.markdown_settings import MarkdownSettingsStore
from tests._mvr_default_vault_harness import (
    activate,
    active_runtime,
    new_runtime,
    reopen_runtime,
)


def _service(runtime) -> InstanceDefaultVaultService:
    # No outbox/DB in these unit-level tests: the event contract itself is proven
    # by tests/api/test_default_vault_admin.py against the production emitter.
    return InstanceDefaultVaultService(runtime.registry, emit_event=lambda receipt: "")


def test_production_resolution_precedence_is_explicit(tmp_path) -> None:
    runtime, first, extra = active_runtime(tmp_path, extra_roots=("two", "three"))
    session_binding, override_binding = extra
    service = _service(runtime)
    service.set(first.vault_binding_id)

    snapshot = runtime.registry.load()

    # override > session > instance default > explicit legacy bootstrap > no-vault,
    # and every branch reports which one won.
    overridden = resolve_vault_selection(
        snapshot,
        request_override=override_binding.vault_binding_id,
        session_selection=session_binding.vault_binding_id,
        legacy_bootstrap_vault_root=Path(first.path),
    )
    assert overridden.vault_binding_id == override_binding.vault_binding_id
    assert overridden.provenance == SELECTION_REQUEST_OVERRIDE

    sessioned = resolve_vault_selection(
        snapshot,
        session_selection=session_binding.vault_binding_id,
        legacy_bootstrap_vault_root=Path(first.path),
    )
    assert sessioned.vault_binding_id == session_binding.vault_binding_id
    assert sessioned.provenance == SELECTION_SESSION

    defaulted = resolve_vault_selection(
        snapshot, legacy_bootstrap_vault_root=Path(extra[0].path)
    )
    assert defaulted.vault_binding_id == first.vault_binding_id
    assert defaulted.provenance == SELECTION_INSTANCE_DEFAULT

    service.clear()
    cleared = runtime.registry.load()
    bootstrapped = resolve_vault_selection(
        cleared, legacy_bootstrap_vault_root=Path(session_binding.path)
    )
    assert bootstrapped.vault_binding_id == session_binding.vault_binding_id
    assert bootstrapped.provenance == SELECTION_LEGACY_BOOTSTRAP

    # Absence of every explicit input is a valid result, not an error.
    empty = resolve_vault_selection(cleared)
    assert empty.is_no_vault
    assert empty.provenance == SELECTION_NO_VAULT

    # A one-request override never persists into the retained session selection.
    assert (
        resolve_vault_selection(
            cleared, session_selection=session_binding.vault_binding_id
        ).vault_binding_id
        == session_binding.vault_binding_id
    )


def test_invalid_explicit_selection_never_falls_through(tmp_path) -> None:
    runtime, first, extra = active_runtime(tmp_path, extra_roots=("two",))
    service = _service(runtime)
    service.set(first.vault_binding_id)
    snapshot = runtime.registry.load()
    cwd_decoy = tmp_path / "vault"
    cwd_decoy.mkdir()

    for kwargs in (
        {"request_override": "binding-does-not-exist"},
        {"session_selection": "binding-does-not-exist"},
    ):
        with pytest.raises(VaultSelectionError):
            resolve_vault_selection(
                snapshot,
                legacy_bootstrap_vault_root=Path(first.path),
                **kwargs,
            )

    # An unknown compatibility DEFAULT_VAULT_ID is a fail-closed lookup, never a
    # tiebreak against another registration.
    cleared = _service(runtime)
    cleared.clear()
    with pytest.raises(VaultSelectionError):
        resolve_vault_selection(
            runtime.registry.load(), compatibility_default_vault_id="vault-unknown"
        )

    # An unregistered root does not become a binding, and `./vault` is never it.
    with pytest.raises(VaultSelectionError):
        resolve_vault_selection(
            runtime.registry.load(), legacy_bootstrap_vault_root=cwd_decoy
        )

    # The failed selections changed nothing: last-active and the registration set
    # are untouched, and no vault was silently substituted.
    after = runtime.registry.load()
    assert after.last_active_vault_ref == snapshot.last_active_vault_ref
    assert set(after.registrations) == {
        first.vault_binding_id,
        extra[0].vault_binding_id,
    }

    # A default that is set can never be an unknown binding either.
    with pytest.raises(VaultSelectionError):
        _service(runtime).set("binding-does-not-exist")
    assert runtime.registry.load().default_vault_binding_id is None


def test_default_is_durable_and_distinct_from_last_active(tmp_path) -> None:
    runtime, first, extra = active_runtime(tmp_path, extra_roots=("two",))
    other = extra[0]
    service = _service(runtime)
    last_active_before = runtime.registry.load().last_active_vault_ref

    receipt = service.set(other.vault_binding_id)
    assert receipt.vault_binding_id == other.vault_binding_id
    assert receipt.provenance == DEFAULT_PROVENANCE_EXPLICIT
    # The redacted receipt carries no content-root path or vault name.
    assert set(receipt.as_dict()) == {
        "vault_binding_id",
        "provenance",
        "registry_revision",
        "previous_vault_binding_id",
        "changed",
    }

    # Restart: a brand new process re-attached to the same durable volume.
    restarted = reopen_runtime(runtime, tmp_path)
    snapshot = restarted.registry.load()
    assert snapshot.default_vault_binding_id == other.vault_binding_id
    assert snapshot.last_active_vault_ref == last_active_before
    assert (
        resolve_vault_selection(snapshot).vault_binding_id == other.vault_binding_id
    )

    # Clearing is equally durable and equally leaves last-active alone.
    _service(restarted).clear()
    after_clear = reopen_runtime(runtime, tmp_path).registry.load()
    assert after_clear.default_vault_binding_id is None
    assert after_clear.default_vault_provenance is None
    assert after_clear.last_active_vault_ref == last_active_before
    assert resolve_vault_selection(after_clear).is_no_vault
    assert first.vault_binding_id in after_clear.registrations


def test_legacy_last_active_materializes_default_once(tmp_path) -> None:
    # A picker-only single-vault legacy install: known vault plus last-active,
    # no explicit default anywhere.
    legacy_root = tmp_path / "picker-vault"
    legacy_root.mkdir()
    path = tmp_path / "vault-registry.md"
    MarkdownSettingsStore().write_frontmatter(
        path,
        {
            "schema": "design-handoff.app-local.v1",
            "scope": "app-local",
            "appInstallId": "app-legacy-picker",
            "lastActiveVaultRef": f"path:{legacy_root}",
            "knownVaults": {
                f"path:{legacy_root}": {
                    "path": str(legacy_root),
                    "vaultId": "vault-legacy",
                    "localInstanceId": "local-legacy",
                }
            },
        },
    )
    store = VaultRegistryStore(path)

    migrated = store.load_or_migrate()

    binding_id = next(iter(migrated.registrations))
    assert migrated.default_vault_binding_id == binding_id
    assert migrated.default_vault_provenance == DEFAULT_PROVENANCE_LEGACY_MIGRATION
    assert migrated.extensions["defaultVaultMigration"]["provenance"] == (
        DEFAULT_PROVENANCE_LEGACY_MIGRATION
    )
    # The restart journey is preserved: resolution lands on the same binding.
    assert (
        resolve_vault_selection(migrated).vault_binding_id == binding_id
    )
    assert resolve_vault_selection(migrated).provenance == SELECTION_INSTANCE_DEFAULT

    # Restart is stable and the migration does not run twice.
    reloaded = VaultRegistryStore(path).load_or_migrate()
    assert reloaded.revision == migrated.revision
    assert reloaded.default_vault_binding_id == binding_id

    # A later selection moves last-active only; the default is not a follower.
    _service_store = InstanceDefaultVaultService(store, emit_event=lambda receipt: "")
    _service_store.clear()
    cleared_revision = store.load().revision
    assert VaultRegistryStore(path).load_or_migrate().default_vault_binding_id is None
    assert VaultRegistryStore(path).load_or_migrate().revision == cleared_revision


def test_first_vault_initialize_materializes_default_once(tmp_path) -> None:
    runtime = new_runtime(tmp_path)
    root = tmp_path / "first-vault"
    root.mkdir()

    registration = runtime.register_first_vault(
        root, provenance=DEFAULT_PROVENANCE_FIRST_INITIALIZE
    )

    snapshot = runtime.registry.load()
    assert snapshot.default_vault_binding_id == registration.vault_binding_id
    assert snapshot.default_vault_provenance == DEFAULT_PROVENANCE_FIRST_INITIALIZE
    assert (
        resolve_vault_selection(snapshot).vault_binding_id
        == registration.vault_binding_id
    )

    # Registration and default landed in one revision: the transaction is atomic,
    # not two writes with a window where the binding has no restart source.
    assert snapshot.revision == 1

    # The producer is once-only: a second first-vault gesture is a conflict, not a
    # silent re-point of the explicit default.
    second_root = tmp_path / "second-vault"
    second_root.mkdir()
    with pytest.raises(RegistryDefaultConflict):
        runtime.register_first_vault(
            second_root, provenance=DEFAULT_PROVENANCE_FIRST_INITIALIZE
        )
    assert (
        runtime.registry.load().default_vault_binding_id
        == registration.vault_binding_id
    )

    # A later picker write moves last-active only; the default is not a follower.
    activate(runtime, registration, tmp_path)
    runtime.registry.remember_registration(
        registration.vault_binding_id,
        KnownVaultRef(
            ref=registration.ref,
            path=registration.path,
            vault_id=registration.vault_id,
            local_instance_id=registration.local_instance_id,
            vault_name="renamed-by-picker",
            last_opened_at="2026-08-01T00:00:00Z",
        ),
        make_active=True,
        _capability=_STORAGE_MUTATION_CAPABILITY,
    )
    after_picker = runtime.registry.load()
    assert after_picker.last_active_vault_ref == registration.ref
    assert after_picker.default_vault_binding_id == registration.vault_binding_id
    assert after_picker.default_vault_provenance == DEFAULT_PROVENANCE_FIRST_INITIALIZE
    # Restart still lands on the same binding without reselection.
    assert (
        reopen_runtime(runtime, tmp_path).registry.load().default_vault_binding_id
        == registration.vault_binding_id
    )
