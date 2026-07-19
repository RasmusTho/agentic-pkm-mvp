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
from typing import Any, Callable, Iterator, Mapping
from uuid import uuid4

from app.instance.filesystem_identity import resolve_filesystem_root_identity


LEDGER_SCHEMA = "agentic-pkm.host-ownership-ledger.v1"
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

    def recover_or_require_active(
        self,
        vault_binding_id: str,
        *,
        channel_id: str,
        root: Path,
    ) -> OwnershipLease:
        """Authenticate an active owner or finish a committed pending reservation."""

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

    def reserve(
        self,
        *,
        channel_id: str,
        vault_binding_id: str,
        root: Path,
        allow_same_channel_nested: bool = True,
    ) -> OwnershipLease:
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
                allow_same_channel_nested=allow_same_channel_nested,
            )
            leases = dict(current.leases)
            leases[vault_binding_id] = candidate
            self._write_ledger_locked(self._replace(current, leases=leases), key)
            return candidate

    def activate(self, vault_binding_id: str) -> OwnershipLease:
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

    def release_to_tombstone(self, vault_binding_id: str) -> OwnershipLease:
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

    def reactivate(self, vault_binding_id: str, *, channel_id: str, root: Path) -> OwnershipLease:
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
            self._assert_no_collision(current, active, allow_same_channel_nested=True)
            leases = dict(current.leases)
            leases[vault_binding_id] = active
            self._write_ledger_locked(self._replace(current, leases=leases), key)
            return active

    def active_owner(self, vault_binding_id: str) -> OwnershipLease | None:
        lease = self.load().leases.get(vault_binding_id)
        return lease if lease is not None and lease.state == "active" else None

    def begin_transfer(
        self,
        *,
        source_binding_id: str,
        destination_channel_id: str,
        destination_binding_id: str,
    ) -> TransferReservation:
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

    def activate_transfer(self) -> OwnershipLease:
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
    ) -> LedgerSnapshot:
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
                self._assert_no_collision(staged, candidate, allow_same_channel_nested=True)
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
    ) -> LedgerSnapshot:
        with self._locked():
            old_key = self._load_or_create_key_locked()
            current = self._load_or_create_ledger_locked(old_key)
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
    def _locked(self) -> Iterator[None]:
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

    def _load_or_create_ledger_locked(
        self,
        key: _KeyMaterial,
        *,
        allow_create: bool = True,
    ) -> LedgerSnapshot:
        if not self.path.exists():
            if not allow_create:
                raise LedgerKeyError(
                    "protected ownership key exists without its ownership ledger"
                )
            current = LedgerSnapshot(LEDGER_SCHEMA, key.generation, key.key_id)
            self._write_ledger_locked(current, key)
            return current
        _assert_private_file(self.path)
        try:
            value = json.loads(self.path.read_text(encoding="utf-8"))
            if value.get("schema") != LEDGER_SCHEMA:
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
                    **(
                        raw
                        | {"ancestor_fingerprints": tuple(raw["ancestor_fingerprints"])}
                    )
                )
                for raw in value.get("transfer_lineage", [])
            )
            current = LedgerSnapshot(
                schema=LEDGER_SCHEMA,
                generation=int(value["generation"]),
                key_id=str(value["key_id"]),
                leases=leases,
                tombstones=tombstones,
                transfer=transfer,
                transfer_lineage=transfer_lineage,
                legacy_bootstrap_complete=bool(value.get("legacy_bootstrap_complete", False)),
            )
        except (OSError, ValueError, KeyError, TypeError, json.JSONDecodeError) as exc:
            raise LedgerError("ownership ledger is invalid") from exc
        if current.key_id != key.key_id or current.generation != key.generation:
            raise LedgerKeyError("ownership ledger/key generation mismatch")
        return current

    def _write_ledger_locked(self, current: LedgerSnapshot, key: _KeyMaterial) -> None:
        if current.key_id != key.key_id or current.generation != key.generation:
            raise LedgerKeyError("cannot persist mixed ownership key generations")
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
            secret = base64.b64decode(key["secret"], validate=True)
            if (
                key.get("schema") != KEY_SCHEMA
                or ledger.get("schema") != LEDGER_SCHEMA
                or key.get("key_id") != ledger.get("key_id")
                or key.get("generation") != ledger.get("generation")
                or len(secret) != 32
            ):
                raise ValueError
        except (OSError, ValueError, KeyError, TypeError, json.JSONDecodeError) as exc:
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
        ancestor_identity = resolve_filesystem_root_identity(ancestor)
        ancestors.append(
            f"inode:{ancestor_identity.device}:{ancestor_identity.inode}"
            if ancestor_identity.materialized
            else f"path:{ancestor_identity.canonical_path}"
        )
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
