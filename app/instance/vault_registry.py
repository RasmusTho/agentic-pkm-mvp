from __future__ import annotations

import base64
import binascii
import copy
import fcntl
import hashlib
import json
import os
import stat
import tempfile
from contextlib import contextmanager
from dataclasses import dataclass, field, replace
from datetime import datetime, timezone
from pathlib import Path
from typing import TYPE_CHECKING, Any, Iterable, Iterator, Mapping, Protocol
from uuid import uuid4

import yaml

from app.instance._storage_boundary import (
    CapabilityNotReadyError,
    RegistryError,
    _StorageMutationCapability,
    _require_storage_mutation_capability,
)
from app.instance.filesystem_identity import (
    FilesystemIdentityError,
    FilesystemRootIdentity,
    resolve_filesystem_root_identity,
    same_filesystem_root,
)
from app.receipts.settings_write import emit_settings_write_receipts_for_changes

if TYPE_CHECKING:
    from app.instance.runtime import InstanceRegistryRuntime


CURRENT_REGISTRY_SCHEMA = "agentic-pkm.instance-vault-registry.v1"
APP_LOCAL_SCHEMA = "design-handoff.app-local.v1"
REGISTRY_AUTHORITY_DORMANT = "dormant"
REGISTRY_AUTHORITY_ACTIVE = "active"
SCALAR_ROLLBACK_SCHEMA = "agentic-pkm.scalar-rollback-floor.v1"
ROLL_FORWARD_LINEAGE_SCHEMA = "agentic-pkm.scalar-roll-forward-lineage.v1"
_TRANSACTION_SCHEMA = "agentic-pkm.instance-vault-registry-transaction.v1"

# MVR-02 explicit-default provenance vocabulary. ``last_active_vault_ref`` is
# interaction history and never becomes a default outside the one-time migration.
DEFAULT_PROVENANCE_EXPLICIT = "explicit_default_command"
DEFAULT_PROVENANCE_LEGACY_MIGRATION = "legacy_last_active_migration"
DEFAULT_PROVENANCE_FIRST_INITIALIZE = "first_vault_initialize"
DEFAULT_PROVENANCE_FIRST_OPEN_EXISTING = "first_open_existing"
DEFAULT_PROVENANCE_ROLL_FORWARD_RESTORE = "roll_forward_restored"
# A default carried over from a pre-MVR-02 image, adopted because it resolved.
# It gets its own label rather than borrowing `explicit_default_command`: no
# operator command ever set it, and provenance is supposed to be inspectable.
DEFAULT_PROVENANCE_LEGACY_UNLABELLED = "legacy_unlabelled_adoption"
DEFAULT_VAULT_PROVENANCES = frozenset(
    {
        DEFAULT_PROVENANCE_EXPLICIT,
        DEFAULT_PROVENANCE_LEGACY_MIGRATION,
        DEFAULT_PROVENANCE_LEGACY_UNLABELLED,
        DEFAULT_PROVENANCE_FIRST_INITIALIZE,
        DEFAULT_PROVENANCE_FIRST_OPEN_EXISTING,
        DEFAULT_PROVENANCE_ROLL_FORWARD_RESTORE,
    }
)

_APP_DIR_NAME = "Agentic PKM"
_SETTINGS_FILENAME = "app-local.md"
_CONTAINER_RUNTIME_DIR = Path("/app/tmp")
_REGISTRY_FIELDS = {
    "schema",
    "authority",
    "revision",
    "appInstallId",
    "lastActiveVaultRef",
    "defaultVaultBindingId",
    "defaultVaultProvenance",
    "registrations",
    "removalTombstones",
    "transferLineage",
    "settingsRebind",
}
_REGISTRATION_FIELDS = {
    "ref",
    "path",
    "vaultId",
    "vaultName",
    "localInstanceId",
    "lastOpenedAt",
}


class RegistryMigrationError(RegistryError):
    """Legacy state cannot be migrated without guessing identity."""


class RegistryRevisionConflict(RegistryError):
    """A caller attempted to write from a stale registry revision."""


class RegistryParseError(RegistryError):
    """A registry Markdown payload is malformed."""


class RegistrySecurityError(RegistryError):
    """Registry path permissions, ownership, or type violate the private-state contract."""


class RegistryDefaultConflict(RegistryError):
    """A mutation would leave the explicit instance default dangling or inferred."""


def _binding_for_ref(
    ref: str | None, registrations: Mapping[str, VaultRegistration]
) -> str | None:
    """Resolve a legacy ``lastActiveVaultRef`` to exactly one binding, else ``None``."""

    if ref is None:
        return None
    matches = [
        binding_id for binding_id, item in registrations.items() if item.ref == ref
    ]
    return matches[0] if len(matches) == 1 else None


def _read_default_from_frontmatter(
    frontmatter: Mapping[str, Any],
    registrations: Mapping[str, VaultRegistration],
    extensions: dict[str, Any],
) -> tuple[str | None, str | None]:
    """Read the explicit default, tolerating a pre-MVR-02 unlabelled value.

    MVR-02 always writes ``defaultVaultBindingId`` and ``defaultVaultProvenance``
    together, so an id with **no** provenance is definitionally a value written
    before this field existed — MVR-01 flattened `extensions` into the same
    frontmatter, and `defaultVaultBindingId` was one of the keys it could carry.
    Such a value is untrusted: it is adopted only when it names exactly one
    current registration, and otherwise demoted to lineage. It is never an error,
    because refusing to load an otherwise intact registry would take every
    consumer's startup down on the exact population this slice upgrades.

    A *labelled* default is held to the full fail-closed contract below: a
    dangling binding or an unknown provenance is a hard error, because MVR-02
    itself wrote it and no writer is allowed to produce that state.
    """

    binding_id = _optional_str(frontmatter.get("defaultVaultBindingId"))
    provenance = _optional_str(frontmatter.get("defaultVaultProvenance"))
    if binding_id is not None and provenance is None:
        if binding_id in registrations:
            return binding_id, DEFAULT_PROVENANCE_LEGACY_UNLABELLED
        extensions["legacyDefaultVaultBindingId"] = binding_id
        return None, None
    _assert_default_is_resolvable(binding_id, provenance, registrations)
    return binding_id, provenance


def _assert_default_is_resolvable(
    default_vault_binding_id: str | None,
    default_vault_provenance: str | None,
    registrations: Mapping[str, VaultRegistration],
) -> None:
    """Fail closed on an unresolvable or unlabelled explicit instance default."""

    if default_vault_binding_id is None:
        if default_vault_provenance is not None:
            raise RegistryDefaultConflict(
                "default provenance is present without an explicit default binding"
            )
        return
    if default_vault_binding_id not in registrations:
        raise RegistryDefaultConflict(
            f"explicit instance default is not registered: {default_vault_binding_id}"
        )
    if default_vault_provenance not in DEFAULT_VAULT_PROVENANCES:
        raise RegistryDefaultConflict(
            f"unsupported default provenance: {default_vault_provenance or '<missing>'}"
        )


@dataclass(frozen=True)
class _RegistryDocument:
    frontmatter: dict[str, Any]
    body: str


class _MarkdownStore(Protocol):
    def read(self, path: Path) -> Any: ...

    def write_frontmatter(self, path: Path, frontmatter: Mapping[str, Any], *, body: str | None = None) -> None: ...


@dataclass(frozen=True)
class RegistryActivationProof:
    rollback_exporter: bool = False
    rollback_transformer: bool = False
    previous_image_preflight: bool = False
    rollback_vault_binding_id: str | None = None
    authenticated_gateway: bool = False
    native_guard: bool = False
    roll_forward_lineage: bool = False
    compose_policy_sha256: str | None = None
    gateway_policy_sha256: str | None = None
    native_launcher_sha256: str | None = None


@dataclass(frozen=True)
class VaultRegistration:
    vault_binding_id: str
    ref: str
    path: str
    vault_id: str | None = None
    local_instance_id: str | None = None
    vault_name: str | None = None
    last_opened_at: str | None = None
    extensions: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class RemovalTombstone:
    vault_binding_id: str
    ref: str
    path: str
    vault_id: str | None
    local_instance_id: str | None
    content_epoch: int


@dataclass(frozen=True)
class TransferLineage:
    source_binding_id: str
    destination_binding_id: str
    local_instance_id: str | None
    vault_id: str | None
    source_channel_id: str
    destination_channel_id: str
    source_registry_revision: int
    destination_registry_revision: int
    ownership_transfer_id: str


@dataclass(frozen=True)
class RegistrySnapshot:
    schema: str
    authority: str
    revision: int
    app_install_id: str
    last_active_vault_ref: str | None
    registrations: dict[str, VaultRegistration]
    removal_tombstones: dict[str, RemovalTombstone] = field(default_factory=dict)
    transfer_lineage: tuple[TransferLineage, ...] = ()
    settings_rebind: dict[str, Any] | None = None
    extensions: dict[str, Any] = field(default_factory=dict)
    default_vault_binding_id: str | None = None
    default_vault_provenance: str | None = None


