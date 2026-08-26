from __future__ import annotations

import base64
import fcntl
import hashlib
import hmac
import json
import os
import secrets
import stat
import tempfile
from contextlib import contextmanager
from dataclasses import asdict, dataclass, field, replace
from pathlib import Path
from typing import Any, Callable, Iterator, Mapping, Sequence
from uuid import uuid4

from app.instance._storage_boundary import (
    _StorageMutationCapability,
    _require_storage_mutation_capability,
)
from app.instance.filesystem_identity import (
    FilesystemIdentityError,
    resolve_filesystem_root_identity,
)


LEGACY_LEDGER_SCHEMA = "agentic-pkm.host-ownership-ledger.v1"
LEDGER_SCHEMA = "agentic-pkm.host-ownership-ledger.v2"
KEY_SCHEMA = "agentic-pkm.host-ownership-key.v1"
ROTATION_SCHEMA = "agentic-pkm.host-ownership-key-rotation.v1"


class LedgerError(RuntimeError):
    """Host-global ownership state cannot be used safely."""


class LedgerCollisionError(LedgerError):
    """A physical root is already owned by an incompatible domain."""


class LedgerKeyError(LedgerError):
    """The shared HMAC key is missing, unsafe, or inconsistent."""


@dataclass(frozen=True)
class LegacyOwner:
    channel_id: str
    vault_binding_id: str
    root: Path


@dataclass(frozen=True)
class OwnershipLease:
    channel_id: str
    vault_binding_id: str
    root_fingerprint: str
    ancestor_fingerprints: tuple[str, ...]
    sealed_root: str
    state: str = "active"


@dataclass(frozen=True)
class TransferReservation:
    transfer_id: str
    source_channel_id: str
    source_binding_id: str
    destination_channel_id: str
    destination_binding_id: str
    root_fingerprint: str
    ancestor_fingerprints: tuple[str, ...]
    sealed_root: str


@dataclass(frozen=True)
class OwnershipTransferLineage:
    transfer_id: str
    source_channel_id: str
    source_binding_id: str
    destination_channel_id: str
    destination_binding_id: str
    root_fingerprint: str
    ancestor_fingerprints: tuple[str, ...]
    sealed_root: str


@dataclass(frozen=True)
class LedgerSnapshot:
    schema: str
    generation: int
    key_id: str
    leases: dict[str, OwnershipLease] = field(default_factory=dict)
    tombstones: dict[str, OwnershipLease] = field(default_factory=dict)
    transfer: TransferReservation | None = None
    transfer_lineage: tuple[OwnershipTransferLineage, ...] = ()
    legacy_bootstrap_complete: bool = False


@dataclass(frozen=True)
class _KeyMaterial:
    key_id: str
    generation: int
    secret: bytes