class VaultRegistryStore:
    """Locked, atomic store for the dormant MVR registry schema.

    MVR-01A deliberately does not wire this store into picker/runtime authority. The
    legacy scalar ``AppLocalSettingsStore`` remains authoritative until later
    rollback/cutover capability is present.
    """

    CURRENT_SCHEMA = CURRENT_REGISTRY_SCHEMA

    def __init__(self, path: Path) -> None:
        self.path = path
        self.lock_path = path.with_suffix(path.suffix + ".lock")
        self.snapshot_path = path.with_suffix(path.suffix + ".last-good")
        self.snapshot_checksum_path = path.with_suffix(path.suffix + ".last-good.sha256")
        self.rollback_export_path = path.with_suffix(path.suffix + ".legacy-export")
        self.transaction_path = path.with_suffix(path.suffix + ".transaction")
        self.scalar_rollback_session_path = path.with_suffix(
            path.suffix + ".scalar-rollback-session.json"
        )

    def load(self) -> RegistrySnapshot:
        with self._locked():
            if not self.path.exists():
                return self._restore_or_initialize_missing_locked()
            return self._read_current_locked(recover=True)

    def require_no_scalar_rollback_session(self) -> None:
        """Fail current-runtime startup while an authenticated old image is live."""

        with self._locked():
            self._assert_no_scalar_rollback_session_locked()

    def app_local_view(self) -> AppLocalSettings:
        """Return the complete compatibility view without scalar projection loss."""

        return _app_local_from_registry(self.load())

    def capture_backup_artifacts(self) -> dict[str, bytes]:
        """Capture the complete registry generation while holding its writer lock."""

        with self._locked():
            if not self.path.exists():
                self._restore_or_initialize_missing_locked()
            else:
                self._read_current_locked(recover=True)
            artifacts = {
                "vault-registry.md": self.path,
                "vault-registry.md.last-good": self.snapshot_path,
                "vault-registry.md.last-good.sha256": self.snapshot_checksum_path,
                "vault-registry.md.legacy-export": self.rollback_export_path,
            }
            payloads: dict[str, bytes] = {}
            for name, source in artifacts.items():
                if not source.is_file():
                    raise RegistryError(f"registry backup source is incomplete: {name}")
                payloads[name] = source.read_bytes()
            return payloads

    def load_or_migrate(self) -> RegistrySnapshot:
        legacy_upgrade = self._is_owned_legacy_source()
        with self._locked(allow_legacy_directory_upgrade=legacy_upgrade):
            if not self.path.exists():
                return self._restore_or_initialize_missing_locked()
            try:
                document = _read_document(self.path)
            except (OSError, RegistryParseError):
                return self._read_current_locked(recover=True)
            schema = _optional_str(document.frontmatter.get("schema"))
            if schema == CURRENT_REGISTRY_SCHEMA:
                # Already migrated: nothing to do, and deliberately no write. The
                # spec materializes a legacy last-active "during the one-time
                # schema migration only", so the promotion lives in
                # `_migrate_legacy_frontmatter` and nowhere else. A second
                # materialization arm here would be a standing last-active rule
                # wearing a migration's name, and would turn this read-named
                # entry point into a writer that bypasses the scalar-rollback
                # session guard every other writer holds.
                _assert_private(self.path, directory=False)
                return self._snapshot_from_frontmatter(document.frontmatter)
            if schema != APP_LOCAL_SCHEMA:
                raise RegistryMigrationError(f"unsupported registry migration schema: {schema or '<missing>'}")
            migrated = self._migrate_legacy_frontmatter(document.frontmatter)
            self._write_locked(migrated)
            return migrated

    def register(
        self,
        registration: VaultRegistration,
        *,
        expected_revision: int | None = None,
        first_default_provenance: str | None = None,
        _capability: _StorageMutationCapability | None = None,
    ) -> RegistrySnapshot:
        """Register one binding, optionally as the atomic MVR-02 first default.

        ``first_default_provenance`` records the new binding as the explicit
        instance default **inside this same locked transaction**, and only when
        the transaction itself proves the registry had no prior registration and
        no prior default. A later picker, open, or last-active write never infers
        a default, so the first-vault journey stays a distinct producer rather
        than a fallback rule.
        """

        _require_storage_mutation_capability(_capability)
        self._validate_registration(registration)
        if first_default_provenance is not None and first_default_provenance not in {
            DEFAULT_PROVENANCE_FIRST_INITIALIZE,
            DEFAULT_PROVENANCE_FIRST_OPEN_EXISTING,
        }:
            raise RegistryError(
                f"unsupported first-default provenance: {first_default_provenance}"
            )
        with self._locked():
            self._assert_no_scalar_rollback_session_locked()
            current = (
                self._read_current_locked(recover=True)
                if self.path.exists()
                else self._restore_or_initialize_missing_locked()
            )
            self._assert_revision(current, expected_revision)
            registrations = dict(current.registrations)
            existing = registrations.get(registration.vault_binding_id)
            if existing is not None and existing != registration:
                raise RegistryError(f"vault_binding_id collision: {registration.vault_binding_id}")
            self._assert_registration_unique(registration, registrations)
            first_registration = not current.registrations
            registrations[registration.vault_binding_id] = registration
            updated = self._with_registrations(current, registrations)
            if first_default_provenance is not None:
                if not first_registration or current.default_vault_binding_id is not None:
                    raise RegistryDefaultConflict(
                        "the first-vault default producer requires an empty registry "
                        "with no explicit default"
                    )
                updated = replace(
                    updated,
                    default_vault_binding_id=registration.vault_binding_id,
                    default_vault_provenance=first_default_provenance,
                )
            self._write_locked(updated)
            return updated

    def set_instance_default(
        self,
        vault_binding_id: str | None,
        *,
        provenance: str = DEFAULT_PROVENANCE_EXPLICIT,
        expected_revision: int | None = None,
        _capability: _StorageMutationCapability | None = None,
    ) -> RegistrySnapshot:
        """Set or clear the explicit instance default in one locked revision.

        This never reads or writes ``last_active_vault_ref``: the default is
        instance selection, last-active is interaction history, and MVR-02 keeps
        them distinct. An unknown binding fails closed instead of falling through
        to another registration.
        """

        _require_storage_mutation_capability(_capability)
        target = _optional_str(vault_binding_id)
        if target is None:
            resolved_provenance: str | None = None
        else:
            if provenance not in DEFAULT_VAULT_PROVENANCES:
                raise RegistryError(f"unsupported default provenance: {provenance}")
            resolved_provenance = provenance
        with self._locked():
            self._assert_no_scalar_rollback_session_locked()
            current = self._read_current_locked(recover=True)
            self._assert_revision(current, expected_revision)
            if target is not None and target not in current.registrations:
                raise RegistryError(f"unknown vault_binding_id: {target}")
            updated = replace(
                self._with_registrations(current, dict(current.registrations)),
                default_vault_binding_id=target,
                default_vault_provenance=resolved_provenance,
            )
            self._write_locked(updated)
            return updated

    def list_registrations(self) -> tuple[VaultRegistration, ...]:
        """Return a stable binding-id ordered view of dormant registrations."""

        snapshot = self.load()
        return tuple(snapshot.registrations[key] for key in sorted(snapshot.registrations))

    def lookup(self, vault_binding_id: str) -> VaultRegistration | None:
        return self.load().registrations.get(vault_binding_id)

    def update_registration(
        self,
        registration: VaultRegistration,
        *,
        expected_revision: int | None = None,
        _capability: _StorageMutationCapability | None = None,
    ) -> RegistrySnapshot:
        """Update mutable binding metadata without changing stable identities."""

        _require_storage_mutation_capability(_capability)
        self._validate_registration(registration)
        with self._locked():
            self._assert_no_scalar_rollback_session_locked()
            current = self._read_current_locked(recover=True)
            self._assert_revision(current, expected_revision)
            existing = current.registrations.get(registration.vault_binding_id)
            if existing is None:
                raise RegistryError(f"unknown vault_binding_id: {registration.vault_binding_id}")
            for field_name in ("vault_id", "local_instance_id"):
                old_value = getattr(existing, field_name)
                new_value = getattr(registration, field_name)
                if old_value is not None and new_value != old_value:
                    raise RegistryError(f"stable registration identity cannot change: {field_name}")
            registrations = dict(current.registrations)
            self._assert_registration_unique(registration, registrations)
            registrations[registration.vault_binding_id] = registration
            updated = self._with_registrations(current, registrations)
            self._write_locked(updated)
            return updated

    def remember_registration(
        self,
        vault_binding_id: str,
        item: KnownVaultRef,
        *,
        make_active: bool,
        _capability: _StorageMutationCapability | None = None,
    ) -> RegistrySnapshot:
        """Route the live picker/app-local compatibility seam through active registry truth."""

        _require_storage_mutation_capability(_capability)
        with self._locked():
            self._assert_no_scalar_rollback_session_locked()
            current = self._read_current_locked(recover=True)
            if current.authority != REGISTRY_AUTHORITY_ACTIVE:
                raise CapabilityNotReadyError("active registry authority is required")
            registration = current.registrations.get(vault_binding_id)
            if registration is None:
                raise RegistryError("remembered vault binding is not registered")
            if (
                item.ref != registration.ref
                or Path(item.path).expanduser().resolve(strict=True)
                != Path(registration.path).expanduser().resolve(strict=True)
                or item.vault_id not in (None, registration.vault_id)
                or item.local_instance_id not in (None, registration.local_instance_id)
            ):
                raise RegistryError("remembered vault identity does not match active registration")
            registrations = copy.deepcopy(current.registrations)
            registrations[vault_binding_id] = VaultRegistration(
                vault_binding_id=registration.vault_binding_id,
                ref=registration.ref,
                path=registration.path,
                vault_id=registration.vault_id,
                local_instance_id=registration.local_instance_id,
                vault_name=item.vault_name,
                last_opened_at=item.last_opened_at,
                extensions=copy.deepcopy(registration.extensions),
            )
            next_revision = current.revision + 1
            extensions = copy.deepcopy(current.extensions)
            floor = extensions.get("scalarRollback")
            if not isinstance(floor, dict):
                raise RegistryError("active registry scalar rollback floor is invalid")
            extensions["scalarRollback"] = {
                **floor,
                "forkRegistryRevision": next_revision,
            }
            updated = RegistrySnapshot(
                schema=current.schema,
                authority=current.authority,
                revision=next_revision,
                app_install_id=current.app_install_id,
                last_active_vault_ref=(
                    registration.ref if make_active else current.last_active_vault_ref
                ),
                registrations=registrations,
                removal_tombstones=copy.deepcopy(current.removal_tombstones),
                transfer_lineage=copy.deepcopy(current.transfer_lineage),
                settings_rebind=copy.deepcopy(current.settings_rebind),
                extensions=extensions,
                default_vault_binding_id=current.default_vault_binding_id,
                default_vault_provenance=current.default_vault_provenance,
            )
            self._write_locked(updated)
            return updated

    def remove_registration(
        self,
        vault_binding_id: str,
        *,
        expected_revision: int | None = None,
        clear_default: bool = False,
        replacement_default_binding_id: str | None = None,
        _capability: _StorageMutationCapability | None = None,
    ) -> RegistrySnapshot:
        """Remove one registration; production removal remains sealed.

        MVR-02 makes this transaction reference-safe: removing the binding that
        is currently the explicit instance default is a conflict unless the same
        locked transaction also supplies ``clear_default`` or exactly one valid
        authorized replacement. The removal never silently promotes another
        registration and never leaves a dangling default behind.
        """

        _require_storage_mutation_capability(_capability)
        replacement = _optional_str(replacement_default_binding_id)
        if clear_default and replacement is not None:
            raise RegistryDefaultConflict(
                "default removal takes either an explicit clear or one replacement, not both"
            )
        with self._locked():
            self._assert_no_scalar_rollback_session_locked()
            current = self._read_current_locked(recover=True)
            self._assert_revision(current, expected_revision)
            if vault_binding_id not in current.registrations:
                raise RegistryError(f"unknown vault_binding_id: {vault_binding_id}")
            floor = current.extensions.get("scalarRollback")
            if (
                current.authority == REGISTRY_AUTHORITY_ACTIVE
                and isinstance(floor, dict)
                and _optional_str(floor.get("targetVaultBindingId")) == vault_binding_id
            ):
                # Reference safety is not only about the MVR-02 default: removing
                # the MVR-01C scalar rollback target would write a registry whose
                # own floor no longer resolves. Fail closed instead; retargeting
                # the floor belongs to its owner, not to this transaction.
                raise RegistryDefaultConflict(
                    "removing the MVR-01C scalar rollback target requires an "
                    "explicit authorized floor retarget"
                )
            registrations = dict(current.registrations)
            del registrations[vault_binding_id]
            updated = self._with_registrations(current, registrations)
            # MVR-04 transactional membership repair. `_with_registrations` already
            # deep-copied `extensions`, so this mutates the *pending* generation only, and
            # the single `_write_locked` below commits the deregistration and the
            # membership repair together. A dangling member is therefore never observable:
            # there is no window in which the registration is gone but a dimension still
            # lists it. Remaining member order is preserved and each repaired dimension
            # records a bounded receipt.
            # Deferred import: `app.instance.vault_dimensions` reads this module's snapshot
            # types, so importing it at module scope would be a cycle. The hook itself
            # takes only a plain mapping.
            from app.instance.vault_dimensions import (
                repair_dimensions_for_removed_binding,
            )

            repair_dimensions_for_removed_binding(
                updated.extensions,
                vault_binding_id=vault_binding_id,
                registry_revision=updated.revision,
            )
            removes_default = current.default_vault_binding_id == vault_binding_id
            if replacement is not None:
                if replacement == vault_binding_id or replacement not in registrations:
                    raise RegistryDefaultConflict(
                        "replacement default must be another current registration"
                    )
                if not removes_default:
                    raise RegistryDefaultConflict(
                        "a replacement default is only valid when removing the current default"
                    )
                updated = replace(
                    updated,
                    default_vault_binding_id=replacement,
                    default_vault_provenance=DEFAULT_PROVENANCE_EXPLICIT,
                )
            elif removes_default:
                if not clear_default:
                    raise RegistryDefaultConflict(
                        "removing the current instance default requires an explicit "
                        "clear_default or one authorized replacement binding"
                    )
                updated = replace(
                    updated,
                    default_vault_binding_id=None,
                    default_vault_provenance=None,
                )
            elif clear_default:
                raise RegistryDefaultConflict(
                    "clear_default is only valid when removing the current default"
                )
            self._write_locked(updated)
            return updated

    def commit_state(
        self,
        *,
        registrations: dict[str, VaultRegistration],
        removal_tombstones: dict[str, RemovalTombstone] | None = None,
        transfer_lineage: tuple[TransferLineage, ...] | None = None,
        extensions: dict[str, Any] | None = None,
        expected_revision: int | None = None,
        _capability: _StorageMutationCapability | None = None,
    ) -> RegistrySnapshot:
        """Atomically commit one lifecycle/transfer state transition.

        The explicit instance default is carried through unchanged: MVR-02 owns
        it through :meth:`set_instance_default` alone, so no lifecycle or
        transfer transition can silently move, forge, or wipe it. A committed
        registration set that would orphan the current default is refused
        outright rather than quietly clearing it.
        """

        _require_storage_mutation_capability(_capability)
        with self._locked():
            self._assert_no_scalar_rollback_session_locked()
            current = self._read_current_locked(recover=True)
            self._assert_revision(current, expected_revision)
            validated: dict[str, VaultRegistration] = {}
            for binding_id, registration in registrations.items():
                if binding_id != registration.vault_binding_id:
                    raise RegistryError("registration key does not match vault_binding_id")
                self._validate_registration(registration)
                self._assert_registration_unique(registration, validated)
                validated[binding_id] = registration
            next_revision = current.revision + 1
            next_extensions = copy.deepcopy(
                current.extensions if extensions is None else extensions
            )
            if current.authority == REGISTRY_AUTHORITY_ACTIVE:
                floor = next_extensions.get("scalarRollback")
                if not isinstance(floor, dict):
                    raise RegistryError("active registry scalar rollback floor is invalid")
                next_extensions["scalarRollback"] = {
                    **floor,
                    "forkRegistryRevision": next_revision,
                }
            next_default = current.default_vault_binding_id
            next_default_provenance = current.default_vault_provenance
            if next_default is not None and next_default not in validated:
                raise RegistryDefaultConflict(
                    "committed registration state would leave the instance default dangling"
                )
            updated = RegistrySnapshot(
                schema=current.schema,
                authority=current.authority,
                revision=next_revision,
                app_install_id=current.app_install_id,
                last_active_vault_ref=current.last_active_vault_ref,
                registrations=validated,
                removal_tombstones=copy.deepcopy(
                    current.removal_tombstones
                    if removal_tombstones is None
                    else removal_tombstones
                ),
                transfer_lineage=copy.deepcopy(
                    current.transfer_lineage if transfer_lineage is None else transfer_lineage
                ),
                settings_rebind=copy.deepcopy(current.settings_rebind),
                extensions=next_extensions,
                default_vault_binding_id=next_default,
                default_vault_provenance=next_default_provenance,
            )
            self._write_locked(updated)
            return updated

    def set_dimension_state(
        self,
        dimensions: Mapping[str, object],
        *,
        expected_revision: int | None = None,
        _capability: _StorageMutationCapability | None = None,
    ) -> RegistrySnapshot:
        """Persist the MVR-04 dimension set in one locked registry revision.

        This is a *dedicated* producer rather than a call into
        :meth:`set_extension_state`, for the same reason MVR-02 gave the explicit default
        its own writer: that method rewrites four slots at once, so routing dimensions
        through it would let an unrelated principal/background/floor write wipe durable
        grouping (when passed a stale value) with no way to tell that it had.

        It touches dimensions and nothing else. Registrations, tombstones, transfer
        lineage, the explicit default, and every other extension slot are carried through
        unchanged, so a grouping write can never move authority-bearing state.
        """

        _require_storage_mutation_capability(_capability)
        with self._locked():
            self._assert_no_scalar_rollback_session_locked()
            current = self._read_current_locked(recover=True)
            self._assert_revision(current, expected_revision)
            updated = self._with_registrations(current, dict(current.registrations))
            updated.extensions["dimensions"] = copy.deepcopy(dict(dimensions))
            self._write_locked(updated)
            return updated

    def remove_dimension_state(
        self,
        *,
        expected_revision: int,
        _capability: _StorageMutationCapability | None = None,
    ) -> RegistrySnapshot:
        """Remove only the durable MVR-04 extension slot at a pinned revision.

        This deliberately narrow recovery writer exists for a registry whose
        ``extensions.dimensions`` payload cannot be parsed by the ordinary MVR-04
        service.  It is not an extension mutation escape hatch: registrations,
        defaults, and every extension key other than ``dimensions`` are copied from
        the locked current snapshot unchanged.
        """

        _require_storage_mutation_capability(_capability)
        with self._locked():
            self._assert_no_scalar_rollback_session_locked()
            current = self._read_current_locked(recover=True)
            self._assert_revision(current, expected_revision)
            if "dimensions" not in current.extensions:
                raise RegistryError("registry dimensions recovery requires a dimensions slot")
            updated = self._with_registrations(current, dict(current.registrations))
            updated.extensions.pop("dimensions", None)
            self._write_locked(updated)
            return updated

    def set_extension_state(
        self,
        *,
        principal_state: Mapping[str, object],
        background_state: Mapping[str, object],
        runtime_floors: Mapping[str, object],
        expected_revision: int | None = None,
        _capability: _StorageMutationCapability | None = None,
    ) -> RegistrySnapshot:
        """Persist the 01B mechanical state that must survive backup/restore.

        MVR-02 promoted the default from an opaque extension blob to a validated
        first-class registry field with its own producer, so this 01B mechanical
        writer no longer carries ``default_vault_binding_id`` at all. Letting it
        would mean an unrelated dimensions/principal/background write could wipe
        a durable operator default (when passed ``None``) or forge
        ``explicit_default_command`` provenance (when passed a binding).

        MVR-04 does exactly the same for ``dimensions``, for exactly the same
        reason. That slot is no longer an opaque 01B placeholder but durable
        operator state with its own validated producer
        (:meth:`set_dimension_state`), so this writer must not be able to reach
        it at all. Keeping the parameter would leave a standing wipe: any caller
        that read the slots, edited one, and re-supplied the rest would silently
        destroy every dimension on a stale or empty payload — with no error, no
        conflict, and no event. Removing it makes that unrepresentable rather
        than merely unlikely.

        ``expected_revision`` additionally lets such a caller pin the revision it
        actually read, so a concurrent write to any *remaining* slot fails closed
        with :class:`RegistryRevisionConflict` instead of being lost across the
        two reads this call spans.
        """

        _require_storage_mutation_capability(_capability)
        current = self.load()
        self._assert_revision(current, expected_revision)
        extensions = copy.deepcopy(current.extensions)
        extensions.update(
            {
                "principalState": copy.deepcopy(dict(principal_state)),
                "backgroundState": copy.deepcopy(dict(background_state)),
                "runtimeFloors": copy.deepcopy(dict(runtime_floors)),
            }
        )
        return self.commit_state(
            registrations=dict(current.registrations),
            extensions=extensions,
            expected_revision=current.revision,
            _capability=_capability,
        )

    def require_authoritative_activation(
        self,
        proof: RegistryActivationProof,
        *,
        expected_revision: int | None = None,
        _capability: _StorageMutationCapability | None = None,
    ) -> RegistrySnapshot:
        """Atomically install the MVR-01C rollback floor and cut registry authority over."""

        if not (proof.rollback_exporter and proof.rollback_transformer and proof.previous_image_preflight):
            raise CapabilityNotReadyError(
                "MVR-01B rollback exporter/transformer and previous-image preflight are required "
                "before registry authority activation"
            )
        if not (
            proof.authenticated_gateway
            and proof.native_guard
            and proof.roll_forward_lineage
        ):
            raise CapabilityNotReadyError(
                "MVR-01C authority cutover requires gateway, native guard, and "
                "roll-forward lineage preflight"
            )
        policy_digests = (
            _optional_str(proof.compose_policy_sha256),
            _optional_str(proof.gateway_policy_sha256),
            _optional_str(proof.native_launcher_sha256),
        )
        if any(value is None or len(value) != 64 for value in policy_digests):
            raise CapabilityNotReadyError(
                "MVR-01C authority cutover requires bound rollback policy digests"
            )
        _require_storage_mutation_capability(_capability)
        target_binding_id = _optional_str(proof.rollback_vault_binding_id)
        with self._locked():
            self._assert_no_scalar_rollback_session_locked()
            current = self._read_current_locked(recover=True)
            self._assert_revision(current, expected_revision)
            if current.authority == REGISTRY_AUTHORITY_ACTIVE:
                floor = current.extensions.get("scalarRollback")
                if not isinstance(floor, dict) or floor.get("targetVaultBindingId") != target_binding_id:
                    raise RegistryError("registry authority is already active with another rollback floor")
                return current
            if not current.registrations:
                raise CapabilityNotReadyError("registry authority activation requires one registration")
            if target_binding_id is None:
                if len(current.registrations) != 1:
                    raise CapabilityNotReadyError(
                        "one explicit rollback_vault_binding_id is required for multiple registrations"
                    )
                target_binding_id = next(iter(current.registrations))
            if target_binding_id not in current.registrations:
                raise RegistryError("rollback target is not a current registration")
            target = current.registrations[target_binding_id]
            extensions = copy.deepcopy(current.extensions)
            extensions["scalarRollback"] = {
                "schema": SCALAR_ROLLBACK_SCHEMA,
                "targetVaultBindingId": target_binding_id,
                "targetRef": target.ref,
                "targetPath": target.path,
                "forkRegistryRevision": current.revision + 1,
                "gatewayPreflight": "authenticated-mutation-filter",
                "nativeGuardPreflight": "deny-by-default",
                "rollForwardLineage": ROLL_FORWARD_LINEAGE_SCHEMA,
                "composePolicySha256": policy_digests[0],
                "gatewayPolicySha256": policy_digests[1],
                "nativeLauncherSha256": policy_digests[2],
            }
            activated = RegistrySnapshot(
                schema=current.schema,
                authority=REGISTRY_AUTHORITY_ACTIVE,
                revision=current.revision + 1,
                app_install_id=current.app_install_id,
                last_active_vault_ref=current.last_active_vault_ref,
                registrations=copy.deepcopy(current.registrations),
                removal_tombstones=copy.deepcopy(current.removal_tombstones),
                transfer_lineage=copy.deepcopy(current.transfer_lineage),
                settings_rebind=copy.deepcopy(current.settings_rebind),
                extensions=extensions,
                default_vault_binding_id=current.default_vault_binding_id,
                default_vault_provenance=current.default_vault_provenance,
            )
            self._write_locked(activated)
            return activated

    def materialize_legacy_rollback(
        self,
        target_path: Path,
        *,
        rollback_vault_binding_id: str | None = None,
        selected_runtime_path: Path | None = None,
    ) -> AppLocalSettings:
        """Transform the latest scalar-representable revision for a previous image."""

        with self._locked():
            self._assert_no_scalar_rollback_session_locked()
            current = self._read_current_locked(recover=True)
            selected = _optional_str(rollback_vault_binding_id)
            floor = current.extensions.get("scalarRollback")
            if current.authority == REGISTRY_AUTHORITY_ACTIVE:
                if not isinstance(floor, dict) or floor.get("schema") != SCALAR_ROLLBACK_SCHEMA:
                    raise RegistryError("active registry is missing scalar rollback floor")
                floor_target = _optional_str(floor.get("targetVaultBindingId"))
                if selected is not None and selected != floor_target:
                    raise RegistryError("rollback target does not match the activated scalar floor")
                selected = floor_target
            elif len(current.registrations) > 1:
                raise CapabilityNotReadyError(
                    "MVR-01C explicit rollback target is required for multiple registrations"
                )
            canonical_payload = self._rollback_export_payload(
                current,
                selected_binding_id=selected,
            )
            if (
                not self.rollback_export_path.exists()
                or self.rollback_export_path.read_bytes() != canonical_payload
            ):
                raise RegistryError("latest-revision legacy rollback export is missing or stale")
            payload = self._rollback_export_payload(
                current,
                selected_binding_id=selected,
                selected_runtime_path=selected_runtime_path,
            )
            target = Path(target_path)
            _atomic_private_write(target, payload)
        return AppLocalSettingsStore(Path(target_path)).load()

    def install_scalar_rollback_session(
        self,
        *,
        payload: Mapping[str, object],
        authentication: Mapping[str, object],
        expected_revision: int,
        _capability: _StorageMutationCapability | None = None,
    ) -> None:
        """Durably exclude current writers for the authenticated scalar runtime."""

        _require_storage_mutation_capability(_capability)
        with self._locked():
            self._assert_no_scalar_rollback_session_locked()
            current = self._read_current_locked(recover=True)
            self._assert_revision(current, expected_revision)
            floor = current.extensions.get("scalarRollback")
            initial_export_sha256 = str(payload.get("initialExportSha256") or "")
            registry_export_sha256 = str(payload.get("registryExportSha256") or "")
            legacy_selected_path = _optional_str(payload.get("legacySelectedPath"))
            if (
                current.authority != REGISTRY_AUTHORITY_ACTIVE
                or not isinstance(floor, dict)
                or payload.get("schema") != ROLL_FORWARD_LINEAGE_SCHEMA
                or payload.get("registrySchema") != current.schema
                or payload.get("forkRegistryRevision") != current.revision
                or payload.get("rollbackVaultBindingId")
                != floor.get("targetVaultBindingId")
                or payload.get("minimumRuntimeSchema")
                != (current.extensions.get("runtimeFloors") or {}).get(
                    "minimumRuntimeSchema"
                )
                or payload.get("composePolicySha256")
                != floor.get("composePolicySha256")
                or payload.get("gatewayPolicySha256")
                != floor.get("gatewayPolicySha256")
                or payload.get("nativeLauncherSha256")
                != floor.get("nativeLauncherSha256")
                or not _is_sha256(initial_export_sha256)
                or not _is_sha256(registry_export_sha256)
                or legacy_selected_path is None
                or not self.rollback_export_path.is_file()
                or hashlib.sha256(self.rollback_export_path.read_bytes()).hexdigest()
                != registry_export_sha256
            ):
                raise RegistryError("scalar rollback session does not match current authority")
            document = {
                "payload": copy.deepcopy(dict(payload)),
                "authentication": copy.deepcopy(dict(authentication)),
            }
            _atomic_private_write(
                self.scalar_rollback_session_path,
                (
                    json.dumps(document, sort_keys=True, separators=(",", ":"))
                    + "\n"
                ).encode("utf-8"),
            )

    def load_scalar_rollback_session(
        self,
    ) -> tuple[dict[str, object], dict[str, object]]:
        with self._locked():
            try:
                _assert_private(self.scalar_rollback_session_path, directory=False)
                document = json.loads(
                    self.scalar_rollback_session_path.read_text(encoding="utf-8")
                )
            except (OSError, ValueError, TypeError, json.JSONDecodeError) as exc:
                raise RegistryError(
                    "authenticated scalar rollback session is missing or invalid"
                ) from exc
            if (
                not isinstance(document, dict)
                or not isinstance(document.get("payload"), dict)
                or not isinstance(document.get("authentication"), dict)
            ):
                raise RegistryError(
                    "authenticated scalar rollback session is missing or invalid"
                )
            return dict(document["payload"]), dict(document["authentication"])

    def merge_scalar_rollback(
        self,
        source_path: Path,
        *,
        session_payload: Mapping[str, object],
        _capability: _StorageMutationCapability | None = None,
    ) -> RegistrySnapshot:
        """Import one validated scalar rollback fork as the next registry revision."""

        _require_storage_mutation_capability(_capability)
        source = Path(source_path)
        with self._locked():
            legacy = AppLocalSettingsStore(source).load()
            current = self._read_current_locked(recover=True)
            floor = current.extensions.get("scalarRollback")
            if (
                current.authority != REGISTRY_AUTHORITY_ACTIVE
                or not isinstance(floor, dict)
                or floor.get("schema") != SCALAR_ROLLBACK_SCHEMA
            ):
                raise CapabilityNotReadyError("active scalar rollback lineage floor is required")
            target_id = _optional_str(floor.get("targetVaultBindingId"))
            if target_id is None:
                raise RegistryError("scalar rollback target is missing")
            target = current.registrations.get(target_id)
            if target is None:
                raise RegistryError("scalar rollback target is no longer registered")
            initial_export_sha256 = str(
                session_payload.get("initialExportSha256") or ""
            )
            registry_export_sha256 = str(
                session_payload.get("registryExportSha256") or ""
            )
            legacy_selected_path = _optional_str(
                session_payload.get("legacySelectedPath")
            )
            expected_initial_export_sha256 = (
                hashlib.sha256(
                    self._rollback_export_payload(
                        current,
                        selected_binding_id=target_id,
                        selected_runtime_path=Path(legacy_selected_path),
                    )
                ).hexdigest()
                if legacy_selected_path is not None
                else None
            )
            if (
                session_payload.get("schema") != ROLL_FORWARD_LINEAGE_SCHEMA
                or session_payload.get("registrySchema") != current.schema
                or session_payload.get("forkRegistryRevision")
                != floor.get("forkRegistryRevision")
                or session_payload.get("rollbackVaultBindingId") != target_id
                or current.revision != floor.get("forkRegistryRevision")
                or not _is_sha256(initial_export_sha256)
                or not _is_sha256(registry_export_sha256)
                or legacy_selected_path is None
                or initial_export_sha256 != expected_initial_export_sha256
                or not self.rollback_export_path.is_file()
                or hashlib.sha256(self.rollback_export_path.read_bytes()).hexdigest()
                != registry_export_sha256
            ):
                raise RegistryError("scalar rollback lineage is stale, ambiguous, or divergent")
            if set(legacy.known_vaults) != {target.ref}:
                raise RegistryError("scalar rollback mutation escaped the selected binding")
            changed = legacy.known_vaults[target.ref]
            if (
                changed.path != legacy_selected_path
                or changed.vault_id != target.vault_id
                or changed.local_instance_id != target.local_instance_id
                or legacy.last_active_vault_ref not in (None, target.ref)
            ):
                raise RegistryError("scalar rollback identity or selection diverged")
            registrations = copy.deepcopy(current.registrations)
            registrations[target_id] = VaultRegistration(
                vault_binding_id=target.vault_binding_id,
                ref=target.ref,
                path=target.path,
                vault_id=target.vault_id,
                local_instance_id=target.local_instance_id,
                vault_name=changed.vault_name,
                last_opened_at=changed.last_opened_at,
                extensions=copy.deepcopy(target.extensions),
            )
            extensions = copy.deepcopy(current.extensions)
            lineage = extensions.get("scalarRollForwardLineage")
            if lineage is None:
                lineage = []
            if not isinstance(lineage, list):
                raise RegistryError("scalar roll-forward lineage is invalid")
            lineage.append(
                {
                    "schema": ROLL_FORWARD_LINEAGE_SCHEMA,
                    "vaultBindingId": target_id,
                    "forkRegistryRevision": current.revision,
                    "mergedRegistryRevision": current.revision + 1,
                }
            )
            extensions["scalarRollForwardLineage"] = lineage
            extensions["scalarRollback"] = {
                **copy.deepcopy(floor),
                "forkRegistryRevision": current.revision + 1,
            }
            # MVR-02: the scalar previous image never carried the explicit
            # default, so roll-forward restores the authoritative new-schema
            # value rather than inferring one from the returning last-active
            # projection. The merge verifies the binding still exists first; a
            # default whose binding is gone is cleared atomically instead of
            # being left dangling or silently repointed at another registration.
            merged_default = current.default_vault_binding_id
            merged_default_provenance = current.default_vault_provenance
            if merged_default is not None and merged_default not in registrations:
                merged_default = None
                merged_default_provenance = None
            merged = RegistrySnapshot(
                schema=current.schema,
                authority=current.authority,
                revision=current.revision + 1,
                app_install_id=current.app_install_id,
                last_active_vault_ref=legacy.last_active_vault_ref,
                registrations=registrations,
                removal_tombstones=copy.deepcopy(current.removal_tombstones),
                transfer_lineage=copy.deepcopy(current.transfer_lineage),
                settings_rebind=copy.deepcopy(current.settings_rebind),
                extensions=extensions,
                default_vault_binding_id=merged_default,
                default_vault_provenance=merged_default_provenance,
            )
            self._write_locked(merged, retire_scalar_session=True)
            return merged

    def _empty_snapshot(self) -> RegistrySnapshot:
        return RegistrySnapshot(
            schema=CURRENT_REGISTRY_SCHEMA,
            authority=REGISTRY_AUTHORITY_DORMANT,
            revision=0,
            app_install_id=f"app-{uuid4()}",
            last_active_vault_ref=None,
            registrations={},
        )

    def _assert_revision(self, current: RegistrySnapshot, expected: int | None) -> None:
        if expected is not None and current.revision != expected:
            raise RegistryRevisionConflict(
                f"expected revision {expected}, found {current.revision}; reload before retry"
            )

    def _assert_registration_unique(
        self,
        candidate: VaultRegistration,
        registrations: Mapping[str, VaultRegistration],
    ) -> None:
        candidate_identity = _root_identity(candidate.path)
        for binding_id, item in registrations.items():
            if binding_id == candidate.vault_binding_id:
                continue
            if item.ref == candidate.ref:
                raise RegistryError(f"registry ref collision: {candidate.ref}")
            if same_filesystem_root(_root_identity(item.path), candidate_identity):
                raise RegistryError(f"registry path identity collision: {candidate.path}")

    def _validate_registration(self, registration: VaultRegistration) -> None:
        if not registration.vault_binding_id.strip():
            raise RegistryError("vault_binding_id is required")
        if not registration.ref.strip() or not registration.path.strip():
            raise RegistryError("registration ref and path are required")

    def _with_registrations(
        self,
        current: RegistrySnapshot,
        registrations: dict[str, VaultRegistration],
    ) -> RegistrySnapshot:
        next_revision = current.revision + 1
        extensions = copy.deepcopy(current.extensions)
        if current.authority == REGISTRY_AUTHORITY_ACTIVE:
            floor = extensions.get("scalarRollback")
            if not isinstance(floor, dict):
                raise RegistryError("active registry scalar rollback floor is invalid")
            extensions["scalarRollback"] = {
                **floor,
                "forkRegistryRevision": next_revision,
            }
        return RegistrySnapshot(
            schema=current.schema,
            authority=current.authority,
            revision=next_revision,
            app_install_id=current.app_install_id,
            last_active_vault_ref=current.last_active_vault_ref,
            registrations=registrations,
            removal_tombstones=copy.deepcopy(current.removal_tombstones),
            transfer_lineage=copy.deepcopy(current.transfer_lineage),
            settings_rebind=copy.deepcopy(current.settings_rebind),
            extensions=extensions,
            default_vault_binding_id=current.default_vault_binding_id,
            default_vault_provenance=current.default_vault_provenance,
        )

    @contextmanager
    def _locked(self, *, allow_legacy_directory_upgrade: bool = False) -> Iterator[None]:
        if allow_legacy_directory_upgrade:
            _upgrade_owned_legacy_directory(self.path.parent)
        else:
            _ensure_private_directory(self.path.parent)
        existed = self.lock_path.exists()
        descriptor = os.open(
            self.lock_path,
            os.O_RDWR | os.O_CREAT | getattr(os, "O_NOFOLLOW", 0),
            0o600,
        )
        try:
            _assert_private_stat(os.fstat(descriptor), self.lock_path, directory=False)
            if not existed:
                os.fchmod(descriptor, 0o600)
        except BaseException:
            os.close(descriptor)
            raise
        with os.fdopen(descriptor, "a+b", closefd=True) as lock_file:
            fcntl.flock(lock_file.fileno(), fcntl.LOCK_EX)
            try:
                self._recover_transaction_locked()
                self._ensure_rollback_export_locked()
                yield
            finally:
                fcntl.flock(lock_file.fileno(), fcntl.LOCK_UN)

    def _is_owned_legacy_source(self) -> bool:
        if not os.path.lexists(self.path):
            return False
        metadata = self.path.lstat()
        if not stat.S_ISREG(metadata.st_mode) or metadata.st_uid != os.geteuid():
            raise RegistrySecurityError(f"unsafe legacy registry source for {self.path.name}")
        try:
            document = _read_document(self.path)
        except (OSError, RegistryParseError):
            return False
        return _optional_str(document.frontmatter.get("schema")) == APP_LOCAL_SCHEMA

    def _read_current_locked(self, *, recover: bool) -> RegistrySnapshot:
        try:
            _assert_private(self.path, directory=False)
            document = _read_document(self.path)
            return self._snapshot_from_frontmatter(document.frontmatter)
        except RegistrySecurityError:
            raise
        except (OSError, RegistryParseError, RegistryError) as exc:
            if not recover:
                raise
            recovered = self._load_verified_snapshot_locked()
            if recovered is None:
                raise RegistryError("registry is corrupt and no unambiguous last-good snapshot exists") from exc
            snapshot, payload = recovered
            _atomic_private_write(self.path, payload)
            _atomic_private_write(self.rollback_export_path, self._rollback_export_payload(snapshot))
            return snapshot

    def _restore_or_initialize_missing_locked(self) -> RegistrySnapshot:
        recovered = self._load_verified_snapshot_locked()
        if recovered is not None:
            snapshot, payload = recovered
            _atomic_private_write(self.path, payload)
            _atomic_private_write(self.rollback_export_path, self._rollback_export_payload(snapshot))
            return snapshot
        if os.path.lexists(self.snapshot_path) or os.path.lexists(self.snapshot_checksum_path):
            raise RegistryError(
                "registry main is missing and no unambiguous last-good snapshot exists"
            )
        snapshot = self._empty_snapshot()
        self._write_locked(snapshot)
        return snapshot

    def _load_verified_snapshot_locked(self) -> tuple[RegistrySnapshot, bytes] | None:
        if not self.snapshot_path.exists() or not self.snapshot_checksum_path.exists():
            return None
        _assert_private(self.snapshot_path, directory=False)
        _assert_private(self.snapshot_checksum_path, directory=False)
        payload = self.snapshot_path.read_bytes()
        expected = self.snapshot_checksum_path.read_text(encoding="ascii").strip()
        if not expected or hashlib.sha256(payload).hexdigest() != expected:
            return None
        try:
            text = payload.decode("utf-8")
            frontmatter, _ = _split_rendered(text, self.snapshot_path)
            snapshot = self._snapshot_from_frontmatter(frontmatter)
        except (UnicodeDecodeError, RegistryParseError, RegistryError):
            return None
        return snapshot, payload

    def _write_locked(
        self,
        snapshot: RegistrySnapshot,
        *,
        retire_scalar_session: bool = False,
    ) -> None:
        if snapshot.schema != CURRENT_REGISTRY_SCHEMA or snapshot.authority not in {
            REGISTRY_AUTHORITY_DORMANT,
            REGISTRY_AUTHORITY_ACTIVE,
        }:
            raise RegistryError("unsupported registry schema or authority state")
        frontmatter = self._frontmatter_from_snapshot(snapshot)
        self._snapshot_from_frontmatter(frontmatter)
        payload = _render_markdown_settings(
            frontmatter,
            "# Instance Vault Registry\nMechanical instance-local state; registration does not grant vault authority.\n",
        ).encode("utf-8")
        checksum = (hashlib.sha256(payload).hexdigest() + "\n").encode("ascii")
        rollback_export = self._rollback_export_payload(snapshot)
        previous = {
            self.path: _read_previous_transaction_file(self.path, allow_legacy_mode=True),
            self.snapshot_path: _read_previous_transaction_file(self.snapshot_path),
            self.snapshot_checksum_path: _read_previous_transaction_file(self.snapshot_checksum_path),
            self.rollback_export_path: _read_previous_transaction_file(self.rollback_export_path),
            self.scalar_rollback_session_path: _read_previous_transaction_file(
                self.scalar_rollback_session_path
            ),
        }
        next_generation = {
            self.path: payload,
            self.snapshot_path: payload,
            self.snapshot_checksum_path: checksum,
            self.rollback_export_path: rollback_export,
            self.scalar_rollback_session_path: (
                None
                if retire_scalar_session
                else previous[self.scalar_rollback_session_path]
            ),
        }
        prepared = self._transaction_manifest("prepared", previous, next_generation)
        _atomic_private_write(self.transaction_path, prepared)
        try:
            self._apply_generation(next_generation)
            committed = self._transaction_manifest("committed", previous, next_generation)
            _atomic_private_write(self.transaction_path, committed)
        except Exception:
            try:
                _atomic_private_write(self.transaction_path, prepared)
                self._apply_generation(previous, use_raw_writer=True)
                self._verify_generation(previous)
                self._clear_transaction_journal()
            except Exception as rollback_exc:
                raise RegistryError(
                    "registry transaction failed and rollback could not restore prior state"
                ) from rollback_exc
            raise
        try:
            self._verify_generation(next_generation)
            self._clear_transaction_journal()
        except OSError:
            # The committed journal is itself a durable completion receipt. A later locked
            # reader will idempotently finish verification/cleanup without losing the commit.
            pass

    def _transaction_manifest(
        self,
        phase: str,
        previous: Mapping[Path, bytes | None],
        next_generation: Mapping[Path, bytes | None],
    ) -> bytes:
        document = {
            "schema": _TRANSACTION_SCHEMA,
            "phase": phase,
            "previous": self._encode_generation(previous),
            "next": self._encode_generation(next_generation),
        }
        return (json.dumps(document, sort_keys=True, separators=(",", ":")) + "\n").encode("utf-8")

    def _encode_generation(self, generation: Mapping[Path, bytes | None]) -> dict[str, object]:
        return {
            name: (
                None
                if generation[path] is None
                else {
                    "payload": base64.b64encode(generation[path] or b"").decode("ascii"),
                    "sha256": hashlib.sha256(generation[path] or b"").hexdigest(),
                }
            )
            for name, path in self._transaction_artifacts().items()
        }

    def _decode_generation(self, value: object) -> dict[Path, bytes | None]:
        legacy_names = {"main", "snapshot", "checksum"}
        pre_session_names = {
            "main",
            "snapshot",
            "checksum",
            "rollback_export",
        }
        if not isinstance(value, dict) or frozenset(value) not in {
            frozenset(self._transaction_artifacts()),
            frozenset(legacy_names),
            frozenset(pre_session_names),
        }:
            raise RegistryError("registry transaction generation is malformed")
        decoded: dict[Path, bytes | None] = {}
        for name, path in self._transaction_artifacts().items():
            if name not in value:
                decoded[path] = None
                continue
            artifact = value[name]
            if artifact is None:
                decoded[path] = None
                continue
            if not isinstance(artifact, dict) or set(artifact) != {"payload", "sha256"}:
                raise RegistryError("registry transaction artifact is malformed")
            encoded = artifact["payload"]
            expected_digest = artifact["sha256"]
            if not isinstance(encoded, str) or not isinstance(expected_digest, str):
                raise RegistryError("registry transaction artifact is malformed")
            try:
                payload = base64.b64decode(encoded, validate=True)
            except (binascii.Error, ValueError) as exc:
                raise RegistryError("registry transaction artifact encoding is invalid") from exc
            if hashlib.sha256(payload).hexdigest() != expected_digest:
                raise RegistryError("registry transaction artifact digest is invalid")
            decoded[path] = payload
        return decoded

    def _transaction_artifacts(self) -> dict[str, Path]:
        return {
            "main": self.path,
            "snapshot": self.snapshot_path,
            "checksum": self.snapshot_checksum_path,
            "rollback_export": self.rollback_export_path,
            "scalar_rollback_session": self.scalar_rollback_session_path,
        }

    def _recover_transaction_locked(self) -> None:
        if not os.path.lexists(self.transaction_path):
            return
        _assert_private(self.transaction_path, directory=False)
        try:
            document = json.loads(self.transaction_path.read_text(encoding="utf-8"))
        except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise RegistryError("registry transaction journal is corrupt") from exc
        if not isinstance(document, dict) or set(document) != {"schema", "phase", "previous", "next"}:
            raise RegistryError("registry transaction journal is malformed")
        if document["schema"] != _TRANSACTION_SCHEMA or document["phase"] not in {"prepared", "committed"}:
            raise RegistryError("registry transaction journal schema or phase is invalid")
        previous = self._decode_generation(document["previous"])
        next_generation = self._decode_generation(document["next"])
        self._validate_next_generation(next_generation)
        self._assert_current_generation_belongs_to_transaction(previous, next_generation)
        target = previous if document["phase"] == "prepared" else next_generation
        self._apply_generation(target)
        self._verify_generation(target)
        self._clear_transaction_journal()

    def _validate_next_generation(self, generation: Mapping[Path, bytes | None]) -> None:
        payload = generation.get(self.path)
        snapshot = generation.get(self.snapshot_path)
        checksum = generation.get(self.snapshot_checksum_path)
        rollback_export = generation.get(self.rollback_export_path)
        scalar_session = generation.get(self.scalar_rollback_session_path)
        if payload is None or snapshot != payload or checksum is None:
            raise RegistryError("registry transaction next generation is incomplete")
        if checksum != (hashlib.sha256(payload).hexdigest() + "\n").encode("ascii"):
            raise RegistryError("registry transaction next generation checksum is invalid")
        try:
            frontmatter, _ = _split_rendered(payload.decode("utf-8"), self.path)
            parsed = self._snapshot_from_frontmatter(frontmatter)
            if rollback_export is not None and rollback_export != self._rollback_export_payload(parsed):
                raise RegistryError("registry transaction rollback export is invalid")
            if scalar_session is not None:
                session = json.loads(scalar_session)
                if (
                    not isinstance(session, dict)
                    or not isinstance(session.get("payload"), dict)
                    or not isinstance(session.get("authentication"), dict)
                ):
                    raise RegistryError(
                        "registry transaction scalar rollback session is invalid"
                    )
        except (UnicodeDecodeError, RegistryParseError, RegistryError) as exc:
            raise RegistryError("registry transaction next generation payload is invalid") from exc
        except (TypeError, json.JSONDecodeError) as exc:
            raise RegistryError(
                "registry transaction scalar rollback session is invalid"
            ) from exc

    def _assert_current_generation_belongs_to_transaction(
        self,
        previous: Mapping[Path, bytes | None],
        next_generation: Mapping[Path, bytes | None],
    ) -> None:
        for path in self._transaction_artifacts().values():
            current = _read_previous_transaction_file(path, allow_legacy_mode=path == self.path)
            if current not in {previous[path], next_generation[path]}:
                raise RegistryError(f"registry transaction artifact diverged outside journal: {path.name}")

    def _apply_generation(
        self,
        generation: Mapping[Path, bytes | None],
        *,
        use_raw_writer: bool = False,
    ) -> None:
        for path in (
            self.snapshot_path,
            self.snapshot_checksum_path,
            self.rollback_export_path,
            self.path,
            self.scalar_rollback_session_path,
        ):
            payload = generation[path]
            if payload is None:
                if os.path.lexists(path):
                    _read_previous_transaction_file(path, allow_legacy_mode=path == self.path)
                    path.unlink()
                    _fsync_directory(path.parent)
            else:
                writer = _atomic_private_write_raw if use_raw_writer else _atomic_private_write
                writer(path, payload)

    def _verify_generation(self, generation: Mapping[Path, bytes | None]) -> None:
        for path in self._transaction_artifacts().values():
            actual = _read_previous_transaction_file(path, allow_legacy_mode=path == self.path)
            if actual != generation[path]:
                raise RegistryError(f"registry transaction verification failed for {path.name}")

    def _clear_transaction_journal(self) -> None:
        self.transaction_path.unlink(missing_ok=True)
        _fsync_directory(self.transaction_path.parent)

    def _assert_no_scalar_rollback_session_locked(self) -> None:
        if self.scalar_rollback_session_path.exists():
            _assert_private(self.scalar_rollback_session_path, directory=False)
            raise CapabilityNotReadyError(
                "authenticated scalar rollback session blocks current registry writers"
            )

    def _ensure_rollback_export_locked(self) -> None:
        if not self.path.exists():
            return
        try:
            document = _read_document(self.path)
        except (OSError, RegistryParseError):
            return
        if _optional_str(document.frontmatter.get("schema")) != CURRENT_REGISTRY_SCHEMA:
            return
        try:
            snapshot = self._snapshot_from_frontmatter(document.frontmatter)
        except RegistryError:
            return
        expected = self._rollback_export_payload(snapshot)
        if self.rollback_export_path.exists():
            _assert_private(self.rollback_export_path, directory=False)
        if snapshot.authority == REGISTRY_AUTHORITY_ACTIVE:
            # Active cutover must fail closed on missing/stale projection; startup
            # preflight is not allowed to heal authority evidence implicitly.
            return
        if not self.rollback_export_path.exists() or self.rollback_export_path.read_bytes() != expected:
            _atomic_private_write(self.rollback_export_path, expected)

    def _rollback_export_payload(
        self,
        snapshot: RegistrySnapshot,
        *,
        selected_binding_id: str | None = None,
        selected_runtime_path: Path | None = None,
    ) -> bytes:
        if selected_binding_id is None and snapshot.authority == REGISTRY_AUTHORITY_ACTIVE:
            floor = snapshot.extensions.get("scalarRollback")
            if not isinstance(floor, dict) or floor.get("schema") != SCALAR_ROLLBACK_SCHEMA:
                raise RegistryError("active registry is missing scalar rollback floor")
            selected_binding_id = _optional_str(floor.get("targetVaultBindingId"))
        registrations: Iterable[VaultRegistration] = snapshot.registrations.values()
        if selected_binding_id is not None:
            selected = snapshot.registrations.get(selected_binding_id)
            if selected is None:
                raise RegistryError("scalar rollback target is not registered")
            registrations = (selected,)
        known = {
            item.ref: {
                "path": (
                    str(selected_runtime_path)
                    if selected_binding_id is not None
                    and item.vault_binding_id == selected_binding_id
                    and selected_runtime_path is not None
                    else item.path
                ),
                "vaultId": item.vault_id,
                "vaultName": item.vault_name,
                "localInstanceId": item.local_instance_id,
                "lastOpenedAt": item.last_opened_at,
            }
            for item in sorted(registrations, key=lambda item: item.ref)
        }
        frontmatter = {
            "schema": APP_LOCAL_SCHEMA,
            "scope": "app-local",
            "appInstallId": snapshot.app_install_id,
            "lastActiveVaultRef": (
                snapshot.registrations[selected_binding_id].ref
                if selected_binding_id is not None
                else snapshot.last_active_vault_ref
            ),
            "knownVaults": known,
            "mvrRegistrySchema": snapshot.schema,
            "mvrRegistryRevision": snapshot.revision,
            "mvrRollbackBindingId": selected_binding_id,
        }
        return _render_markdown_settings(
            frontmatter,
            "# Legacy Registry Rollback Export\nGenerated from the latest committed registry revision.\n",
        ).encode("utf-8")

    def _frontmatter_from_snapshot(self, snapshot: RegistrySnapshot) -> dict[str, Any]:
        frontmatter = copy.deepcopy(snapshot.extensions)
        frontmatter.update(
            {
                "schema": snapshot.schema,
                "authority": snapshot.authority,
                "revision": snapshot.revision,
                "appInstallId": snapshot.app_install_id,
                "lastActiveVaultRef": snapshot.last_active_vault_ref,
                "defaultVaultBindingId": snapshot.default_vault_binding_id,
                "defaultVaultProvenance": snapshot.default_vault_provenance,
                "registrations": {
                    binding_id: _registration_to_frontmatter(item)
                    for binding_id, item in sorted(snapshot.registrations.items())
                },
                "removalTombstones": {
                    binding_id: _tombstone_to_frontmatter(item)
                    for binding_id, item in sorted(snapshot.removal_tombstones.items())
                },
                "transferLineage": [
                    _transfer_lineage_to_frontmatter(item) for item in snapshot.transfer_lineage
                ],
                "settingsRebind": copy.deepcopy(snapshot.settings_rebind),
            }
        )
        return frontmatter

    def _snapshot_from_frontmatter(self, frontmatter: Mapping[str, Any]) -> RegistrySnapshot:
        schema = _optional_str(frontmatter.get("schema"))
        if schema != CURRENT_REGISTRY_SCHEMA:
            raise RegistryError(f"registry schema mismatch: {schema or '<missing>'}")
        authority = _optional_str(frontmatter.get("authority"))
        if authority not in {REGISTRY_AUTHORITY_DORMANT, REGISTRY_AUTHORITY_ACTIVE}:
            raise RegistryError(f"unsupported registry authority state: {authority or '<missing>'}")
        revision_value = frontmatter.get("revision", 0)
        if not isinstance(revision_value, int) or revision_value < 0:
            raise RegistryError("registry revision must be a non-negative integer")
        raw_registrations = frontmatter.get("registrations") or {}
        if not isinstance(raw_registrations, dict):
            raise RegistryError("registry registrations must be a mapping")
        registrations: dict[str, VaultRegistration] = {}
        for binding_id, raw in raw_registrations.items():
            if not isinstance(raw, dict):
                raise RegistryError(f"registration {binding_id} must be a mapping")
            registration = _registration_from_frontmatter(str(binding_id), raw)
            self._validate_registration(registration)
            self._assert_registration_unique(registration, registrations)
            registrations[registration.vault_binding_id] = registration
        raw_tombstones = frontmatter.get("removalTombstones") or {}
        if not isinstance(raw_tombstones, dict):
            raise RegistryError("registry removalTombstones must be a mapping")
        removal_tombstones: dict[str, RemovalTombstone] = {}
        for binding_id, raw in raw_tombstones.items():
            if not isinstance(raw, dict):
                raise RegistryError(f"removal tombstone {binding_id} must be a mapping")
            removal_tombstones[str(binding_id)] = _tombstone_from_frontmatter(
                str(binding_id), raw
            )
        raw_lineage = frontmatter.get("transferLineage") or []
        if not isinstance(raw_lineage, list):
            raise RegistryError("registry transferLineage must be a list")
        transfer_lineage = tuple(_transfer_lineage_from_frontmatter(raw) for raw in raw_lineage)
        app_install_id = _optional_str(frontmatter.get("appInstallId"))
        if app_install_id is None:
            raise RegistryError("registry appInstallId is required")
        extensions = {key: copy.deepcopy(value) for key, value in frontmatter.items() if key not in _REGISTRY_FIELDS}
        if authority == REGISTRY_AUTHORITY_ACTIVE:
            floor = extensions.get("scalarRollback")
            if (
                not isinstance(floor, dict)
                or floor.get("schema") != SCALAR_ROLLBACK_SCHEMA
                or _optional_str(floor.get("targetVaultBindingId")) not in registrations
                or floor.get("forkRegistryRevision") != revision_value
                or floor.get("gatewayPreflight") != "authenticated-mutation-filter"
                or floor.get("nativeGuardPreflight") != "deny-by-default"
                or floor.get("rollForwardLineage") != ROLL_FORWARD_LINEAGE_SCHEMA
                or any(
                    not isinstance(floor.get(key), str)
                    or len(floor[key]) != 64
                    for key in (
                        "composePolicySha256",
                        "gatewayPolicySha256",
                        "nativeLauncherSha256",
                    )
                )
            ):
                raise RegistryError("active registry scalar rollback floor is invalid")
        settings_rebind = frontmatter.get("settingsRebind")
        if settings_rebind is not None and not isinstance(settings_rebind, dict):
            raise RegistryError("settingsRebind must be a mapping")
        default_binding_id, default_provenance = _read_default_from_frontmatter(
            frontmatter, registrations, extensions
        )
        return RegistrySnapshot(
            schema=schema,
            authority=authority,
            revision=revision_value,
            app_install_id=app_install_id,
            last_active_vault_ref=_optional_str(frontmatter.get("lastActiveVaultRef")),
            registrations=registrations,
            removal_tombstones=removal_tombstones,
            transfer_lineage=transfer_lineage,
            settings_rebind=copy.deepcopy(settings_rebind),
            extensions=extensions,
            default_vault_binding_id=default_binding_id,
            default_vault_provenance=default_provenance,
        )

    def _migrate_legacy_frontmatter(self, frontmatter: Mapping[str, Any]) -> RegistrySnapshot:
        app_install_id = _optional_str(frontmatter.get("appInstallId"))
        if app_install_id is None:
            raise RegistryMigrationError("legacy appInstallId is missing")
        raw_known = frontmatter.get("knownVaults") or {}
        if not isinstance(raw_known, dict):
            raise RegistryMigrationError("legacy knownVaults must be a mapping")
        raw_candidates: dict[str, dict[str, Any]] = {}
        for ref, raw in raw_known.items():
            normalized_ref = _optional_str(ref)
            if normalized_ref is None:
                raise RegistryMigrationError("legacy registration ref is blank")
            if not isinstance(raw, dict):
                raise RegistryMigrationError(f"legacy registration {ref} must be a mapping")
            path = _optional_str(raw.get("path"))
            if path is None:
                raise RegistryMigrationError(f"legacy registration {ref} has no path")
            if normalized_ref in raw_candidates:
                raise RegistryMigrationError(f"duplicate normalized legacy registration ref: {normalized_ref}")
            raw_candidates[normalized_ref] = dict(raw)
        candidates, aliases = _coalesce_legacy_candidates(
            raw_candidates,
            last_active_ref=_optional_str(frontmatter.get("lastActiveVaultRef")),
        )
        rebind_key = next(
            (key for key in ("settingsRebind", "settingsRebindV1", "settings_rebind.v1") if key in frontmatter),
            None,
        )
        raw_rebind = copy.deepcopy(frontmatter.get(rebind_key)) if rebind_key else None
        if raw_rebind is not None and not isinstance(raw_rebind, dict):
            raise RegistryMigrationError("settings_rebind.v1 must be a mapping")
        binding_by_ref: dict[str, str] = {}
        rewritten_rebind = copy.deepcopy(raw_rebind)
        if rewritten_rebind is not None:
            for key in ("prior", "candidate", "applied"):
                value = rewritten_rebind.get(key)
                if value is None:
                    continue
                if not isinstance(value, dict):
                    raise RegistryMigrationError(f"settings rebind {key} must be a mapping")
                binding_id = _optional_str(value.get("vaultBindingId"))
                if binding_id is None:
                    raise RegistryMigrationError(f"settings rebind {key} has no provisional vaultBindingId")
                matched_ref = _resolve_legacy_reference(value, candidates, aliases)
                previous = binding_by_ref.get(matched_ref)
                if previous is not None and previous != binding_id:
                    raise RegistryMigrationError("conflicting provisional binding identities")
                if binding_id in binding_by_ref.values() and previous != binding_id:
                    raise RegistryMigrationError("one provisional binding identity matches multiple registrations")
                binding_by_ref[matched_ref] = binding_id
                value["ref"] = matched_ref
                value["vaultBindingId"] = binding_id
        registrations: dict[str, VaultRegistration] = {}
        for ref, raw in candidates.items():
            binding_id = binding_by_ref.get(ref) or f"binding-{uuid4()}"
            if binding_id in registrations:
                raise RegistryMigrationError(f"duplicate vault_binding_id during migration: {binding_id}")
            registrations[binding_id] = VaultRegistration(
                vault_binding_id=binding_id,
                ref=ref,
                path=str(raw["path"]),
                vault_id=_optional_str(raw.get("vaultId")),
                local_instance_id=_optional_str(raw.get("localInstanceId")),
                vault_name=_optional_str(raw.get("vaultName")),
                last_opened_at=_optional_str(raw.get("lastOpenedAt")),
                extensions={key: copy.deepcopy(value) for key, value in raw.items() if key not in _REGISTRATION_FIELDS},
            )
        known_legacy_fields = {
            "schema",
            "scope",
            "appInstallId",
            "lastActiveVaultRef",
            "knownVaults",
            "settingsRebind",
            "settingsRebindV1",
            "settings_rebind.v1",
            "defaultVaultBindingId",
        }
        last_active_vault_ref = _optional_str(frontmatter.get("lastActiveVaultRef"))
        extensions = {
            key: copy.deepcopy(value)
            for key, value in frontmatter.items()
            if key not in known_legacy_fields
        }
        # A legacy payload may already carry an explicit default. It is untrusted:
        # binding identity is minted during this migration, so it is adopted only
        # when it names exactly one migrated registration. Otherwise the raw value
        # is preserved as lineage rather than silently dropped, and the one-time
        # last-active materialization below decides the default instead.
        legacy_default = _optional_str(frontmatter.get("defaultVaultBindingId"))
        default_binding_id: str | None = None
        default_provenance: str | None = None
        if legacy_default is not None and legacy_default in registrations:
            default_binding_id = legacy_default
            default_provenance = DEFAULT_PROVENANCE_EXPLICIT
        elif legacy_default is not None:
            extensions["legacyDefaultVaultBindingId"] = legacy_default
        if default_binding_id is None:
            # MVR-02 one-time materialization: a picker-only legacy install keeps
            # its restart journey by promoting a valid last-active reference to the
            # explicit default exactly once, with recorded provenance.
            default_binding_id = _binding_for_ref(last_active_vault_ref, registrations)
            default_provenance = (
                DEFAULT_PROVENANCE_LEGACY_MIGRATION if default_binding_id else None
            )
        # No separate "migration applied" marker: this branch runs only for an
        # `APP_LOCAL_SCHEMA` document, and the schema transition it performs is
        # itself the once-only guarantee. `default_vault_provenance` already
        # records which producer set the default, which is what the spec asks for.
        return RegistrySnapshot(
            schema=CURRENT_REGISTRY_SCHEMA,
            authority=REGISTRY_AUTHORITY_DORMANT,
            revision=1,
            app_install_id=app_install_id,
            last_active_vault_ref=last_active_vault_ref,
            registrations=registrations,
            settings_rebind=rewritten_rebind,
            extensions=extensions,
            default_vault_binding_id=default_binding_id,
            default_vault_provenance=default_provenance,
        )


def preflight_registry_payload(path: Path) -> RegistrySnapshot:
    store = VaultRegistryStore(path)
    snapshot = store.load()
    _assert_private(path.parent, directory=True)
    for candidate in (
        path,
        store.lock_path,
        store.snapshot_path,
        store.snapshot_checksum_path,
        store.rollback_export_path,
    ):
        _assert_private(candidate, directory=False)
    return snapshot


def _resolve_legacy_reference(
    value: Mapping[str, Any],
    candidates: Mapping[str, Mapping[str, Any]],
    aliases: Mapping[str, str],
) -> str:
    ref = _optional_str(value.get("ref"))
    if ref is not None:
        canonical_ref = aliases.get(ref, ref)
        candidate = candidates.get(canonical_ref)
        if candidate is None:
            raise RegistryMigrationError(f"settings rebind reference is missing from legacy registry: {ref}")
        path = _optional_str(value.get("path"))
        if path is not None and not _same_root(path, str(candidate["path"])):
            raise RegistryMigrationError(f"settings rebind reference/path conflict: {ref}")
        return canonical_ref
    path = _optional_str(value.get("path"))
    if path is None:
        raise RegistryMigrationError("settings rebind reference has neither ref nor path")
    matches = [key for key, candidate in candidates.items() if _same_root(str(candidate["path"]), path)]
    if len(matches) != 1:
        raise RegistryMigrationError("ambiguous settings rebind path migration")
    return matches[0]