class OwnershipLedger:
    """Private host-global root ownership ledger shared by all channels.

    The persisted ledger contains HMAC fingerprints and an authenticated sealed
    root locator, never plaintext host paths. The locator exists solely so a
    globally fenced key rotation can re-fingerprint live and retired roots.
    """

    def __init__(self, root: Path) -> None:
        self.root = root
        self.path = root / "ownership-ledger.json"
        self.key_path = root / "ownership-key.json"
        self.lock_path = root / "ownership-ledger.lock"
        self.rotation_path = root / "ownership-key-rotation.json"

    def load(self) -> LedgerSnapshot:
        with self._locked():
            key = self._load_or_create_key_locked()
            return self._load_or_create_ledger_locked(key)

    def require_existing(self) -> LedgerSnapshot:
        """Load an established ledger without creating any missing authority state."""

        self._assert_existing_artifacts()
        with self._locked():
            key = self._load_or_create_key_locked(allow_create=False)
            return self._load_or_create_ledger_locked(key, allow_create=False)

    def authenticate_scalar_rollback_session(
        self,
        payload: Mapping[str, object],
        *,
        _capability: _StorageMutationCapability | None = None,
    ) -> dict[str, object]:
        """Authenticate rollback lineage with the host key unavailable to the old image."""

        _require_storage_mutation_capability(_capability)
        self._assert_existing_artifacts()
        with self._locked():
            key = self._load_or_create_key_locked(allow_create=False)
            self._load_or_create_ledger_locked(key, allow_create=False)
            encoded = json.dumps(
                dict(payload),
                sort_keys=True,
                separators=(",", ":"),
            ).encode("utf-8")
            return {
                "keyId": key.key_id,
                "keyGeneration": key.generation,
                "hmacSha256": hmac.new(key.secret, encoded, hashlib.sha256).hexdigest(),
            }

    def verify_scalar_rollback_session(
        self,
        payload: Mapping[str, object],
        authentication: Mapping[str, object],
        *,
        _capability: _StorageMutationCapability | None = None,
    ) -> None:
        """Fail when a rollback fork receipt is forged or bound to another key."""

        _require_storage_mutation_capability(_capability)
        self._assert_existing_artifacts()
        with self._locked():
            key = self._load_or_create_key_locked(allow_create=False)
            self._load_or_create_ledger_locked(key, allow_create=False)
            encoded = json.dumps(
                dict(payload),
                sort_keys=True,
                separators=(",", ":"),
            ).encode("utf-8")
            expected = hmac.new(key.secret, encoded, hashlib.sha256).hexdigest()
            if (
                authentication.get("keyId") != key.key_id
                or authentication.get("keyGeneration") != key.generation
                or not hmac.compare_digest(
                    str(authentication.get("hmacSha256") or ""),
                    expected,
                )
            ):
                raise LedgerKeyError("scalar rollback session authentication failed")

    def authenticate_principal_cutover_receipt(
        self,
        payload: Mapping[str, object],
        *,
        _capability: _StorageMutationCapability | None = None,
    ) -> dict[str, object]:
        """Authenticate one attempt-local clean-failure receipt."""

        _require_storage_mutation_capability(_capability)
        self._assert_existing_artifacts()
        with self._locked():
            key = self._load_or_create_key_locked(allow_create=False)
            self._load_or_create_ledger_locked(key, allow_create=False)
            encoded = json.dumps(
                dict(payload), sort_keys=True, separators=(",", ":")
            ).encode("utf-8")
            return {
                "keyId": key.key_id,
                "keyGeneration": key.generation,
                "hmacSha256": hmac.new(key.secret, encoded, hashlib.sha256).hexdigest(),
            }

    def verify_principal_cutover_receipt(
        self,
        payload: Mapping[str, object],
        authentication: Mapping[str, object],
        *,
        _capability: _StorageMutationCapability | None = None,
    ) -> None:
        """Reject a forged or stale-key principal cutover receipt."""

        _require_storage_mutation_capability(_capability)
        self._assert_existing_artifacts()
        with self._locked():
            key = self._load_or_create_key_locked(allow_create=False)
            self._load_or_create_ledger_locked(key, allow_create=False)
            encoded = json.dumps(
                dict(payload), sort_keys=True, separators=(",", ":")
            ).encode("utf-8")
            expected = hmac.new(key.secret, encoded, hashlib.sha256).hexdigest()
            if (
                authentication.get("keyId") != key.key_id
                or authentication.get("keyGeneration") != key.generation
                or not hmac.compare_digest(
                    str(authentication.get("hmacSha256") or ""), expected
                )
            ):
                raise LedgerKeyError("principal cutover receipt authentication failed")

    def require_scalar_rollback_ready(
        self,
        *,
        channel_id: str,
        registrations: Mapping[str, Path | None],
    ) -> None:
        """Reject rollback while any ownership transition is pending or mismatched.

        A ``None`` root checks lease coverage only. This lets the selected-only
        rollback guard prove every binding is actively owned without mounting
        every content root; the selected binding still supplies its mounted
        root and must match the ledger's authenticated filesystem identity.
        """

        self._assert_existing_artifacts()
        with self._locked():
            key = self._load_or_create_key_locked(allow_create=False)
            current = self._load_or_create_ledger_locked(key, allow_create=False)
            if current.transfer is not None or any(
                lease.state != "active" for lease in current.leases.values()
            ):
                raise LedgerError(
                    "scalar rollback requires no pending ownership transition"
                )
            channel_leases = {
                binding_id: lease
                for binding_id, lease in current.leases.items()
                if lease.channel_id == channel_id
            }
            if set(channel_leases) != set(registrations):
                raise LedgerError(
                    "scalar rollback requires one active lease per registration"
                )
            for binding_id, root in registrations.items():
                lease = channel_leases[binding_id]
                if root is not None and not self._matches_materialized_root(lease, root, key):
                    raise LedgerError(
                        "scalar rollback registration ownership is inconsistent"
                    )

    def pending_registration(
        self,
        *,
        channel_id: str,
        root: Path,
    ) -> OwnershipLease | None:
        """Return the unique prepared registration for a physical root, if any."""

        self._assert_existing_artifacts()
        with self._locked():
            key = self._load_or_create_key_locked(allow_create=False)
            current = self._load_or_create_ledger_locked(key, allow_create=False)
            matches = [
                lease
                for lease in current.leases.values()
                if lease.channel_id == channel_id
                and lease.state == "pending"
                and self._matches_complete_root_identity(lease, root, key)
            ]
            if len(matches) > 1:
                raise LedgerError(
                    "multiple pending ownership reservations match one registration root"
                )
            return matches[0] if matches else None

    def resolve_live_owner_bindings(
        self,
        owners: Sequence[LegacyOwner],
        *,
        skip_unadopted: bool = False,
    ) -> tuple[LegacyOwner, ...]:
        """Fill omitted owner binding IDs from the authenticated live ledger.

        With ``skip_unadopted``, an owner that carries no binding ID, matches
        no active lease, **and whose root is not materialized in this
        process's filesystem view** is treated as a config-derived candidate
        the ledger never adopted (a root bound after legacy bootstrap
        completed, seen from a verifier in another mount namespace). It holds
        no lease, so it cannot participate in lease consistency and is
        omitted from the result instead of failing resolution (#4371). A
        lease-less owner whose root IS locally materialized stays fail-closed
        — there the verifier can adjudicate, and a missing lease is
        indistinguishable from a ledger that lost one. An ambiguous match
        always fails.
        """

        self._assert_existing_artifacts()
        with self._locked():
            key = self._load_or_create_key_locked(allow_create=False)
            current = self._load_or_create_ledger_locked(key, allow_create=False)
            resolved: list[LegacyOwner] = []
            for owner in owners:
                if owner.vault_binding_id:
                    resolved.append(owner)
                    continue
                try:
                    matches = [
                        binding_id
                        for binding_id, lease in current.leases.items()
                        if lease.channel_id == owner.channel_id
                        and lease.state == "active"
                        and self._matches_complete_root_identity(lease, owner.root, key)
                    ]
                    if not matches:
                        # The inventory can retain the host spelling while an
                        # adopted lease was minted through a bind-mounted
                        # runtime spelling.  Complete path identity is not
                        # portable across those mount namespaces, but a
                        # materialized root fingerprint is.  Keep the
                        # fallback unique so it only adopts an authenticated
                        # physical owner, never a path-like candidate.
                        matches = [
                            binding_id
                            for binding_id, lease in current.leases.items()
                            if lease.channel_id == owner.channel_id
                            and lease.state == "active"
                            and self._matches_materialized_root(lease, owner.root, key)
                        ]
                    unmaterialized = not resolve_filesystem_root_identity(
                        owner.root
                    ).materialized
                except FilesystemIdentityError as exc:
                    raise LedgerError(
                        "cannot resolve omitted live-owner binding identity"
                    ) from exc
                if len(matches) > 1:
                    raise LedgerError(
                        "omitted live-owner binding identity is not unambiguous"
                    )
                if not matches:
                    if skip_unadopted and unmaterialized:
                        continue
                    raise LedgerError(
                        "omitted live-owner binding matches no live lease"
                    )
                resolved.append(
                    LegacyOwner(owner.channel_id, matches[0], owner.root)
                )
            return tuple(resolved)

    def capture_backup_artifacts(
        self,
        *,
        capture_registry_artifacts: Callable[[], Mapping[str, bytes]],
    ) -> dict[str, bytes]:
        """Capture registry and ownership bytes as one immutable lock generation.

        Ledger writers that need registry state already acquire locks in
        ledger-then-registry order. Backup uses that same order so registry
        mutation and key rotation cannot interleave the captured artifacts.
        """

        self._assert_existing_artifacts()
        with self._locked():
            key = self._load_or_create_key_locked(allow_create=False)
            self._load_or_create_ledger_locked(key, allow_create=False)
            payloads = dict(capture_registry_artifacts())
            for name, source in (
                ("ownership-ledger.json", self.path),
                ("ownership-key.json", self.key_path),
            ):
                if not source.is_file():
                    raise LedgerKeyError(
                        "established registry requires protected ownership ledger "
                        "and key recovery"
                    )
                payloads[name] = source.read_bytes()
            return payloads

    def require_registry_consistency(
        self,
        *,
        channel_id: str,
        registrations: Mapping[str, Path | None],
        tombstones: Mapping[str, Path | None],
        transfer_lineage: Sequence[Mapping[str, str]],
        global_live_owners: Sequence[LegacyOwner],
        require_materialized_roots: bool = True,
    ) -> LedgerSnapshot:
        """Authenticate one channel registry and the complete host-global ledger."""

        self._assert_existing_artifacts()
        with self._locked():
            key = self._load_or_create_key_locked(allow_create=False)
            current = self._load_or_create_ledger_locked(key, allow_create=False)
            if current.transfer is not None:
                raise LedgerError(
                    "registry/ledger consistency cannot commit an in-progress transfer"
                )

            ledger_live_owners: set[tuple[str, str]] = set()
            ledger_live_roots: list[tuple[str, str, str]] = []
            for binding_id, lease in current.leases.items():
                if (
                    binding_id != lease.vault_binding_id
                    or lease.state != "active"
                    or not self._has_authenticated_stored_identity(lease, key)
                    or (
                        require_materialized_roots
                        and not self._has_complete_self_identity(lease, key)
                    )
                ):
                    raise LedgerError(
                        "registry/ledger consistency found an invalid host-global live lease"
                    )
                ledger_live_owners.add((lease.channel_id, lease.vault_binding_id))
                ledger_live_roots.append(
                    (
                        lease.channel_id,
                        lease.vault_binding_id,
                        lease.root_fingerprint,
                    )
                )
            expected_live_owners = {
                (owner.channel_id, owner.vault_binding_id)
                for owner in global_live_owners
            }
            if ledger_live_owners != expected_live_owners:
                raise LedgerError(
                    "registry/ledger consistency requires one live lease per global owner"
                )
            if require_materialized_roots:
                try:
                    expected_live_roots = [
                        (
                            owner.channel_id,
                            owner.vault_binding_id,
                            self._lease_for_root(
                                channel_id=owner.channel_id,
                                vault_binding_id=owner.vault_binding_id,
                                root=owner.root,
                                key=key,
                                state="active",
                            ).root_fingerprint,
                        )
                        for owner in global_live_owners
                    ]
                except FilesystemIdentityError as exc:
                    raise LedgerError(
                        "registry/ledger consistency cannot resolve global live-owner identity"
                    ) from exc
                if sorted(ledger_live_roots) != sorted(expected_live_roots):
                    raise LedgerError(
                        "registry/ledger consistency requires one live lease per global owner"
                    )

            for binding_id, retired in current.tombstones.items():
                if (
                    binding_id != retired.vault_binding_id
                    or retired.state != "retired"
                    or not self._has_authenticated_stored_identity(retired, key)
                    or (
                        require_materialized_roots
                        and not self._has_complete_self_identity(retired, key)
                    )
                ):
                    raise LedgerError(
                        "registry/ledger consistency found an invalid host-global tombstone"
                    )

            lineage_identities: set[tuple[str, str, str, str, str]] = set()
            lineage_transfer_ids: set[str] = set()
            for item in current.transfer_lineage:
                identity = (
                    item.transfer_id,
                    item.source_channel_id,
                    item.source_binding_id,
                    item.destination_channel_id,
                    item.destination_binding_id,
                )
                source = current.tombstones.get(item.source_binding_id)
                destination = current.leases.get(
                    item.destination_binding_id
                ) or current.tombstones.get(item.destination_binding_id)
                lineage_lease = OwnershipLease(
                    channel_id=item.destination_channel_id,
                    vault_binding_id=item.destination_binding_id,
                    root_fingerprint=item.root_fingerprint,
                    ancestor_fingerprints=item.ancestor_fingerprints,
                    sealed_root=item.sealed_root,
                    state="lineage",
                )
                if (
                    identity in lineage_identities
                    or any(
                        not isinstance(value, str) or not value.strip()
                        for value in identity
                    )
                    or item.transfer_id in lineage_transfer_ids
                    or item.source_channel_id == item.destination_channel_id
                    or item.source_binding_id == item.destination_binding_id
                    or source is None
                    or destination is None
                    or source.channel_id != item.source_channel_id
                    or destination.channel_id != item.destination_channel_id
                    or source.root_fingerprint != item.root_fingerprint
                    or destination.root_fingerprint != item.root_fingerprint
                    or source.ancestor_fingerprints != item.ancestor_fingerprints
                    or destination.ancestor_fingerprints != item.ancestor_fingerprints
                    or not self._has_authenticated_stored_identity(
                        lineage_lease, key
                    )
                    or (
                        require_materialized_roots
                        and not self._has_complete_self_identity(lineage_lease, key)
                    )
                ):
                    raise LedgerError(
                        "registry/ledger consistency found invalid host-global transfer lineage"
                    )
                lineage_identities.add(identity)
                lineage_transfer_ids.add(item.transfer_id)

            channel_leases = {
                binding_id: lease
                for binding_id, lease in current.leases.items()
                if lease.channel_id == channel_id
            }
            if set(channel_leases) != set(registrations):
                raise LedgerError(
                    "registry/ledger consistency requires one live lease per registration"
                )
            for binding_id, root in registrations.items():
                lease = channel_leases[binding_id]
                if (
                    lease.state != "active"
                    or lease.vault_binding_id != binding_id
                    or (
                        require_materialized_roots
                        and (
                            root is None
                            or not self._matches_complete_root_identity(
                                lease, root, key
                            )
                        )
                    )
                ):
                    raise LedgerError(
                        "registry/ledger consistency found an incompatible live lease"
                    )

            channel_tombstones = {
                binding_id: lease
                for binding_id, lease in current.tombstones.items()
                if lease.channel_id == channel_id
            }
            if set(channel_tombstones) != set(tombstones):
                raise LedgerError(
                    "registry/ledger consistency requires matching removal tombstones"
                )
            for binding_id, root in tombstones.items():
                retired = channel_tombstones[binding_id]
                if (
                    retired.state != "retired"
                    or retired.vault_binding_id != binding_id
                    or (
                        require_materialized_roots
                        and (
                            root is None
                            or not self._matches_complete_root_identity(
                                retired, root, key
                            )
                        )
                    )
                ):
                    raise LedgerError(
                        "registry/ledger consistency found an incompatible tombstone"
                    )

            registry_lineage_items = tuple(
                item
                for item in transfer_lineage
                if item["destination_channel_id"] == channel_id
            )
            registry_lineage = {
                (
                    item["ownership_transfer_id"],
                    item["source_channel_id"],
                    item["source_binding_id"],
                    item["destination_channel_id"],
                    item["destination_binding_id"],
                ): item
                for item in registry_lineage_items
            }
            ledger_lineage_items = tuple(
                item
                for item in current.transfer_lineage
                if item.destination_channel_id == channel_id
            )
            ledger_lineage = {
                (
                    item.transfer_id,
                    item.source_channel_id,
                    item.source_binding_id,
                    item.destination_channel_id,
                    item.destination_binding_id,
                ): item
                for item in ledger_lineage_items
            }
            if (
                len(registry_lineage) != len(registry_lineage_items)
                or len(ledger_lineage) != len(ledger_lineage_items)
                or set(registry_lineage) != set(ledger_lineage)
            ):
                raise LedgerError(
                    "registry/ledger consistency requires matching transfer lineage"
                )
            roots = dict(registrations) | dict(tombstones)
            for identity, item in ledger_lineage.items():
                destination_binding_id = identity[-1]
                destination_root = roots.get(destination_binding_id)
                if require_materialized_roots and destination_root is None:
                    raise LedgerError(
                        "registry/ledger consistency lineage has no destination root"
                    )
                lineage_lease = OwnershipLease(
                    channel_id=item.destination_channel_id,
                    vault_binding_id=item.destination_binding_id,
                    root_fingerprint=item.root_fingerprint,
                    ancestor_fingerprints=item.ancestor_fingerprints,
                    sealed_root=item.sealed_root,
                    state="lineage",
                )
                if require_materialized_roots and (
                    destination_root is None
                    or not self._matches_complete_root_identity(
                        lineage_lease,
                        destination_root,
                        key,
                    )
                ):
                    raise LedgerError(
                        "registry/ledger consistency found an incompatible lineage fingerprint"
                    )
            return current

    def recover_or_require_active(
        self,
        vault_binding_id: str,
        *,
        channel_id: str,
        root: Path,
        _capability: _StorageMutationCapability | None = None,
    ) -> OwnershipLease:
        """Authenticate an active owner or finish a committed pending reservation."""

        _require_storage_mutation_capability(_capability)
        self._assert_existing_artifacts()
        with self._locked():
            key = self._load_or_create_key_locked(allow_create=False)
            current = self._load_or_create_ledger_locked(key, allow_create=False)
            lease = current.leases.get(vault_binding_id)
            if (
                lease is None
                or lease.channel_id != channel_id
                or not self._matches_root(lease, root, key)
            ):
                raise LedgerError(
                    "registered binding has no authenticated ownership reservation"
                )
            if lease.state == "active":
                return lease
            if lease.state != "pending":
                raise LedgerError("registered binding ownership is not recoverable")
            active = OwnershipLease(**(asdict(lease) | {"state": "active"}))
            leases = dict(current.leases)
            leases[vault_binding_id] = active
            self._write_ledger_locked(self._replace(current, leases=leases), key)
            return active

    def recover_missing_active(
        self,
        *,
        channel_id: str,
        vault_binding_id: str,
        root: Path,
        _capability: _StorageMutationCapability | None = None,
    ) -> OwnershipLease:
        """Reconstruct one lost active lease after an external fenced proof.

        This is intentionally stricter than normal registration recovery: the
        host ledger must contain no live or pending owner at all.  The caller
        supplies the stopped-window/quiescence and backup proof; this method
        only performs the authenticated ledger transaction.
        """

        _require_storage_mutation_capability(_capability)
        self._assert_existing_artifacts()
        with self._locked():
            key = self._load_or_create_key_locked(allow_create=False)
            current = self._load_or_create_ledger_locked(key, allow_create=False)
            if current.transfer is not None or current.tombstones:
                raise LedgerError("lost ownership recovery found non-empty transition history")
            if current.leases:
                raise LedgerError("lost ownership recovery found a foreign or pending owner")
            candidate = self._lease_for_root(
                channel_id=channel_id,
                vault_binding_id=vault_binding_id,
                root=root,
                key=key,
                state="active",
            )
            self._assert_no_collision(
                current, candidate, key=key, allow_same_channel_nested=False
            )
            self._write_ledger_locked(
                self._replace(current, leases={vault_binding_id: candidate}), key
            )
            return candidate

    def reserve(
        self,
        *,
        channel_id: str,
        vault_binding_id: str,
        root: Path,
        allow_same_channel_nested: bool = True,
        _capability: _StorageMutationCapability | None = None,
    ) -> OwnershipLease:
        _require_storage_mutation_capability(_capability)
        with self._locked():
            key = self._load_or_create_key_locked()
            current = self._load_or_create_ledger_locked(key)
            existing = current.leases.get(vault_binding_id)
            if existing is not None:
                if self._matches_root(existing, root, key):
                    return existing
                raise LedgerCollisionError("stable binding already owns a different physical root")
            candidate = self._lease_for_root(
                channel_id=channel_id,
                vault_binding_id=vault_binding_id,
                root=root,
                key=key,
                state="pending",
            )
            self._assert_no_collision(
                current,
                candidate,
                key=key,
                allow_same_channel_nested=allow_same_channel_nested,
            )
            leases = dict(current.leases)
            leases[vault_binding_id] = candidate
            self._write_ledger_locked(self._replace(current, leases=leases), key)
            return candidate

    def activate(
        self,
        vault_binding_id: str,
        *,
        _capability: _StorageMutationCapability | None = None,
    ) -> OwnershipLease:
        _require_storage_mutation_capability(_capability)
        with self._locked():
            key = self._load_or_create_key_locked()
            current = self._load_or_create_ledger_locked(key)
            lease = current.leases.get(vault_binding_id)
            if lease is None or lease.state not in {"pending", "active"}:
                raise LedgerError("ownership reservation is missing or invalid")
            active = OwnershipLease(**(asdict(lease) | {"state": "active"}))
            leases = dict(current.leases)
            leases[vault_binding_id] = active
            self._write_ledger_locked(self._replace(current, leases=leases), key)
            return active

    def release_to_tombstone(
        self,
        vault_binding_id: str,
        *,
        _capability: _StorageMutationCapability | None = None,
    ) -> OwnershipLease:
        _require_storage_mutation_capability(_capability)
        with self._locked():
            key = self._load_or_create_key_locked()
            current = self._load_or_create_ledger_locked(key)
            lease = current.leases.get(vault_binding_id)
            if lease is None:
                raise LedgerError("active ownership lease is missing")
            retired = OwnershipLease(**(asdict(lease) | {"state": "retired"}))
            leases = dict(current.leases)
            del leases[vault_binding_id]
            tombstones = dict(current.tombstones)
            tombstones[vault_binding_id] = retired
            self._write_ledger_locked(
                self._replace(current, leases=leases, tombstones=tombstones),
                key,
            )
            return retired

    def reactivate(
        self,
        vault_binding_id: str,
        *,
        channel_id: str,
        root: Path,
        _capability: _StorageMutationCapability | None = None,
    ) -> OwnershipLease:
        _require_storage_mutation_capability(_capability)
        with self._locked():
            key = self._load_or_create_key_locked()
            current = self._load_or_create_ledger_locked(key)
            retired = current.tombstones.get(vault_binding_id)
            if retired is None or not self._matches_root(retired, root, key):
                raise LedgerCollisionError("root does not match immutable predecessor lineage")
            active = self._lease_for_root(
                channel_id=channel_id,
                vault_binding_id=vault_binding_id,
                root=root,
                key=key,
                state="active",
            )
            self._assert_no_collision(
                current, active, key=key, allow_same_channel_nested=True
            )
            leases = dict(current.leases)
            leases[vault_binding_id] = active
            self._write_ledger_locked(self._replace(current, leases=leases), key)
            return active

    def active_owner(self, vault_binding_id: str) -> OwnershipLease | None:
        lease = self.load().leases.get(vault_binding_id)
        return lease if lease is not None and lease.state == "active" else None

    @contextmanager
    def active_binding_fence(
        self,
        vault_binding_id: str,
        *,
        channel_id: str,
        root: Path,
    ) -> Iterator[OwnershipLease]:
        """Hold the host-global fence while a per-binding fence is acquired."""

        self._assert_existing_artifacts()
        with self._locked():
            key = self._load_or_create_key_locked(allow_create=False)
            current = self._load_or_create_ledger_locked(key, allow_create=False)
            lease = current.leases.get(vault_binding_id)
            if (
                lease is None
                or lease.state != "active"
                or lease.channel_id != channel_id
                or not self._matches_root(lease, root, key)
            ):
                raise LedgerError(
                    "binding effect acquisition requires the matching active ownership lease"
                )
            yield lease

    def begin_transfer(
        self,
        *,
        source_binding_id: str,
        destination_channel_id: str,
        destination_binding_id: str,
        _capability: _StorageMutationCapability | None = None,
    ) -> TransferReservation:
        _require_storage_mutation_capability(_capability)
        with self._locked():
            key = self._load_or_create_key_locked()
            current = self._load_or_create_ledger_locked(key)
            if current.transfer is not None:
                if (
                    current.transfer.source_binding_id == source_binding_id
                    and current.transfer.destination_binding_id == destination_binding_id
                ):
                    return current.transfer
                raise LedgerError("another ownership transfer is already recoverable")
            source = current.leases.get(source_binding_id)
            if source is None or source.state != "active":
                raise LedgerError("source lease is not active")
            reservation = TransferReservation(
                transfer_id=f"transfer-{uuid4()}",
                source_channel_id=source.channel_id,
                source_binding_id=source_binding_id,
                destination_channel_id=destination_channel_id,
                destination_binding_id=destination_binding_id,
                root_fingerprint=source.root_fingerprint,
                ancestor_fingerprints=source.ancestor_fingerprints,
                sealed_root=source.sealed_root,
            )
            leases = dict(current.leases)
            del leases[source_binding_id]
            self._write_ledger_locked(self._replace(current, leases=leases, transfer=reservation), key)
            return reservation

    def activate_transfer(
        self,
        *,
        _capability: _StorageMutationCapability | None = None,
    ) -> OwnershipLease:
        _require_storage_mutation_capability(_capability)
        with self._locked():
            key = self._load_or_create_key_locked()
            current = self._load_or_create_ledger_locked(key)
            transfer = current.transfer
            if transfer is None:
                raise LedgerError("no transfer reservation is recoverable")
            active = OwnershipLease(
                channel_id=transfer.destination_channel_id,
                vault_binding_id=transfer.destination_binding_id,
                root_fingerprint=transfer.root_fingerprint,
                ancestor_fingerprints=transfer.ancestor_fingerprints,
                sealed_root=transfer.sealed_root,
                state="active",
            )
            leases = dict(current.leases)
            leases[active.vault_binding_id] = active
            tombstones = dict(current.tombstones)
            tombstones[transfer.source_binding_id] = OwnershipLease(
                channel_id=transfer.source_channel_id,
                vault_binding_id=transfer.source_binding_id,
                root_fingerprint=transfer.root_fingerprint,
                ancestor_fingerprints=transfer.ancestor_fingerprints,
                sealed_root=transfer.sealed_root,
                state="retired",
            )
            lineage = current.transfer_lineage + (
                OwnershipTransferLineage(
                    transfer_id=transfer.transfer_id,
                    source_channel_id=transfer.source_channel_id,
                    source_binding_id=transfer.source_binding_id,
                    destination_channel_id=transfer.destination_channel_id,
                    destination_binding_id=transfer.destination_binding_id,
                    root_fingerprint=transfer.root_fingerprint,
                    ancestor_fingerprints=transfer.ancestor_fingerprints,
                    sealed_root=transfer.sealed_root,
                ),
            )
            self._write_ledger_locked(
                self._replace(
                    current,
                    leases=leases,
                    tombstones=tombstones,
                    transfer=None,
                    transfer_lineage=lineage,
                ),
                key,
            )
            return active

    def bootstrap_legacy_owners(
        self,
        owners: list[LegacyOwner],
        *,
        inventory_complete: bool,
        writers_drained: bool,
        _capability: _StorageMutationCapability | None = None,
    ) -> LedgerSnapshot:
        _require_storage_mutation_capability(_capability)
        if not inventory_complete or not writers_drained:
            raise LedgerCollisionError("legacy owner inventory must be complete and writers drained")
        with self._locked():
            key = self._load_or_create_key_locked()
            current = self._load_or_create_ledger_locked(key)
            if current.legacy_bootstrap_complete:
                return current
            staged = current
            leases = dict(current.leases)
            for owner in owners:
                candidate = self._lease_for_root(
                    channel_id=owner.channel_id,
                    vault_binding_id=owner.vault_binding_id,
                    root=owner.root,
                    key=key,
                    state="active",
                )
                self._assert_no_collision(
                    staged, candidate, key=key, allow_same_channel_nested=True
                )
                leases[candidate.vault_binding_id] = candidate
                staged = self._replace(staged, leases=leases)
            staged = self._replace(staged, legacy_bootstrap_complete=True)
            self._write_ledger_locked(staged, key)
            return staged

    def rotate_key(
        self,
        *,
        precondition: Callable[[LedgerSnapshot, Mapping[str, Path]], None],
        crash_after: str | None = None,
        _capability: _StorageMutationCapability | None = None,
    ) -> LedgerSnapshot:
        _require_storage_mutation_capability(_capability)
        self._assert_existing_artifacts()
        with self._locked(recover_rotation=False):
            if self.rotation_path.exists():
                raise LedgerKeyError(
                    "pending key rotation must be recovered before another rotation"
                )
            old_key = self._load_or_create_key_locked(allow_create=False)
            current = self._load_or_create_ledger_locked(old_key, allow_create=False)
            live_roots = {
                binding: Path(self._open_root(lease.sealed_root, old_key))
                for binding, lease in current.leases.items()
            }
            precondition(current, live_roots)
            new_key = _KeyMaterial(
                key_id=f"key-{uuid4()}",
                generation=old_key.generation + 1,
                secret=secrets.token_bytes(32),
            )

            def rotate_lease(lease: OwnershipLease) -> OwnershipLease:
                root = Path(self._open_root(lease.sealed_root, old_key))
                return self._lease_for_root(
                    channel_id=lease.channel_id,
                    vault_binding_id=lease.vault_binding_id,
                    root=root,
                    key=new_key,
                    state=lease.state,
                )

            leases = {binding: rotate_lease(lease) for binding, lease in current.leases.items()}
            tombstones = {
                binding: rotate_lease(lease) for binding, lease in current.tombstones.items()
            }
            transfer = current.transfer
            if transfer is not None:
                root = Path(self._open_root(transfer.sealed_root, old_key))
                rotated_root = self._lease_for_root(
                    channel_id=transfer.source_channel_id,
                    vault_binding_id=transfer.source_binding_id,
                    root=root,
                    key=new_key,
                    state="transferring",
                )
                transfer = TransferReservation(
                    **(
                        asdict(transfer)
                        | {
                            "root_fingerprint": rotated_root.root_fingerprint,
                            "ancestor_fingerprints": rotated_root.ancestor_fingerprints,
                            "sealed_root": rotated_root.sealed_root,
                        }
                    )
                )
            transfer_lineage: list[OwnershipTransferLineage] = []
            for item in current.transfer_lineage:
                root = Path(self._open_root(item.sealed_root, old_key))
                rotated_root = self._lease_for_root(
                    channel_id=item.destination_channel_id,
                    vault_binding_id=item.destination_binding_id,
                    root=root,
                    key=new_key,
                    state="lineage",
                )
                transfer_lineage.append(
                    replace(
                        item,
                        root_fingerprint=rotated_root.root_fingerprint,
                        ancestor_fingerprints=rotated_root.ancestor_fingerprints,
                        sealed_root=rotated_root.sealed_root,
                    )
                )
            rotated = LedgerSnapshot(
                schema=LEDGER_SCHEMA,
                generation=new_key.generation,
                key_id=new_key.key_id,
                leases=leases,
                tombstones=tombstones,
                transfer=transfer,
                transfer_lineage=tuple(transfer_lineage),
                legacy_bootstrap_complete=current.legacy_bootstrap_complete,
            )
            _atomic_private_json(
                self.rotation_path,
                {
                    "schema": ROTATION_SCHEMA,
                    "key": self._key_value(new_key),
                    "ledger": self._ledger_value(rotated),
                },
            )
            self._write_key_locked(new_key)
            if crash_after == "key_commit":
                raise RuntimeError("injected crash after key_commit")
            self._write_ledger_locked(rotated, new_key)
            self.rotation_path.unlink(missing_ok=True)
            _fsync_directory(self.root)
            return rotated

    def root_for_transfer(self, transfer: TransferReservation) -> Path:
        with self._locked():
            key = self._load_or_create_key_locked()
            current = self._load_or_create_ledger_locked(key)
            if current.transfer != transfer:
                raise LedgerError("transfer reservation changed")
            return Path(self._open_root(transfer.sealed_root, key))

    def _assert_no_collision(
        self,
        current: LedgerSnapshot,
        candidate: OwnershipLease,
        *,
        key: _KeyMaterial,
        allow_same_channel_nested: bool,
    ) -> None:
        leases = list(current.leases.values()) + list(current.tombstones.values())
        if current.transfer is not None:
            transfer = current.transfer
            leases.append(
                OwnershipLease(
                    channel_id=transfer.destination_channel_id,
                    vault_binding_id=transfer.destination_binding_id,
                    root_fingerprint=transfer.root_fingerprint,
                    ancestor_fingerprints=transfer.ancestor_fingerprints,
                    sealed_root=transfer.sealed_root,
                    state="transferring",
                )
            )
        for lease in leases:
            exact = candidate.root_fingerprint == lease.root_fingerprint
            overlap = (
                exact
                or candidate.root_fingerprint in lease.ancestor_fingerprints
                or lease.root_fingerprint in candidate.ancestor_fingerprints
            )
            if not overlap:
                try:
                    candidate_root = Path(self._open_root(candidate.sealed_root, key))
                    lease_root = Path(self._open_root(lease.sealed_root, key))
                    overlap = (
                        candidate_root != lease_root
                        and (
                            candidate_root.is_relative_to(lease_root)
                            or lease_root.is_relative_to(candidate_root)
                        )
                    )
                except (LedgerError, OSError, ValueError):
                    overlap = False
            if not overlap or lease.vault_binding_id == candidate.vault_binding_id:
                continue
            if (
                allow_same_channel_nested
                and not exact
                and lease.channel_id == candidate.channel_id
            ):
                continue
            raise LedgerCollisionError("canonical content roots overlap across ownership domains")

    def _matches_root(self, lease: OwnershipLease, root: Path, key: _KeyMaterial) -> bool:
        return lease.root_fingerprint == self._lease_for_root(
            channel_id=lease.channel_id,
            vault_binding_id=lease.vault_binding_id,
            root=root,
            key=key,
            state=lease.state,
        ).root_fingerprint

    def _matches_complete_root_identity(
        self,
        lease: OwnershipLease,
        root: Path,
        key: _KeyMaterial,
    ) -> bool:
        expected = self._lease_for_root(
            channel_id=lease.channel_id,
            vault_binding_id=lease.vault_binding_id,
            root=root,
            key=key,
            state=lease.state,
        )
        try:
            sealed_root = Path(self._open_root(lease.sealed_root, key)).expanduser().resolve(
                strict=False
            )
        except (LedgerError, UnicodeError):
            return False
        return (
            lease.root_fingerprint == expected.root_fingerprint
            and lease.ancestor_fingerprints == expected.ancestor_fingerprints
            and sealed_root == Path(root).expanduser().resolve(strict=False)
        )

    def _matches_materialized_root(
        self,
        lease: OwnershipLease,
        root: Path,
        key: _KeyMaterial,
    ) -> bool:
        """Match a bind-mounted alias by physical root without trusting its path."""

        identity = resolve_filesystem_root_identity(root)
        if not identity.materialized:
            return False
        primary, _ = _identity_material(root)
        return hmac.compare_digest(
            lease.root_fingerprint,
            _fingerprint(primary, key.secret),
        )

    def _has_complete_self_identity(
        self,
        lease: OwnershipLease,
        key: _KeyMaterial,
    ) -> bool:
        try:
            root = Path(self._open_root(lease.sealed_root, key))
            return self._matches_complete_root_identity(lease, root, key)
        except (FilesystemIdentityError, LedgerError, UnicodeError):
            return False

    def _has_authenticated_stored_identity(
        self,
        lease: OwnershipLease,
        key: _KeyMaterial,
    ) -> bool:
        """Authenticate stored identity fields without opening the content root."""

        try:
            root = Path(self._open_root(lease.sealed_root, key))
        except (LedgerError, UnicodeError, ValueError):
            return False
        fingerprints = (lease.root_fingerprint, *lease.ancestor_fingerprints)
        return (
            root.is_absolute()
            and bool(fingerprints)
            and all(
                len(value) == 64
                and all(character in "0123456789abcdef" for character in value)
                for value in fingerprints
            )
        )

    def _lease_for_root(
        self,
        *,
        channel_id: str,
        vault_binding_id: str,
        root: Path,
        key: _KeyMaterial,
        state: str,
    ) -> OwnershipLease:
        canonical, ancestors = _identity_material(root)
        return OwnershipLease(
            channel_id=channel_id,
            vault_binding_id=vault_binding_id,
            root_fingerprint=_fingerprint(canonical, key.secret),
            ancestor_fingerprints=tuple(_fingerprint(item, key.secret) for item in ancestors),
            sealed_root=self._seal_root(str(Path(root).expanduser().resolve(strict=False)), key),
            state=state,
        )

    def _seal_root(self, value: str, key: _KeyMaterial) -> str:
        plaintext = value.encode("utf-8")
        nonce = secrets.token_bytes(16)
        stream = _keystream(key.secret, nonce, len(plaintext))
        ciphertext = bytes(left ^ right for left, right in zip(plaintext, stream, strict=True))
        tag = hmac.new(key.secret, nonce + ciphertext, hashlib.sha256).digest()
        return base64.urlsafe_b64encode(nonce + tag + ciphertext).decode("ascii")

    def _open_root(self, value: str, key: _KeyMaterial) -> str:
        try:
            payload = base64.urlsafe_b64decode(value.encode("ascii"))
        except (ValueError, UnicodeError) as exc:
            raise LedgerKeyError("sealed root locator is malformed") from exc
        if len(payload) < 48:
            raise LedgerKeyError("sealed root locator is incomplete")
        nonce, tag, ciphertext = payload[:16], payload[16:48], payload[48:]
        expected = hmac.new(key.secret, nonce + ciphertext, hashlib.sha256).digest()
        if not hmac.compare_digest(tag, expected):
            raise LedgerKeyError("sealed root locator does not match the protected key")
        stream = _keystream(key.secret, nonce, len(ciphertext))
        return bytes(left ^ right for left, right in zip(ciphertext, stream, strict=True)).decode("utf-8")

    def _replace(self, current: LedgerSnapshot, **changes: Any) -> LedgerSnapshot:
        return replace(current, **changes)

    @contextmanager
    def _locked(self, *, recover_rotation: bool = True) -> Iterator[None]:
        _ensure_private_directory(self.root)
        descriptor = os.open(
            self.lock_path,
            os.O_RDWR | os.O_CREAT | getattr(os, "O_NOFOLLOW", 0),
            0o600,
        )
        os.fchmod(descriptor, 0o600)
        with os.fdopen(descriptor, "a+b", closefd=True) as handle:
            fcntl.flock(handle.fileno(), fcntl.LOCK_EX)
            try:
                if recover_rotation:
                    self._recover_rotation_locked()
                yield
            finally:
                fcntl.flock(handle.fileno(), fcntl.LOCK_UN)

    def _assert_existing_artifacts(self) -> None:
        if not self.root.is_dir():
            raise LedgerKeyError("ownership state directory is missing")
        metadata = self.root.lstat()
        if (
            not stat.S_ISDIR(metadata.st_mode)
            or metadata.st_uid != os.geteuid()
            or metadata.st_mode & 0o777 != 0o700
        ):
            raise LedgerKeyError("ownership state directory is unsafe")
        if not self.path.is_file() or not self.key_path.is_file():
            raise LedgerKeyError(
                "established registry requires protected ownership ledger and key recovery"
            )

    def _load_or_create_key_locked(self, *, allow_create: bool = True) -> _KeyMaterial:
        if not self.key_path.exists():
            if self.path.exists() or not allow_create:
                raise LedgerKeyError("ownership ledger exists without its protected key")
            key = _KeyMaterial(f"key-{uuid4()}", 1, secrets.token_bytes(32))
            self._write_key_locked(key)
            return key
        _assert_private_file(self.key_path)
        try:
            value = json.loads(self.key_path.read_text(encoding="utf-8"))
            if value.get("schema") != KEY_SCHEMA:
                raise ValueError
            secret = base64.b64decode(value["secret"], validate=True)
            key = _KeyMaterial(str(value["key_id"]), int(value["generation"]), secret)
        except (OSError, ValueError, KeyError, TypeError, json.JSONDecodeError) as exc:
            raise LedgerKeyError("protected ownership key is invalid") from exc
        if len(key.secret) != 32 or key.generation < 1:
            raise LedgerKeyError("protected ownership key is unsafe")
        return key

    def _write_key_locked(self, key: _KeyMaterial) -> None:
        _atomic_private_json(self.key_path, self._key_value(key))

    def _key_value(self, key: _KeyMaterial) -> dict[str, object]:
        return {
            "schema": KEY_SCHEMA,
            "key_id": key.key_id,
            "generation": key.generation,
            "secret": base64.b64encode(key.secret).decode("ascii"),
        }

    def _parse_key_value(self, value: Mapping[str, Any]) -> _KeyMaterial:
        key_id = value["key_id"]
        generation = value["generation"]
        encoded_secret = value["secret"]
        if (
            value.get("schema") != KEY_SCHEMA
            or not isinstance(key_id, str)
            or not key_id.strip()
            or isinstance(generation, bool)
            or not isinstance(generation, int)
            or generation < 1
            or not isinstance(encoded_secret, str)
        ):
            raise ValueError
        return _KeyMaterial(
            key_id=key_id,
            generation=generation,
            secret=base64.b64decode(encoded_secret, validate=True),
        )

    def _load_or_create_ledger_locked(
        self,
        key: _KeyMaterial,
        *,
        allow_create: bool = True,
    ) -> LedgerSnapshot:
        if not self.path.exists():
            if not allow_create:
                raise LedgerKeyError("protected ownership key exists without its ownership ledger")
            current = LedgerSnapshot(LEDGER_SCHEMA, key.generation, key.key_id)
            self._write_ledger_locked(current, key)
            return current
        _assert_private_file(self.path)
        try:
            value = json.loads(self.path.read_text(encoding="utf-8"))
            current = self._parse_ledger_value(value)
        except (OSError, ValueError, KeyError, TypeError, json.JSONDecodeError) as exc:
            raise LedgerError("ownership ledger is invalid") from exc
        if current.key_id != key.key_id or current.generation != key.generation:
            raise LedgerKeyError("ownership ledger/key generation mismatch")
        if current.schema == LEGACY_LEDGER_SCHEMA:
            current = self._migrate_legacy_ledger(current, key)
            self._write_ledger_locked(current, key)
        return current

    def _parse_ledger_value(self, value: Mapping[str, Any]) -> LedgerSnapshot:
        schema = value.get("schema")
        generation = value["generation"]
        key_id = value["key_id"]
        legacy_bootstrap_complete = value.get("legacy_bootstrap_complete", False)
        if (
            schema not in {LEGACY_LEDGER_SCHEMA, LEDGER_SCHEMA}
            or isinstance(generation, bool)
            or not isinstance(generation, int)
            or generation < 1
            or not isinstance(key_id, str)
            or not key_id.strip()
            or not isinstance(legacy_bootstrap_complete, bool)
        ):
            raise ValueError
        leases = {
            binding: OwnershipLease(
                **(raw | {"ancestor_fingerprints": tuple(raw["ancestor_fingerprints"])})
            )
            for binding, raw in value.get("leases", {}).items()
        }
        tombstones = {
            binding: OwnershipLease(
                **(raw | {"ancestor_fingerprints": tuple(raw["ancestor_fingerprints"])})
            )
            for binding, raw in value.get("tombstones", {}).items()
        }
        transfer_raw = value.get("transfer")
        transfer = (
            None
            if transfer_raw is None
            else TransferReservation(
                **(
                    transfer_raw
                    | {"ancestor_fingerprints": tuple(transfer_raw["ancestor_fingerprints"])}
                )
            )
        )
        transfer_lineage = tuple(
            OwnershipTransferLineage(
                **(raw | {"ancestor_fingerprints": tuple(raw["ancestor_fingerprints"])})
            )
            for raw in value.get("transfer_lineage", [])
        )
        return LedgerSnapshot(
            schema=schema,
            generation=generation,
            key_id=key_id,
            leases=leases,
            tombstones=tombstones,
            transfer=transfer,
            transfer_lineage=transfer_lineage,
            legacy_bootstrap_complete=legacy_bootstrap_complete,
        )

    def _migrate_legacy_ledger(
        self,
        current: LedgerSnapshot,
        key: _KeyMaterial,
    ) -> LedgerSnapshot:
        """Converge authenticated v1 parent identities without replacing authority."""

        def migrate_lease(lease: OwnershipLease) -> OwnershipLease:
            return replace(
                lease,
                ancestor_fingerprints=self._migrated_legacy_ancestors(
                    root_fingerprint=lease.root_fingerprint,
                    ancestor_fingerprints=lease.ancestor_fingerprints,
                    sealed_root=lease.sealed_root,
                    key=key,
                ),
            )

        def valid_identifier(value: object) -> bool:
            return isinstance(value, str) and bool(value.strip())

        try:
            if current.schema != LEGACY_LEDGER_SCHEMA:
                raise ValueError
            if any(
                not valid_identifier(binding)
                or not valid_identifier(lease.channel_id)
                or not valid_identifier(lease.vault_binding_id)
                or binding != lease.vault_binding_id
                or lease.state not in {"pending", "active"}
                for binding, lease in current.leases.items()
            ):
                raise ValueError
            if any(
                not valid_identifier(binding)
                or not valid_identifier(lease.channel_id)
                or not valid_identifier(lease.vault_binding_id)
                or binding != lease.vault_binding_id
                or lease.state != "retired"
                for binding, lease in current.tombstones.items()
            ):
                raise ValueError

            leases = {binding: migrate_lease(lease) for binding, lease in current.leases.items()}
            tombstones = {
                binding: migrate_lease(lease) for binding, lease in current.tombstones.items()
            }
            transfer = current.transfer
            if transfer is not None:
                if (
                    any(
                        not valid_identifier(value)
                        for value in (
                            transfer.transfer_id,
                            transfer.source_channel_id,
                            transfer.source_binding_id,
                            transfer.destination_channel_id,
                            transfer.destination_binding_id,
                        )
                    )
                    or transfer.source_channel_id == transfer.destination_channel_id
                    or transfer.source_binding_id == transfer.destination_binding_id
                ):
                    raise ValueError
                transfer = replace(
                    transfer,
                    ancestor_fingerprints=self._migrated_legacy_ancestors(
                        root_fingerprint=transfer.root_fingerprint,
                        ancestor_fingerprints=transfer.ancestor_fingerprints,
                        sealed_root=transfer.sealed_root,
                        key=key,
                    ),
                )

            transfer_lineage: list[OwnershipTransferLineage] = []
            lineage_ids: set[str] = set()
            for item in current.transfer_lineage:
                if (
                    any(
                        not valid_identifier(value)
                        for value in (
                            item.transfer_id,
                            item.source_channel_id,
                            item.source_binding_id,
                            item.destination_channel_id,
                            item.destination_binding_id,
                        )
                    )
                    or item.transfer_id in lineage_ids
                    or item.source_channel_id == item.destination_channel_id
                    or item.source_binding_id == item.destination_binding_id
                ):
                    raise ValueError
                lineage_ids.add(item.transfer_id)
                transfer_lineage.append(
                    replace(
                        item,
                        ancestor_fingerprints=self._migrated_legacy_ancestors(
                            root_fingerprint=item.root_fingerprint,
                            ancestor_fingerprints=item.ancestor_fingerprints,
                            sealed_root=item.sealed_root,
                            key=key,
                        ),
                    )
                )
        except (
            FilesystemIdentityError,
            LedgerError,
            OSError,
            TypeError,
            UnicodeError,
            ValueError,
        ) as exc:
            raise LedgerError(
                "legacy ownership ledger contains unauthenticated identity state"
            ) from exc

        return replace(
            current,
            schema=LEDGER_SCHEMA,
            leases=leases,
            tombstones=tombstones,
            transfer=transfer,
            transfer_lineage=tuple(transfer_lineage),
        )

    def _migrated_legacy_ancestors(
        self,
        *,
        root_fingerprint: str,
        ancestor_fingerprints: Sequence[str],
        sealed_root: str,
        key: _KeyMaterial,
    ) -> tuple[str, ...]:
        fingerprints = (root_fingerprint, *ancestor_fingerprints)
        if not fingerprints or any(
            len(value) != 64 or any(character not in "0123456789abcdef" for character in value)
            for value in fingerprints
        ):
            raise ValueError
        root = Path(self._open_root(sealed_root, key))
        if not root.is_absolute():
            raise ValueError
        resolved = root.resolve(strict=False)
        if len(ancestor_fingerprints) != len(resolved.parents):
            raise ValueError
        identity = resolve_filesystem_root_identity(resolved)
        if not identity.materialized:
            raise ValueError
        primary, ancestors = _identity_material(resolved)
        if not hmac.compare_digest(root_fingerprint, _fingerprint(primary, key.secret)):
            raise ValueError
        return tuple(_fingerprint(item, key.secret) for item in ancestors)

    def _write_ledger_locked(self, current: LedgerSnapshot, key: _KeyMaterial) -> None:
        if current.key_id != key.key_id or current.generation != key.generation:
            raise LedgerKeyError("cannot persist mixed ownership key generations")
        if current.schema != LEDGER_SCHEMA:
            raise LedgerError("cannot persist an unsupported ownership ledger schema")
        _atomic_private_json(self.path, self._ledger_value(current))

    def _ledger_value(self, current: LedgerSnapshot) -> dict[str, object]:
        return {
            "schema": current.schema,
            "generation": current.generation,
            "key_id": current.key_id,
            "leases": {key: asdict(value) for key, value in sorted(current.leases.items())},
            "tombstones": {
                key: asdict(value) for key, value in sorted(current.tombstones.items())
            },
            "transfer": None if current.transfer is None else asdict(current.transfer),
            "transfer_lineage": [asdict(item) for item in current.transfer_lineage],
            "legacy_bootstrap_complete": current.legacy_bootstrap_complete,
        }

    def _recover_rotation_locked(self) -> None:
        if not self.rotation_path.exists():
            return
        _assert_private_file(self.rotation_path)
        try:
            journal = json.loads(self.rotation_path.read_text(encoding="utf-8"))
            if journal.get("schema") != ROTATION_SCHEMA:
                raise ValueError
            key = journal["key"]
            ledger = journal["ledger"]
            if not isinstance(key, dict) or not isinstance(ledger, dict):
                raise ValueError
            key_material = self._parse_key_value(key)
            current = self._parse_ledger_value(ledger)
            if (
                len(key_material.secret) != 32
                or current.key_id != key_material.key_id
                or current.generation != key_material.generation
            ):
                raise ValueError
            if current.schema == LEGACY_LEDGER_SCHEMA:
                current = self._migrate_legacy_ledger(current, key_material)
            key = self._key_value(key_material)
            ledger = self._ledger_value(current)
        except (
            LedgerError,
            OSError,
            ValueError,
            KeyError,
            TypeError,
            json.JSONDecodeError,
        ) as exc:
            raise LedgerKeyError("ownership key rotation journal is invalid") from exc
        _atomic_private_json(self.key_path, key)
        _atomic_private_json(self.path, ledger)
        self.rotation_path.unlink()
        _fsync_directory(self.root)