def _coalesce_legacy_candidates(
    candidates: Mapping[str, Mapping[str, Any]],
    *,
    last_active_ref: str | None,
) -> tuple[dict[str, dict[str, Any]], dict[str, str]]:
    groups: list[list[str]] = []
    for ref, raw in candidates.items():
        matching = [group for group in groups if _same_root(str(candidates[group[0]]["path"]), str(raw["path"]))]
        if len(matching) > 1:
            merged_group = [ref]
            for group in matching:
                groups.remove(group)
                merged_group.extend(group)
            groups.append(merged_group)
        elif matching:
            matching[0].append(ref)
        else:
            groups.append([ref])

    coalesced: dict[str, dict[str, Any]] = {}
    aliases: dict[str, str] = {}
    for refs in groups:
        primary = last_active_ref if last_active_ref in refs else sorted(refs)[0]
        merged = copy.deepcopy(dict(candidates[primary]))
        for ref in refs:
            aliases[ref] = primary
            if ref == primary:
                continue
            for key, value in candidates[ref].items():
                if key == "path":
                    continue
                if key not in merged or merged[key] is None:
                    merged[key] = copy.deepcopy(value)
                elif value is not None and merged[key] != value:
                    raise RegistryMigrationError(
                        f"conflicting alias metadata for legacy registrations: {primary}, {ref}"
                    )
        coalesced[primary] = merged
    return coalesced, aliases


def _canonical_path(value: str) -> str:
    return _root_identity(value).canonical_path


def _root_identity(value: str) -> FilesystemRootIdentity:
    try:
        return resolve_filesystem_root_identity(value)
    except FilesystemIdentityError as exc:
        raise RegistryError(str(exc)) from exc


def _same_root(left: str, right: str) -> bool:
    return same_filesystem_root(_root_identity(left), _root_identity(right))


def _registration_to_frontmatter(item: VaultRegistration) -> dict[str, Any]:
    value = copy.deepcopy(item.extensions)
    value.update(
        {
            "ref": item.ref,
            "path": item.path,
            "vaultId": item.vault_id,
            "vaultName": item.vault_name,
            "localInstanceId": item.local_instance_id,
            "lastOpenedAt": item.last_opened_at,
        }
    )
    return value


def _registration_from_frontmatter(binding_id: str, raw: Mapping[str, Any]) -> VaultRegistration:
    ref = _optional_str(raw.get("ref"))
    path = _optional_str(raw.get("path"))
    if ref is None or path is None:
        raise RegistryError(f"registration {binding_id} requires ref and path")
    return VaultRegistration(
        vault_binding_id=binding_id,
        ref=ref,
        path=path,
        vault_id=_optional_str(raw.get("vaultId")),
        local_instance_id=_optional_str(raw.get("localInstanceId")),
        vault_name=_optional_str(raw.get("vaultName")),
        last_opened_at=_optional_str(raw.get("lastOpenedAt")),
        extensions={key: copy.deepcopy(value) for key, value in raw.items() if key not in _REGISTRATION_FIELDS},
    )