def _identity_material(root: Path) -> tuple[str, tuple[str, ...]]:
    resolved = Path(root).expanduser().resolve(strict=False)
    identity = resolve_filesystem_root_identity(resolved)
    primary = (
        f"inode:{identity.device}:{identity.inode}"
        if identity.materialized
        else f"path:{identity.canonical_path}"
    )
    ancestors: list[str] = []
    for ancestor in resolved.parents:
        # Parent directories can be bind-mount roots whose device/inode
        # identity belongs to the current container mount namespace rather
        # than to the selected vault. Persisting those inode values makes an
        # otherwise identical vault fail cross-container verification. The
        # vault itself remains inode-bound; its parent chain is path-bound.
        ancestors.append(f"path:{ancestor}")
    return primary, tuple(ancestors)


def _fingerprint(value: str, secret: bytes) -> str:
    return hmac.new(secret, value.encode("utf-8"), hashlib.sha256).hexdigest()


def _keystream(secret: bytes, nonce: bytes, size: int) -> bytes:
    output = bytearray()
    counter = 0
    while len(output) < size:
        output.extend(hmac.new(secret, nonce + counter.to_bytes(8, "big"), hashlib.sha256).digest())
        counter += 1
    return bytes(output[:size])


def _ensure_private_directory(path: Path) -> None:
    if not path.exists():
        path.mkdir(parents=True, mode=0o700)
    metadata = path.lstat()
    if not stat.S_ISDIR(metadata.st_mode) or metadata.st_uid != os.geteuid():
        raise LedgerError("ownership state directory is unsafe")
    if metadata.st_mode & 0o777 != 0o700:
        os.chmod(path, 0o700)