def _tombstone_to_frontmatter(item: RemovalTombstone) -> dict[str, Any]:
    return {
        "ref": item.ref,
        "path": item.path,
        "vaultId": item.vault_id,
        "localInstanceId": item.local_instance_id,
        "contentEpoch": item.content_epoch,
    }


def _tombstone_from_frontmatter(
    binding_id: str, raw: Mapping[str, Any]
) -> RemovalTombstone:
    ref = _optional_str(raw.get("ref"))
    path = _optional_str(raw.get("path"))
    epoch = raw.get("contentEpoch")
    if ref is None or path is None or not isinstance(epoch, int) or epoch < 1:
        raise RegistryError(f"removal tombstone {binding_id} is invalid")
    return RemovalTombstone(
        vault_binding_id=binding_id,
        ref=ref,
        path=path,
        vault_id=_optional_str(raw.get("vaultId")),
        local_instance_id=_optional_str(raw.get("localInstanceId")),
        content_epoch=epoch,
    )


def _transfer_lineage_to_frontmatter(item: TransferLineage) -> dict[str, Any]:
    return {
        "sourceBindingId": item.source_binding_id,
        "destinationBindingId": item.destination_binding_id,
        "localInstanceId": item.local_instance_id,
        "vaultId": item.vault_id,
        "sourceChannelId": item.source_channel_id,
        "destinationChannelId": item.destination_channel_id,
        "sourceRegistryRevision": item.source_registry_revision,
        "destinationRegistryRevision": item.destination_registry_revision,
        "ownershipTransferId": item.ownership_transfer_id,
    }


def _transfer_lineage_from_frontmatter(raw: object) -> TransferLineage:
    if not isinstance(raw, dict):
        raise RegistryError("transfer lineage entry must be a mapping")
    source = _optional_str(raw.get("sourceBindingId"))
    destination = _optional_str(raw.get("destinationBindingId"))
    if source is None or destination is None:
        raise RegistryError("transfer lineage entry requires source and destination")
    source_channel = _optional_str(raw.get("sourceChannelId"))
    destination_channel = _optional_str(raw.get("destinationChannelId"))
    transfer_id = _optional_str(raw.get("ownershipTransferId"))
    source_revision = raw.get("sourceRegistryRevision")
    destination_revision = raw.get("destinationRegistryRevision")
    if (
        source_channel is None
        or destination_channel is None
        or transfer_id is None
        or not isinstance(source_revision, int)
        or not isinstance(destination_revision, int)
    ):
        raise RegistryError("transfer lineage entry is incomplete")
    return TransferLineage(
        source_binding_id=source,
        destination_binding_id=destination,
        local_instance_id=_optional_str(raw.get("localInstanceId")),
        vault_id=_optional_str(raw.get("vaultId")),
        source_channel_id=source_channel,
        destination_channel_id=destination_channel,
        source_registry_revision=source_revision,
        destination_registry_revision=destination_revision,
        ownership_transfer_id=transfer_id,
    )


def _split_rendered(text: str, path: Path) -> tuple[dict[str, Any], str]:
    lines = text.splitlines()
    in_conflict = False
    saw_separator = False
    for line in lines:
        if line.startswith("<<<<<<<"):
            in_conflict = True
            saw_separator = False
        elif in_conflict and line.startswith("======="):
            saw_separator = True
        elif in_conflict and saw_separator and line.startswith(">>>>>>>"):
            raise RegistryParseError(f"registry contains Git conflict markers: {path}")
    if not text.startswith("---\n"):
        raise RegistryParseError(f"registry is missing YAML frontmatter: {path}")
    parts = text.split("---", 2)
    if len(parts) < 3:
        raise RegistryParseError(f"registry frontmatter is malformed: {path}")
    try:
        data = yaml.safe_load(parts[1]) or {}
    except yaml.YAMLError as exc:
        raise RegistryParseError(f"registry YAML is invalid: {path}") from exc
    if not isinstance(data, dict):
        raise RegistryParseError(f"registry frontmatter must be a mapping: {path}")
    body = parts[2].removeprefix("\n")
    return data, body


def _read_document(path: Path) -> _RegistryDocument:
    frontmatter, body = _split_rendered(path.read_text(encoding="utf-8"), path)
    return _RegistryDocument(frontmatter=frontmatter, body=body)


def _render_markdown_settings(frontmatter: Mapping[str, Any], body: str) -> str:
    yaml_block = yaml.safe_dump(dict(frontmatter), sort_keys=False, allow_unicode=True).strip()
    normalized_body = body if body.startswith("\n") else f"\n{body}"
    if not normalized_body.endswith("\n"):
        normalized_body += "\n"
    return f"---\n{yaml_block}\n---\n{normalized_body}"


def _ensure_private_directory(path: Path) -> None:
    if path.exists():
        _assert_private(path, directory=True)
        return
    path.mkdir(parents=True, exist_ok=False, mode=0o700)
    os.chmod(path, 0o700)
    _assert_private(path, directory=True)


def _upgrade_owned_legacy_directory(path: Path) -> None:
    if not path.exists():
        _ensure_private_directory(path)
        return
    metadata = path.lstat()
    if not stat.S_ISDIR(metadata.st_mode) or metadata.st_uid != os.geteuid():
        raise RegistrySecurityError(f"unsafe legacy registry directory for {path.name}")
    os.chmod(path, 0o700)
    _assert_private(path, directory=True)


def _atomic_private_write(path: Path, payload: bytes) -> None:
    _atomic_private_write_raw(path, payload)