def _assert_private_file(path: Path) -> None:
    metadata = path.lstat()
    if not stat.S_ISREG(metadata.st_mode) or metadata.st_uid != os.geteuid():
        raise LedgerKeyError("ownership state file is unsafe")
    if metadata.st_mode & 0o777 != 0o600:
        raise LedgerKeyError("ownership state file permissions are unsafe")


def _atomic_private_json(path: Path, value: Mapping[str, object]) -> None:
    _ensure_private_directory(path.parent)
    payload = (json.dumps(value, sort_keys=True, separators=(",", ":")) + "\n").encode("utf-8")
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
        directory = os.open(path.parent, os.O_RDONLY | getattr(os, "O_DIRECTORY", 0))
        try:
            os.fsync(directory)
        finally:
            os.close(directory)
    except BaseException:
        temporary.unlink(missing_ok=True)
        raise


def _fsync_directory(path: Path) -> None:
    directory = os.open(path, os.O_RDONLY | getattr(os, "O_DIRECTORY", 0))
    try:
        os.fsync(directory)
    finally:
        os.close(directory)


__all__ = [
    "LedgerCollisionError",
    "LedgerError",
    "LedgerKeyError",
    "LedgerSnapshot",
    "LegacyOwner",
    "OwnershipLease",
    "OwnershipLedger",
    "OwnershipTransferLineage",
    "TransferReservation",
]