def _atomic_private_write_raw(path: Path, payload: bytes) -> None:
    _ensure_private_directory(path.parent)
    descriptor, temporary_name = tempfile.mkstemp(prefix=f".{path.name}.", dir=path.parent)
    temporary = Path(temporary_name)
    try:
        os.fchmod(descriptor, 0o600)
        with os.fdopen(descriptor, "wb", closefd=True) as handle:
            handle.write(payload)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, path)
        os.chmod(path, 0o600)
        _fsync_directory(path.parent)
    except BaseException:
        try:
            os.close(descriptor)
        except OSError:
            pass
        temporary.unlink(missing_ok=True)
        raise


def _fsync_directory(path: Path) -> None:
    directory_flags = os.O_RDONLY | getattr(os, "O_DIRECTORY", 0)
    directory_descriptor = os.open(path, directory_flags)
    try:
        os.fsync(directory_descriptor)
    finally:
        os.close(directory_descriptor)


def _read_previous_transaction_file(path: Path, *, allow_legacy_mode: bool = False) -> bytes | None:
    if not os.path.lexists(path):
        return None
    metadata = path.lstat()
    if not stat.S_ISREG(metadata.st_mode) or metadata.st_uid != os.geteuid():
        raise RegistrySecurityError(f"unsafe registry transaction path for {path.name}")
    if not allow_legacy_mode:
        _assert_private_stat(metadata, path, directory=False)
    return path.read_bytes()


def _assert_private(path: Path, *, directory: bool) -> None:
    if not path.exists():
        raise RegistryError(f"required registry path is missing: {path}")
    _assert_private_stat(path.lstat(), path, directory=directory)


def _assert_private_stat(metadata: os.stat_result, path: Path, *, directory: bool) -> None:
    expected = 0o700 if directory else 0o600
    actual = metadata.st_mode & 0o777
    expected_kind = stat.S_ISDIR(metadata.st_mode) if directory else stat.S_ISREG(metadata.st_mode)
    if not expected_kind:
        raise RegistrySecurityError(f"unsafe registry path type for {path.name}")
    if metadata.st_uid != os.geteuid():
        raise RegistrySecurityError(f"unsafe registry ownership for {path.name}")
    if actual != expected:
        raise RegistrySecurityError(
            f"unsafe registry mode for {path.name}: {oct(actual)}; expected {oct(expected)}"
        )


def _can_host(directory: Path) -> bool:
    probe = directory
    while True:
        if probe.exists():
            return probe.is_dir() and os.access(probe, os.W_OK)
        parent = probe.parent
        if parent == probe:
            return False
        probe = parent


def _usable_home() -> Path | None:
    home_env = os.getenv("HOME", "").strip()
    if home_env:
        candidate = Path(home_env)
    else:
        try:
            candidate = Path.home()
        except (RuntimeError, OSError):
            return None
    if str(candidate) == candidate.anchor:
        return None
    return candidate


def default_app_local_settings_path() -> Path:
    override = os.getenv("DESIGN_HANDOFF_APP_LOCAL_SETTINGS", "").strip()
    if override:
        return Path(override).expanduser()
    xdg = os.getenv("XDG_DATA_HOME", "").strip()
    if xdg:
        base = Path(xdg).expanduser() / _APP_DIR_NAME
        if _can_host(base):
            return base / _SETTINGS_FILENAME
    home = _usable_home()
    if home is not None:
        base = home / "Library" / "Application Support" / _APP_DIR_NAME
        if _can_host(base):
            return base / _SETTINGS_FILENAME
    base = _CONTAINER_RUNTIME_DIR / "agentic-pkm"
    if _can_host(base):
        return base / _SETTINGS_FILENAME
    return Path(tempfile.gettempdir()) / "agentic-pkm" / _SETTINGS_FILENAME


@dataclass(frozen=True)
class KnownVaultRef:
    ref: str
    path: str
    vault_id: str | None = None
    vault_name: str | None = None
    local_instance_id: str | None = None
    last_opened_at: str | None = None


@dataclass
class AppLocalSettings:
    app_install_id: str
    last_active_vault_ref: str | None = None
    known_vaults: dict[str, KnownVaultRef] = field(default_factory=dict)


def _app_local_from_registry(snapshot: RegistrySnapshot) -> AppLocalSettings:
    return AppLocalSettings(
        app_install_id=snapshot.app_install_id,
        last_active_vault_ref=snapshot.last_active_vault_ref,
        known_vaults={
            item.ref: KnownVaultRef(
                ref=item.ref,
                path=item.path,
                vault_id=item.vault_id,
                vault_name=item.vault_name,
                local_instance_id=item.local_instance_id,
                last_opened_at=item.last_opened_at,
            )
            for item in snapshot.registrations.values()
        },
    )


class AppLocalSettingsStore:
    """Legacy scalar authority retained until the MVR-01B/01C cutover."""

    def __init__(self, path: Path | None = None, markdown_store: _MarkdownStore | None = None) -> None:
        self._authority_aware = path is None
        self.path = path or default_app_local_settings_path()
        if markdown_store is None:
            from app.vault.markdown_settings import MarkdownSettingsStore

            markdown_store = MarkdownSettingsStore()
        self.markdown_store = markdown_store

    def load(self) -> AppLocalSettings:
        runtime = self._active_registry_runtime()
        if runtime is not None:
            return _app_local_from_registry(runtime.registry.load())
        if not self.path.exists():
            settings = AppLocalSettings(app_install_id=f"app-{uuid4()}")
            self.save(settings)
            return settings
        doc = self.markdown_store.read(self.path)
        raw_known = doc.frontmatter.get("knownVaults") or {}
        known: dict[str, KnownVaultRef] = {}
        if isinstance(raw_known, dict):
            for ref, value in raw_known.items():
                if not isinstance(value, dict):
                    continue
                path = str(value.get("path") or "").strip()
                if not path:
                    continue
                known[str(ref)] = KnownVaultRef(
                    ref=str(ref),
                    path=path,
                    vault_id=_optional_str(value.get("vaultId")),
                    vault_name=_optional_str(value.get("vaultName")),
                    local_instance_id=_optional_str(value.get("localInstanceId")),
                    last_opened_at=_optional_str(value.get("lastOpenedAt")),
                )
        install_id = str(doc.frontmatter.get("appInstallId") or "").strip() or f"app-{uuid4()}"
        return AppLocalSettings(
            app_install_id=install_id,
            last_active_vault_ref=_optional_str(doc.frontmatter.get("lastActiveVaultRef")),
            known_vaults=known,
        )

    def save(self, settings: AppLocalSettings) -> None:
        runtime = self._active_registry_runtime()
        if runtime is not None:
            for item in settings.known_vaults.values():
                self._upsert_active(runtime, item, make_active=False)
            if settings.last_active_vault_ref is not None:
                active = settings.known_vaults.get(settings.last_active_vault_ref)
                if active is None:
                    raise RegistryError("active app-local reference is not registered")
                self._upsert_active(runtime, active, make_active=True)
            return
        known = {
            ref: {
                "path": item.path,
                "vaultId": item.vault_id,
                "vaultName": item.vault_name,
                "localInstanceId": item.local_instance_id,
                "lastOpenedAt": item.last_opened_at,
            }
            for ref, item in sorted(settings.known_vaults.items())
        }
        old_frontmatter: dict[str, object] = {}
        if self.path.exists():
            try:
                old_frontmatter = dict(self.markdown_store.read(self.path).frontmatter)
            except Exception:
                # Receipt observation must never prevent recovery from a corrupt file.
                old_frontmatter = {}
        new_frontmatter = {
            "schema": APP_LOCAL_SCHEMA,
            "scope": "app-local",
            "appInstallId": settings.app_install_id,
            "lastActiveVaultRef": settings.last_active_vault_ref,
            "knownVaults": known,
        }
        self.markdown_store.write_frontmatter(
            self.path,
            new_frontmatter,
            body=(
                "# App Local Settings\n"
                "This file stores local application preferences and recently used vaults.\n"
                "It does not define project behavior.\n"
            ),
        )
        emit_settings_write_receipts_for_changes(
            old_values=old_frontmatter,
            new_values=new_frontmatter,
            surface="app-local",
            actor="system",
            file=self.path,
        )

    def upsert_known_vault(self, item: KnownVaultRef, *, make_active: bool = True) -> AppLocalSettings:
        runtime = self._active_registry_runtime()
        if runtime is not None:
            self._upsert_active(runtime, item, make_active=make_active)
            return _app_local_from_registry(runtime.registry.load())
        settings = self.load()
        settings.known_vaults[item.ref] = item
        if make_active:
            settings.last_active_vault_ref = item.ref
        self.save(settings)
        return settings

    def _active_registry_runtime(self) -> InstanceRegistryRuntime | None:
        if not self._authority_aware:
            return None
        registry_value = os.getenv("INSTANCE_VAULT_REGISTRY_PATH", "").strip()
        ownership_value = os.getenv("INSTANCE_OWNERSHIP_ROOT", "").strip()
        if not registry_value or not ownership_value:
            return None
        registry_path = Path(registry_value).expanduser().resolve(strict=False)
        if not registry_path.is_file():
            return None
        snapshot = VaultRegistryStore(registry_path).load()
        if snapshot.authority != REGISTRY_AUTHORITY_ACTIVE:
            return None
        from app.instance.runtime import _load_active_registry_runtime

        return _load_active_registry_runtime(
            registry_path=registry_path,
            ownership_root=Path(ownership_value).expanduser().resolve(strict=False),
            channel=os.getenv("PKM_ENVIRONMENT", "dev"),
        )

    def _upsert_active(
        self,
        runtime: InstanceRegistryRuntime,
        item: KnownVaultRef,
        *,
        make_active: bool,
    ) -> None:
        from app.instance._storage_boundary import _STORAGE_MUTATION_CAPABILITY

        snapshot = runtime.registry.load()
        matches = [
            registration
            for registration in snapshot.registrations.values()
            if Path(registration.path).expanduser().resolve(strict=True)
            == Path(item.path).expanduser().resolve(strict=True)
        ]
        if len(matches) > 1:
            raise RegistryError("active registry path identity is ambiguous")
        registration = (
            matches[0]
            if matches
            else runtime.production_register(Path(item.path), producer="picker")
        )
        runtime.registry.remember_registration(
            registration.vault_binding_id,
            item,
            make_active=make_active,
            _capability=_STORAGE_MUTATION_CAPABILITY,
        )

    def backup_corrupt_and_reset(self) -> Path | None:
        if not self.path.exists():
            return None
        stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
        backup = self.path.with_name(f"{self.path.name}.corrupt-{stamp}")
        suffix = 1
        while backup.exists():
            backup = self.path.with_name(f"{self.path.name}.corrupt-{stamp}-{suffix}")
            suffix += 1
        os.replace(self.path, backup)
        return backup


def _optional_str(value: object) -> str | None:
    text = str(value).strip() if value is not None else ""
    return text or None


def _is_sha256(value: str) -> bool:
    return len(value) == 64 and all(character in "0123456789abcdef" for character in value)


__all__ = [
    "APP_LOCAL_SCHEMA",
    "CURRENT_REGISTRY_SCHEMA",
    "DEFAULT_PROVENANCE_EXPLICIT",
    "DEFAULT_PROVENANCE_FIRST_INITIALIZE",
    "DEFAULT_PROVENANCE_FIRST_OPEN_EXISTING",
    "DEFAULT_PROVENANCE_LEGACY_MIGRATION",
    "DEFAULT_PROVENANCE_LEGACY_UNLABELLED",
    "DEFAULT_PROVENANCE_ROLL_FORWARD_RESTORE",
    "DEFAULT_VAULT_PROVENANCES",
    "AppLocalSettings",
    "AppLocalSettingsStore",
    "CapabilityNotReadyError",
    "KnownVaultRef",
    "RegistryActivationProof",
    "RegistryDefaultConflict",
    "RegistryError",
    "RegistryMigrationError",
    "RegistryRevisionConflict",
    "RegistrySecurityError",
    "RegistrySnapshot",
    "RemovalTombstone",
    "TransferLineage",
    "VaultRegistration",
    "VaultRegistryStore",
    "default_app_local_settings_path",
    "preflight_registry_payload",
]
